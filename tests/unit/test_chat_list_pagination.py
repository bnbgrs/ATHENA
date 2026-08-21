from __future__ import annotations

import uuid

import pytest

from athena.chat.repository import ChatRepository

CHAT_ID = uuid.UUID(
    "11111111-1111-1111-1111-111111111111"
)


class _Cursor:
    def fetchall(
        self,
    ) -> list[dict[str, object]]:
        return [
            {
                "chat_id": CHAT_ID.bytes,
                "started_at_us": 123,
                "ended_at_us": None,
                "archive_mode": "standard",
                "lifecycle_state": "active",
                "message_count": 4,
            }
        ]


class _Connection:
    def __init__(self) -> None:
        self.sql: str | None = None
        self.parameters: tuple[
            object,
            ...,
        ] | None = None

    def execute(
        self,
        sql: str,
        parameters: tuple[
            object,
            ...,
        ],
    ) -> _Cursor:
        self.sql = sql
        self.parameters = parameters

        return _Cursor()


class _Database:
    def __init__(self) -> None:
        self.connection = _Connection()


def test_repository_list_chats_applies_limit_and_offset() -> None:
    database = _Database()

    repository = ChatRepository(
        database  # type: ignore[arg-type]
    )

    result = repository.list_chats(
        limit=25,
        offset=75,
    )

    assert len(result) == 1
    assert result[0].chat_id == CHAT_ID
    assert result[0].message_count == 4

    assert database.connection.sql is not None

    normalized_sql = " ".join(
        database.connection.sql.split()
    )

    assert "LIMIT ? OFFSET ?" in normalized_sql

    assert database.connection.parameters == (
        25,
        75,
    )


def test_repository_list_chats_rejects_negative_offset() -> None:
    repository = ChatRepository(
        _Database()  # type: ignore[arg-type]
    )

    with pytest.raises(
        ValueError,
        match="offset",
    ):
        repository.list_chats(
            offset=-1
        )
