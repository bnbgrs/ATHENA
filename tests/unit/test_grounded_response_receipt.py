from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

import pytest

from athena.chat.grounded_receipt import (
    GroundedResponseReceiptConflictError,
    GroundedResponseReceiptCorruptionError,
    GroundedResponseReceiptRepository,
)
from athena.chat.repository import ChatRepository
from athena.chat.service import ChatService
from athena.common.ids import uuid_to_blob
from athena.storage.database import SQLiteDatabase
from athena.storage.schema_contract import (
    GROUNDED_RESPONSE_RECEIPT_MIGRATION_ID,
    GROUNDED_RESPONSE_RECEIPT_SCHEMA_VERSION,
    PROTECTED_SOURCE_SEMANTIC_MIGRATION_ID,
    PROTECTED_SOURCE_SEMANTIC_SCHEMA_VERSION,
)


def _database(
    path: Path,
) -> SQLiteDatabase:
    database = SQLiteDatabase(
        path
    )
    database.start()
    return database


def _chat(
    database: SQLiteDatabase,
) -> uuid.UUID:
    service = ChatService(
        ChatRepository(
            database
        )
    )

    return service.create_chat()


def test_fresh_database_contains_grounded_receipt_schema(
    tmp_path: Path,
) -> None:
    database = _database(
        tmp_path / "athena.db"
    )

    try:
        user_version = int(
            database.connection.execute(
                "PRAGMA user_version"
            ).fetchone()[0]
        )

        assert (
            user_version
            == GROUNDED_RESPONSE_RECEIPT_SCHEMA_VERSION
        )

        table = database.connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name = 'grounded_response_receipts'
            """
        ).fetchone()

        assert table is not None

        metadata = database.connection.execute(
            """
            SELECT
                schema_version,
                last_migration_id,
                minimum_reader_version
            FROM schema_metadata
            WHERE singleton_id = 1
            """
        ).fetchone()

        assert metadata is not None

        assert tuple(metadata) == (
            GROUNDED_RESPONSE_RECEIPT_SCHEMA_VERSION,
            GROUNDED_RESPONSE_RECEIPT_MIGRATION_ID,
            GROUNDED_RESPONSE_RECEIPT_SCHEMA_VERSION,
        )

    finally:
        database.stop()


def test_v39_database_migrates_to_v40(
    tmp_path: Path,
) -> None:
    path = tmp_path / "athena.db"

    database = _database(
        path
    )

    with database.write_transaction() as connection:
        connection.execute(
            """
            DROP INDEX
            idx_grounded_response_receipts_chat
            """
        )

        connection.execute(
            """
            DROP TABLE grounded_response_receipts
            """
        )

        connection.execute(
            """
            UPDATE schema_metadata
            SET schema_version = ?,
                last_migration_id = ?,
                minimum_reader_version = ?
            WHERE singleton_id = 1
            """,
            (
                PROTECTED_SOURCE_SEMANTIC_SCHEMA_VERSION,
                PROTECTED_SOURCE_SEMANTIC_MIGRATION_ID,
                PROTECTED_SOURCE_SEMANTIC_SCHEMA_VERSION,
            ),
        )

        connection.execute(
            f"PRAGMA user_version = "
            f"{PROTECTED_SOURCE_SEMANTIC_SCHEMA_VERSION}"
        )

    database.stop()

    migrated = SQLiteDatabase(
        path
    )

    migrated.start()

    try:
        user_version = int(
            migrated.connection.execute(
                "PRAGMA user_version"
            ).fetchone()[0]
        )

        assert (
            user_version
            == GROUNDED_RESPONSE_RECEIPT_SCHEMA_VERSION
        )

        table = migrated.connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name = 'grounded_response_receipts'
            """
        ).fetchone()

        assert table is not None

    finally:
        migrated.stop()


