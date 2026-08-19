from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.security.models import Argon2idParameters
from athena.storage.database import (
    DatabaseSnapshotChangedError,
    SQLiteDatabase,
)

_TEST_KDF = Argon2idParameters(
    iterations=1,
    lanes=1,
    memory_cost_kib=8 * 1024,
    length=32,
)


def _app(root: Path) -> AthenaApplication:
    app = AthenaApplication(
        settings=AthenaSettings(
            local_root=root,
        )
    )
    app.start()
    return app


def _track_writer(
    monkeypatch: pytest.MonkeyPatch,
    database: SQLiteDatabase,
) -> Callable[[], bool]:
    original = database.write_transaction
    state = {"active": False}

    @contextmanager
    def tracked() -> Iterator[sqlite3.Connection]:
        with original() as connection:
            state["active"] = True
            try:
                yield connection
            finally:
                state["active"] = False

    monkeypatch.setattr(
        database,
        "write_transaction",
        tracked,
    )
    return lambda: state["active"]


def test_stable_read_retries_after_external_wal_commit(
    tmp_path: Path,
) -> None:
    database = SQLiteDatabase(
        tmp_path / "stable-read.db"
    )
    database.start()
    external: sqlite3.Connection | None = None

    try:
        database.connection.execute(
            "CREATE TABLE a08_probe(value INTEGER NOT NULL)"
        )

        external = sqlite3.connect(
            database.path,
            timeout=5.0,
            autocommit=True,
        )
        external.execute(
            "PRAGMA busy_timeout = 5000"
        )

        attempts = 0

        def reader(
            connection: sqlite3.Connection,
        ) -> int:
            nonlocal attempts
            attempts += 1
            count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM a08_probe"
                ).fetchone()[0]
            )
            if attempts == 1:
                external.execute(
                    "INSERT INTO a08_probe(value) VALUES (1)"
                )
            return count

        count, snapshot = database.stable_read(
            reader
        )

        assert attempts == 2
        assert count == 1

        with database.write_transaction() as connection:
            database.assert_snapshot_current(
                connection,
                snapshot,
            )

        external.execute(
            "INSERT INTO a08_probe(value) VALUES (2)"
        )

        with pytest.raises(
            DatabaseSnapshotChangedError
        ):
            with database.write_transaction() as connection:
                database.assert_snapshot_current(
                    connection,
                    snapshot,
                )
    finally:
        if external is not None:
            external.close()
        database.stop()


def test_snapshot_fence_detects_same_connection_autocommit_write(
    tmp_path: Path,
) -> None:
    database = SQLiteDatabase(
        tmp_path / "same-connection.db"
    )
    database.start()

    try:
        database.connection.execute(
            "CREATE TABLE a08_probe(value INTEGER NOT NULL)"
        )

        _count, snapshot = database.stable_read(
            lambda connection: int(
                connection.execute(
                    "SELECT COUNT(*) FROM a08_probe"
                ).fetchone()[0]
            )
        )

        database.connection.execute(
            "INSERT INTO a08_probe(value) VALUES (1)"
        )

        with pytest.raises(
            DatabaseSnapshotChangedError
        ):
            with database.write_transaction() as connection:
                database.assert_snapshot_current(
                    connection,
                    snapshot,
                )
    finally:
        database.stop()


def test_logical_delete_schema_discovery_never_runs_under_writer_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _app(
        tmp_path / "logical-delete"
    )

    try:
        chat_id = app.chat.create_chat()
        writer_active = _track_writer(
            monkeypatch,
            app.database,
        )

        scan_states: list[bool] = []
        original_scan = (
            app.lifecycle_deletion
            ._append_schema_references
        )

        def tracked_scan(
            connection: sqlite3.Connection,
            *,
            entity_id,
            entity_type: str,
            dependencies,
        ) -> None:
            scan_states.append(
                writer_active()
            )
            original_scan(
                connection,
                entity_id=entity_id,
                entity_type=entity_type,
                dependencies=dependencies,
            )

        monkeypatch.setattr(
            app.lifecycle_deletion,
            "_append_schema_references",
            tracked_scan,
        )

        preview = app.lifecycle_deletion.preview(
            chat_id
        )
        app.lifecycle_deletion.delete(
            chat_id,
            preview_digest=preview.preview_digest,
        )

        assert len(scan_states) == 2
        assert not any(scan_states)
    finally:
        app.stop()


def test_physical_purge_dependency_discovery_never_runs_under_writer_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _app(
        tmp_path / "physical-purge"
    )
    source_file = tmp_path / "purge.txt"
    source_file.write_text(
        "A-08 physical purge dependency scan",
        encoding="utf-8",
    )

    try:
        captured = app.sources.capture_file(
            source_file
        )
        preview = app.lifecycle_deletion.preview(
            captured.source.source_id
        )
        app.lifecycle_deletion.delete(
            captured.source.source_id,
            preview_digest=preview.preview_digest,
        )

        writer_active = _track_writer(
            monkeypatch,
            app.database,
        )
        scan_states: list[bool] = []
        original_scan = (
            app.lifecycle_purge
            ._payload_reference_blockers
        )

        def tracked_scan(
            connection: sqlite3.Connection,
            *,
            blob_id,
            source_ids,
        ):
            scan_states.append(
                writer_active()
            )
            return original_scan(
                connection,
                blob_id=blob_id,
                source_ids=source_ids,
            )

        monkeypatch.setattr(
            app.lifecycle_purge,
            "_payload_reference_blockers",
            tracked_scan,
        )

        app.lifecycle_purge.purge_deleted_source_blob(
            captured.source.source_id
        )

        assert len(scan_states) == 2
        assert not any(scan_states)
    finally:
        app.stop()


def test_protected_scope_dependency_discovery_never_runs_under_writer_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _app(
        tmp_path / "protected-purge"
    )
    password = b"a08-protected-scope-password"
    source_file = tmp_path / "protected.bin"
    source_file.write_bytes(
        b"A-08 protected scope dependency scan"
    )

    try:
        app.protected_content.initialize_password(
            password,
            parameters=_TEST_KDF,
        )
        scope = app.protected_content.create_scope(
            password,
            neutral_label="a08",
        )
        app.protected_content.unlock_scope(
            scope.protection_scope_id,
            password,
        )
        app.sources.capture_protected_file(
            source_file,
            protection_scope_id=(
                scope.protection_scope_id
            ),
        )

        writer_active = _track_writer(
            monkeypatch,
            app.database,
        )
        scan_states: list[bool] = []
        original_scan = (
            app.protected_scope_purge
            ._source_reference_blockers
        )

        def tracked_scan(
            connection: sqlite3.Connection,
            *,
            sources,
        ):
            scan_states.append(
                writer_active()
            )
            return original_scan(
                connection,
                sources=sources,
            )

        monkeypatch.setattr(
            app.protected_scope_purge,
            "_source_reference_blockers",
            tracked_scan,
        )

        preview = app.protected_scope_purge.preview(
            scope.protection_scope_id
        )
        app.protected_scope_purge.delete(
            scope.protection_scope_id,
            preview_digest=preview.preview_digest,
        )

        assert len(scan_states) == 3
        assert not any(scan_states)
    finally:
        app.stop()
