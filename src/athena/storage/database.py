"""SQLite lifecycle and explicit transaction control."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from athena.common.time import utc_now_us
from athena.storage.schema import initialize_schema


class DatabaseNotStartedError(RuntimeError):
    """Raised when database access is attempted before service startup."""


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
