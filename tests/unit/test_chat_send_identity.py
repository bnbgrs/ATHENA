from __future__ import annotations

import uuid

from athena.chat.repository import ChatRepository
from athena.chat.send_identity import (
    SendOperationState,
    assistant_message_id_for_operation,
    chat_id_for_operation,
    user_message_id_for_operation,
)
from athena.chat.service import ChatService
from athena.storage.database import SQLiteDatabase

_OPERATION_ID = uuid.UUID(
    "11111111-2222-4333-8444-555555555555"
)


def test_send_identity_derivation_is_stable() -> None:
    assert (
        user_message_id_for_operation(
            _OPERATION_ID
        )
        == _OPERATION_ID
    )

    assert (
        assistant_message_id_for_operation(
            _OPERATION_ID
        )
        == assistant_message_id_for_operation(
            _OPERATION_ID
        )
    )

    assert (
        chat_id_for_operation(
            _OPERATION_ID
        )
        == chat_id_for_operation(
            _OPERATION_ID
        )
    )

    assert (
        assistant_message_id_for_operation(
            _OPERATION_ID
        )
        != _OPERATION_ID
    )

    assert (
        chat_id_for_operation(
            _OPERATION_ID
        )
        != _OPERATION_ID
    )

    assert (
        chat_id_for_operation(
            _OPERATION_ID
        )
        != assistant_message_id_for_operation(
            _OPERATION_ID
        )
    )


def test_send_operation_state_transitions(
    tmp_path,
) -> None:
    database = SQLiteDatabase(
        tmp_path / "athena.db"
    )
    database.start()

    try:
        service = ChatService(
            ChatRepository(database)
        )

        chat_id = service.create_chat()

        absent = (
            service.inspect_send_operation(
                chat_id=chat_id,
                operation_id=_OPERATION_ID,
                content="hello",
            )
        )

        assert (
            absent.state
            is SendOperationState.ABSENT
        )
        assert (
            absent.user_message_id
            == _OPERATION_ID
        )
        assert (
            absent.assistant_message_id
            == assistant_message_id_for_operation(
                _OPERATION_ID
            )
        )

        user_message = (
            service.add_user_message(
                chat_id=chat_id,
                content="hello",
                operation_id=_OPERATION_ID,
            )
        )

        assert (
            user_message.message_id
            == _OPERATION_ID
        )

        incomplete = (
            service.inspect_send_operation(
                chat_id=chat_id,
                operation_id=_OPERATION_ID,
                content="hello",
            )
        )

        assert (
            incomplete.state
            is SendOperationState.INCOMPLETE
        )

        assistant_message = (
            service.add_assistant_message(
                chat_id=chat_id,
                content="answer",
                provider_id="lm_studio",
                model_id="primary",
                operation_id=_OPERATION_ID,
            )
        )

        assert (
            assistant_message.message_id
            == assistant_message_id_for_operation(
                _OPERATION_ID
            )
        )

        complete = (
            service.inspect_send_operation(
                chat_id=chat_id,
                operation_id=_OPERATION_ID,
                content="hello",
            )
        )

        assert (
            complete.state
            is SendOperationState.COMPLETE
        )

        persisted = (
            service.load_chat(
                chat_id
            ).messages
        )

        assert [
            message.message_id
            for message in persisted
        ] == [
            _OPERATION_ID,
            assistant_message_id_for_operation(
                _OPERATION_ID
            ),
        ]

    finally:
        database.stop()


def test_send_operation_detects_conflicting_content_or_chat(
    tmp_path,
) -> None:
    database = SQLiteDatabase(
        tmp_path / "athena.db"
    )
    database.start()

    try:
        service = ChatService(
            ChatRepository(database)
        )

        first_chat = service.create_chat()
        second_chat = service.create_chat()

        service.add_user_message(
            chat_id=first_chat,
            content="original",
            operation_id=_OPERATION_ID,
        )

        content_conflict = (
            service.inspect_send_operation(
                chat_id=first_chat,
                operation_id=_OPERATION_ID,
                content="different",
            )
        )

        assert (
            content_conflict.state
            is SendOperationState.CONFLICT
        )

        chat_conflict = (
            service.inspect_send_operation(
                chat_id=second_chat,
                operation_id=_OPERATION_ID,
                content="original",
            )
        )

        assert (
            chat_conflict.state
            is SendOperationState.CONFLICT
        )

    finally:
        database.stop()