def test_receipt_store_load_and_idempotent_replay(
    tmp_path: Path,
) -> None:
    database = _database(
        tmp_path / "athena.db"
    )

    try:
        chat_id = _chat(
            database
        )

        operation_id = uuid.uuid4()
        processing_run_id = uuid.uuid4()

        repository = GroundedResponseReceiptRepository(
            database
        )

        first = repository.store(
            operation_id=operation_id,
            chat_id=chat_id,
            processing_run_id=processing_run_id,
            payload_json="""
            {
                "thread": {"chat_id": "chat"},
                "evidence": [{"id": "e1", "score": 0.75}],
                "personal_memory": [],
                "grounding": {"mode": "grounded"}
            }
            """,
        )

        assert first.operation_id == operation_id
        assert first.chat_id == chat_id
        assert first.processing_run_id == processing_run_id

        assert first.payload_json == (
            '{"evidence":[{"id":"e1","score":0.75}],'
            '"grounding":{"mode":"grounded"},'
            '"personal_memory":[],'
            '"thread":{"chat_id":"chat"}}'
        )

        loaded = repository.load(
            operation_id
        )

        assert loaded == first

        duplicate = repository.store(
            operation_id=operation_id,
            chat_id=chat_id,
            processing_run_id=processing_run_id,
            payload_json=(
                '{"personal_memory":[],'
                '"thread":{"chat_id":"chat"},'
                '"grounding":{"mode":"grounded"},'
                '"evidence":[{"score":0.75,"id":"e1"}]}'
            ),
        )

        assert duplicate == first

        count = database.connection.execute(
            """
            SELECT COUNT(*)
            FROM grounded_response_receipts
            WHERE operation_id = ?
            """,
            (
                uuid_to_blob(
                    operation_id
                ),
            ),
        ).fetchone()

        assert count is not None
        assert int(count[0]) == 1

    finally:
        database.stop()


def test_receipt_conflicting_operation_fails_closed(
    tmp_path: Path,
) -> None:
    database = _database(
        tmp_path / "athena.db"
    )

    try:
        chat_id = _chat(
            database
        )

        operation_id = uuid.uuid4()
        processing_run_id = uuid.uuid4()

        repository = GroundedResponseReceiptRepository(
            database
        )

        repository.store(
            operation_id=operation_id,
            chat_id=chat_id,
            processing_run_id=processing_run_id,
            payload_json='{"answer":"first"}',
        )

        with pytest.raises(
            GroundedResponseReceiptConflictError
        ):
            repository.store(
                operation_id=operation_id,
                chat_id=chat_id,
                processing_run_id=processing_run_id,
                payload_json='{"answer":"different"}',
            )

    finally:
        database.stop()


def test_receipt_checksum_corruption_fails_closed(
    tmp_path: Path,
) -> None:
    database = _database(
        tmp_path / "athena.db"
    )

    try:
        chat_id = _chat(
            database
        )

        operation_id = uuid.uuid4()

        repository = GroundedResponseReceiptRepository(
            database
        )

        repository.store(
            operation_id=operation_id,
            chat_id=chat_id,
            processing_run_id=uuid.uuid4(),
            payload_json='{"answer":"durable"}',
        )

        with database.write_transaction() as connection:
            connection.execute(
                """
                UPDATE grounded_response_receipts
                SET payload_sha256 = ?
                WHERE operation_id = ?
                """,
                (
                    "0" * 64,
                    uuid_to_blob(
                        operation_id
                    ),
                ),
            )

        with pytest.raises(
            GroundedResponseReceiptCorruptionError
        ):
            repository.load(
                operation_id
            )

    finally:
        database.stop()


def test_receipt_chat_foreign_key_fails_closed(
    tmp_path: Path,
) -> None:
    database = _database(
        tmp_path / "athena.db"
    )

    try:
        repository = GroundedResponseReceiptRepository(
            database
        )

        with pytest.raises(
            sqlite3.IntegrityError
        ):
            repository.store(
                operation_id=uuid.uuid4(),
                chat_id=uuid.uuid4(),
                processing_run_id=uuid.uuid4(),
                payload_json='{"answer":"orphan"}',
            )

    finally:
        database.stop()
