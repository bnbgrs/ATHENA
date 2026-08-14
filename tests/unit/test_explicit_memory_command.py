import uuid

import pytest

from athena.chat.repository import ChatRepository
from athena.chat.service import ChatService
from athena.common.ids import uuid_to_blob
from athena.memory.explicit_command import (
    ExplicitMemoryCommandError,
    parse_explicit_personal_memory_command,
)
from athena.memory.models import MemoryKind, MemoryScopeKind
from athena.memory.repository import PersonalMemoryRepository
from athena.memory.service import PersonalMemoryService
from athena.storage.database import SQLiteDatabase


def _services(tmp_path):
    database = SQLiteDatabase(tmp_path / "athena.db")
    database.start()
    chat = ChatService(ChatRepository(database))
    memory = PersonalMemoryService(PersonalMemoryRepository(database), chat)
    chat_id = chat.create_chat()
    return database, chat, memory, chat_id


def test_parser_recognizes_explicit_detail_preference() -> None:
    intent = parse_explicit_personal_memory_command(
        "Merke dir, dass ich kurze Antworten bevorzuge."
    )

    assert intent is not None
    assert intent.memory_content == "ich kurze Antworten bevorzuge."
    assert intent.memory_kind is MemoryKind.DETAIL_PREFERENCE
    assert intent.scope_kind is MemoryScopeKind.GLOBAL
    assert intent.scope_entity_id is None


def test_parser_recognizes_from_now_response_style() -> None:
    intent = parse_explicit_personal_memory_command(
        "Ab jetzt bitte immer Markdown verwenden."
    )

    assert intent is not None
    assert intent.memory_content == "bitte immer Markdown verwenden."
    assert intent.memory_kind is MemoryKind.RESPONSE_STYLE


def test_parser_does_not_route_fact_save_request_to_personal_memory() -> None:
    intent = parse_explicit_personal_memory_command(
        "Merke dir, dass Berlin die Hauptstadt von Deutschland ist."
    )

    assert intent is None


def test_parser_rejects_value_only_personal_preferences() -> None:
    for content in (
        "Merke dir, dass ich kurze Haare bevorzuge.",
        "Merke dir, dass ich deutsches Bier bevorzuge.",
        "Merke dir, dass ich englische Krimis bevorzuge.",
        "Merke dir, dass ich detaillierte Landkarten bevorzuge.",
        "Merke dir, dass ich Gitarren bevorzuge.",
    ):
        assert parse_explicit_personal_memory_command(content) is None


def test_parser_keeps_language_value_after_collaboration_is_established() -> None:
    intent = parse_explicit_personal_memory_command(
        "Merke dir, dass du auf Deutsch antworten sollst."
    )

    assert intent is not None
    assert intent.memory_kind is MemoryKind.LANGUAGE_PREFERENCE


def test_fact_save_request_is_still_detected_as_explicit_persistence() -> None:
    from athena.memory.explicit_command import is_explicit_persistence_command

    assert is_explicit_persistence_command(
        "Speichere, dass Berlin die Hauptstadt von Deutschland ist."
    )


def test_project_command_requires_exact_project_scope() -> None:
    content = "Für dieses Projekt möchte ich technische Antworten ausführlich."
    with pytest.raises(ExplicitMemoryCommandError, match="Project-scoped"):
        parse_explicit_personal_memory_command(content)

    project_id = uuid.uuid4()
    intent = parse_explicit_personal_memory_command(
        content,
        scope_kind=MemoryScopeKind.PROJECT,
        scope_entity_id=project_id,
    )

    assert intent is not None
    assert intent.scope_kind is MemoryScopeKind.PROJECT
    assert intent.scope_entity_id == project_id
    assert intent.memory_kind is MemoryKind.DETAIL_PREFERENCE


def test_explicit_chat_command_persists_user_message_and_user_memory_only(tmp_path) -> None:
    database, chat, memory, chat_id = _services(tmp_path)
    command = "Merke dir, dass ich kurze Antworten bevorzuge."

    before_knowledge = database.connection.execute(
        "SELECT COUNT(*) FROM knowledge_units"
    ).fetchone()[0]
    before_claims = database.connection.execute(
        "SELECT COUNT(*) FROM claims"
    ).fetchone()[0]

    result = memory.remember_explicit_chat_command(
        chat_id=chat_id,
        content=command,
    )

    assert result is not None
    assert result.user_message.content == command
    assert result.memory_revision.payload.content == "ich kurze Antworten bevorzuge."
    assert result.memory_revision.payload.memory_kind is MemoryKind.DETAIL_PREFERENCE
    assert chat.load_chat(chat_id).messages[-1].content == command

    after_knowledge = database.connection.execute(
        "SELECT COUNT(*) FROM knowledge_units"
    ).fetchone()[0]
    after_claims = database.connection.execute(
        "SELECT COUNT(*) FROM claims"
    ).fetchone()[0]
    assert after_knowledge == before_knowledge
    assert after_claims == before_claims

    provenance = database.connection.execute(
        """
        SELECT a.actor_type, p.model_signature_id, p.processing_run_id
        FROM provenance_records AS p
        JOIN actors AS a ON a.actor_id = p.actor_id
        WHERE p.provenance_id = ?
        """,
        (uuid_to_blob(result.memory_revision.provenance_id),),
    ).fetchone()
    assert provenance is not None
    assert tuple(provenance) == ("user", None, None)
    database.stop()


def test_non_memory_save_request_creates_no_memory_or_chat_write(tmp_path) -> None:
    database, chat, memory, chat_id = _services(tmp_path)

    result = memory.remember_explicit_chat_command(
        chat_id=chat_id,
        content="Speichere, dass Berlin die Hauptstadt von Deutschland ist.",
    )

    assert result is None
    assert chat.load_chat(chat_id).messages == ()
    count = database.connection.execute(
        "SELECT COUNT(*) FROM personal_memory_entries"
    ).fetchone()[0]
    assert count == 0
    database.stop()


def test_explicit_scoped_command_reuses_existing_direct_user_memory_path(tmp_path) -> None:
    database, _chat, memory, chat_id = _services(tmp_path)
    project_id = uuid.uuid4()

    result = memory.remember_explicit_chat_command(
        chat_id=chat_id,
        content="Für dieses Projekt möchte ich technische Antworten ausführlich.",
        scope_kind=MemoryScopeKind.PROJECT,
        scope_entity_id=project_id,
    )

    assert result is not None
    payload = result.memory_revision.payload
    assert payload.scope_kind is MemoryScopeKind.PROJECT
    assert payload.scope_entity_id == project_id
    assert payload.memory_kind is MemoryKind.DETAIL_PREFERENCE
    database.stop()
