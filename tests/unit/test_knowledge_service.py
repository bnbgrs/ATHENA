import pytest

from athena.chat.repository import ChatRepository
from athena.chat.service import ChatService
from athena.knowledge.models import KnowledgeKind
from athena.knowledge.repository import KnowledgeRepository
from athena.knowledge.service import ChatMessageSequenceError, KnowledgeService
from athena.storage.database import SQLiteDatabase


def test_promotion_uses_exact_message_text_without_model_rewrite(tmp_path) -> None:
    database = SQLiteDatabase(tmp_path / "athena.db")
    database.start()
    chat = ChatService(ChatRepository(database))
    knowledge = KnowledgeService(KnowledgeRepository(database), chat)
    chat_id = chat.create_chat()
    exact = (
        "  User literal [CTX-777] and ATHENA_PROVENANCE text are "
        "normalized only by the Knowledge draft boundary.  "
    )
    chat.add_user_message(chat_id=chat_id, content=exact)

    created = knowledge.promote_chat_message(
        chat_id=chat_id,
        sequence_no=1,
        knowledge_kind=KnowledgeKind.OTHER,
    )

    assert created.payload.body == exact.strip()
    database.stop()


def test_missing_chat_sequence_is_rejected_before_knowledge_write(tmp_path) -> None:
    database = SQLiteDatabase(tmp_path / "athena.db")
    database.start()
    chat = ChatService(ChatRepository(database))
    repository = KnowledgeRepository(database)
    knowledge = KnowledgeService(repository, chat)
    chat_id = chat.create_chat()

    with pytest.raises(ChatMessageSequenceError):
        knowledge.promote_chat_message(
            chat_id=chat_id,
            sequence_no=2,
            knowledge_kind=KnowledgeKind.FACT,
        )

    count = database.connection.execute("SELECT COUNT(*) FROM knowledge_units").fetchone()[0]
    assert count == 0
    database.stop()



def test_grounded_assistant_promotion_strips_ephemeral_trace_but_keeps_source_revision(
    tmp_path,
) -> None:
    database = SQLiteDatabase(tmp_path / "athena.db")
    database.start()

    try:
        chat = ChatService(
            ChatRepository(database)
        )
        repository = KnowledgeRepository(
            database
        )
        knowledge = KnowledgeService(
            repository,
            chat,
        )

        chat_id = chat.create_chat()

        chat.add_user_message(
            chat_id=chat_id,
            content="Which code?",
        )

        assistant = chat.add_assistant_message(
            chat_id=chat_id,
            content=(
                "The code is 7319 [CTX-001].\n\n"
                'ATHENA_PROVENANCE '
                '{"athena_provenance_version":3,'
                '"evidence":[{"context_id":"CTX-001"}]}'
            ),
            provider_id="lm_studio",
            model_id="primary",
        )

        created = knowledge.promote_chat_message(
            chat_id=chat_id,
            sequence_no=2,
            knowledge_kind=KnowledgeKind.FACT,
        )

        assert (
            created.payload.body
            == "The code is 7319."
        )

        assert "CTX-" not in created.payload.body
        assert (
            "ATHENA_PROVENANCE"
            not in created.payload.body
        )

        inputs = repository.list_provenance_inputs(
            created.provenance_id
        )

        assert len(inputs) == 1
        assert (
            inputs[0].input_entity_id
            == assistant.message_id
        )
        assert (
            inputs[0].input_revision_id
            == assistant.revision_id
        )
        assert (
            inputs[0].input_role
            == "chat_message_source"
        )

        persisted = chat.load_chat(
            chat_id
        ).messages[1]

        assert "[CTX-001]" in persisted.content
        assert (
            "ATHENA_PROVENANCE"
            in persisted.content
        )

    finally:
        database.stop()
