"""SQLite lifecycle and explicit transaction control."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from athena.common.time import utc_now_us
from athena.storage.recovery import inspect_database_read_only
from athena.storage.schema import initialize_schema

_ReadResultT = TypeVar("_ReadResultT")


class DatabaseNotStartedError(RuntimeError):
    """Raised when database access is attempted before service startup."""


class DatabaseSnapshotChangedError(RuntimeError):
    """A stable read snapshot is stale before a guarded write."""


@dataclass(frozen=True, slots=True)
class DatabaseReadSnapshot:
    data_version: int
    schema_version: int
    total_changes: int


class SQLiteDatabase:
    """Local transactional ATHENA database service.

    The live database is intentionally local. Writes use explicit
    ``BEGIN IMMEDIATE`` transactions so later writer coordination can be added
    without changing repository semantics.
    """

    name = "sqlite-database"

    def __init__(self, path: Path) -> None:
        self.path = path
        self._connection: sqlite3.Connection | None = None

    @property
    def connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise DatabaseNotStartedError("ATHENA database service is not started.")
        return self._connection

    def start(self) -> None:
        if self._connection is not None:
            return

        inspect_database_read_only(self.path)

        connection = sqlite3.connect(
            self.path,
            timeout=5.0,
            autocommit=True,
        )
        connection.row_factory = sqlite3.Row

        try:
            initialize_schema(connection, created_at_us=utc_now_us())
        except Exception:
            connection.close()
            raise

        self._connection = connection

    def stop(self) -> None:
        if self._connection is None:
            return
        self._connection.close()
        self._connection = None

    @staticmethod
    def _ensure_no_active_transaction(connection: sqlite3.Connection) -> None:
        """Reject nested ATHENA write transactions."""
        if connection.in_transaction:
            raise RuntimeError("Nested ATHENA write transactions are not supported.")

    @staticmethod
    def _rollback_if_active(connection: sqlite3.Connection) -> None:
        """Rollback only while SQLite still reports an active transaction."""
        if connection.in_transaction:
            connection.execute("ROLLBACK")

    @staticmethod
    def _commit_active_transaction(connection: sqlite3.Connection) -> None:
        """Commit the transaction or fail if it ended unexpectedly."""
        if not connection.in_transaction:
            raise RuntimeError(
                "ATHENA write transaction ended unexpectedly before commit."
            )
        connection.execute("COMMIT")

    @staticmethod
    def _read_snapshot_marker(
        connection: sqlite3.Connection,
    ) -> DatabaseReadSnapshot:
        data_version = connection.execute(
            "PRAGMA data_version"
        ).fetchone()
        schema_version = connection.execute(
            "PRAGMA schema_version"
        ).fetchone()

        if data_version is None or schema_version is None:
            raise RuntimeError(
                "ATHENA could not read the SQLite snapshot marker."
            )

        return DatabaseReadSnapshot(
            data_version=int(data_version[0]),
            schema_version=int(schema_version[0]),
            total_changes=int(connection.total_changes),
        )

    def stable_read(
        self,
        reader: Callable[
            [sqlite3.Connection],
            _ReadResultT,
        ],
        *,
        max_attempts: int = 3,
    ) -> tuple[
        _ReadResultT,
        DatabaseReadSnapshot,
    ]:
        """Run a multi-query read on one stable WAL snapshot.

        The callback is forced read-only with ``PRAGMA query_only``. If
        another connection commits while the read snapshot is open, retry
        rather than returning a result assembled from a stale boundary.
        """
        if max_attempts < 1:
            raise ValueError(
                "Stable database read requires at least one attempt."
            )

        connection = self.connection
        self._ensure_no_active_transaction(connection)

        query_only_row = connection.execute(
            "PRAGMA query_only"
        ).fetchone()
        if query_only_row is None:
            raise RuntimeError(
                "ATHENA could not read SQLite query_only state."
            )
        previous_query_only = int(query_only_row[0])

        connection.execute("PRAGMA query_only = ON")
        try:
            for _attempt in range(max_attempts):
                self._ensure_no_active_transaction(
                    connection
                )
                before = self._read_snapshot_marker(
                    connection
                )

                connection.execute("BEGIN")
                try:
                    result = reader(connection)
                except BaseException:
                    self._rollback_if_active(
                        connection
                    )
                    raise

                if not connection.in_transaction:
                    raise RuntimeError(
                        "ATHENA stable read transaction ended "
                        "unexpectedly before commit."
                    )

                try:
                    connection.execute("COMMIT")
                except BaseException:
                    self._rollback_if_active(
                        connection
                    )
                    raise

                after = self._read_snapshot_marker(
                    connection
                )

                if before == after:
                    return result, after

            raise DatabaseSnapshotChangedError(
                "ATHENA database changed repeatedly during stable read."
            )
        finally:
            connection.execute(
                "PRAGMA query_only = "
                + str(previous_query_only)
            )

    def assert_snapshot_current(
        self,
        connection: sqlite3.Connection,
        snapshot: DatabaseReadSnapshot,
    ) -> None:
        """Fence a stable read immediately after BEGIN IMMEDIATE."""
        if connection is not self.connection:
            raise RuntimeError(
                "Database snapshot fence used with another connection."
            )
        if not connection.in_transaction:
            raise RuntimeError(
                "Database snapshot fence requires an active transaction."
            )

        current = self._read_snapshot_marker(
            connection
        )
        if current != snapshot:
            raise DatabaseSnapshotChangedError(
                "ATHENA database changed after stable dependency scan."
            )

    @contextmanager
    def write_transaction(self) -> Iterator[sqlite3.Connection]:
        """Yield one explicit immediate transaction with rollback on failure."""
        connection = self.connection
        self._ensure_no_active_transaction(connection)

        connection.execute("BEGIN IMMEDIATE")
        try:
            yield connection
        except BaseException:
            self._rollback_if_active(connection)
            raise
        else:
            self._commit_active_transaction(connection)
