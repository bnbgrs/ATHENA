import uuid

import pytest

from athena.chat.models import MessageType
from athena.chat.repository import (
    ChatNotFoundError,
    ChatRepository,
    UnsupportedArchiveModeError,
)
from athena.storage.database import SQLiteDatabase


def test_standard_chat_and_messages_survive_database_restart(tmp_path) -> None:
    path = tmp_path / "athena.db"

    first_database = SQLiteDatabase(path)
    first_database.start()
    first_repository = ChatRepository(first_database)

    user_id = first_repository.create_actor(actor_type="user", display_name="User")
    assistant_id = first_repository.create_actor(
        actor_type="primary_model", display_name="Primary Model"
    )
    chat_id = first_repository.create_chat(actor_id=user_id)
    first_message = first_repository.append_message(
        chat_id=chat_id,
        actor_id=user_id,
        message_type=MessageType.USER,
        content="Remember this after restart.",
    )
    second_message = first_repository.append_message(
        chat_id=chat_id,
        actor_id=assistant_id,
        message_type=MessageType.ASSISTANT,
        content="Persisted.",
    )
    first_database.stop()

    second_database = SQLiteDatabase(path)
    second_database.start()
    second_repository = ChatRepository(second_database)
    restored = second_repository.load_chat(chat_id)

    assert restored.chat_id == chat_id
    assert restored.archive_mode == "standard"
    assert restored.lifecycle_state == "active"
    assert [message.sequence_no for message in restored.messages] == [1, 2]
    assert [message.content for message in restored.messages] == [
        "Remember this after restart.",
        "Persisted.",
    ]
    assert restored.messages[0].message_id == first_message.message_id
    assert restored.messages[1].message_id == second_message.message_id
    assert restored.messages[0].revision_id == first_message.revision_id

    second_database.stop()


def test_message_write_creates_revision_provenance_and_commit_atomically(tmp_path) -> None:
    database = SQLiteDatabase(tmp_path / "athena.db")
    database.start()
    repository = ChatRepository(database)
    actor_id = repository.create_actor(actor_type="user")
    chat_id = repository.create_chat(actor_id=actor_id)

    message = repository.append_message(
        chat_id=chat_id,
        actor_id=actor_id,
        message_type=MessageType.USER,
        content="Atomic message",
    )

    connection = database.connection
    message_blob = message.message_id.bytes
    revision_blob = message.revision_id.bytes

    revision = connection.execute(
        "SELECT provenance_id, payload_hash, commit_id FROM revisions WHERE revision_id = ?",
        (revision_blob,),
    ).fetchone()
    assert revision is not None
    assert len(revision["payload_hash"]) == 32

    provenance = connection.execute(
        "SELECT model_signature_id, subject_revision_id FROM provenance_records "
        "WHERE provenance_id = ?",
        (revision["provenance_id"],),
    ).fetchone()
    assert provenance is not None
    assert provenance["model_signature_id"] is None
    assert provenance["subject_revision_id"] == revision_blob

    change = connection.execute(
        "SELECT cc.revision_id FROM commit_changes AS cc "
        "JOIN commit_records AS cr ON cr.commit_seq = cc.commit_seq "
        "WHERE cr.commit_id = ? AND cc.entity_id = ?",
        (revision["commit_id"], message_blob),
    ).fetchone()
    assert change is not None
    assert change["revision_id"] == revision_blob

    database.stop()


def test_failed_message_append_rolls_back_entire_canonical_write(tmp_path) -> None:
    database = SQLiteDatabase(tmp_path / "athena.db")
    database.start()
    repository = ChatRepository(database)
    actor_id = repository.create_actor(actor_type="user")
    commits_before = database.connection.execute(
        "SELECT COUNT(*) FROM commit_records"
    ).fetchone()[0]

    with pytest.raises(ChatNotFoundError):
        repository.append_message(
            chat_id=uuid.uuid4(),
            actor_id=actor_id,
            message_type=MessageType.USER,
            content="Must not partially persist",
        )

    connection = database.connection
    assert connection.execute("SELECT COUNT(*) FROM commit_records").fetchone()[0] == commits_before
    assert connection.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM revisions").fetchone()[0] == 0

    database.stop()


def test_nonstandard_archive_modes_are_not_silently_persisted(tmp_path) -> None:
    database = SQLiteDatabase(tmp_path / "athena.db")
    database.start()
    repository = ChatRepository(database)
    actor_id = repository.create_actor(actor_type="user")

    for archive_mode in ("temporary", "do_not_store"):
        with pytest.raises(UnsupportedArchiveModeError):
            repository.create_chat(actor_id=actor_id, archive_mode=archive_mode)

    assert database.connection.execute("SELECT COUNT(*) FROM chats").fetchone()[0] == 0
    database.stop()
