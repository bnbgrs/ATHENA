import pytest

from athena.chat.repository import ChatRepository
from athena.chat.service import ChatService, EmptyMessageError
from athena.storage.database import SQLiteDatabase


def test_local_user_actor_is_reused(tmp_path) -> None:
    database = SQLiteDatabase(tmp_path / "athena.db")
    database.start()
    service = ChatService(ChatRepository(database))

    first = service.ensure_local_user()
    second = service.ensure_local_user()

    assert first == second
    actor_count = database.connection.execute(
        "SELECT COUNT(*) FROM actors WHERE actor_type = 'user'"
    ).fetchone()[0]
    assert actor_count == 1
    database.stop()


def test_blank_user_message_is_rejected_before_persistence(tmp_path) -> None:
    database = SQLiteDatabase(tmp_path / "athena.db")
    database.start()
    service = ChatService(ChatRepository(database))
    chat_id = service.create_chat()

    with pytest.raises(EmptyMessageError):
        service.add_user_message(chat_id=chat_id, content="   ")

    count = database.connection.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0]
    assert count == 0
    database.stop()


def test_chat_list_reports_message_counts(tmp_path) -> None:
    database = SQLiteDatabase(tmp_path / "athena.db")
    database.start()
    service = ChatService(ChatRepository(database))
    first_chat = service.create_chat()
    second_chat = service.create_chat()
    service.add_user_message(chat_id=first_chat, content="one")
    service.add_user_message(chat_id=first_chat, content="two")

    summaries = {summary.chat_id: summary for summary in service.list_chats()}

    assert summaries[first_chat].message_count == 2
    assert summaries[second_chat].message_count == 0
    database.stop()
