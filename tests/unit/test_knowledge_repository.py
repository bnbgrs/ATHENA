import pytest

from athena.chat.repository import ChatRepository
from athena.chat.service import ChatService
from athena.common.ids import uuid_to_blob
from athena.knowledge.models import EpistemicStatus, KnowledgeKind, KnowledgeUnitDraft
from athena.knowledge.repository import KnowledgeConflictError, KnowledgeRepository
from athena.knowledge.service import KnowledgeService
from athena.storage.database import SQLiteDatabase


def _services(tmp_path):
    database = SQLiteDatabase(tmp_path / "athena.db")
    database.start()
    chat = ChatService(ChatRepository(database))
    knowledge_repository = KnowledgeRepository(database)
    knowledge = KnowledgeService(knowledge_repository, chat)
    return database, chat, knowledge_repository, knowledge


def test_promoted_chat_message_has_stable_provenance_input(tmp_path) -> None:
    database, chat, repository, knowledge = _services(tmp_path)
    chat_id = chat.create_chat()
    source = chat.add_user_message(chat_id=chat_id, content="Berlin is in Germany.")

    revision = knowledge.promote_chat_message(
        chat_id=chat_id,
        sequence_no=1,
        knowledge_kind=KnowledgeKind.FACT,
        title="Berlin",
    )

    snapshot = repository.load_current(revision.knowledge_id)
    assert snapshot.revision.payload.body == "Berlin is in Germany."
    assert snapshot.revision.payload.title == "Berlin"
    assert snapshot.revision.payload.knowledge_kind is KnowledgeKind.FACT

    inputs = repository.list_provenance_inputs(revision.provenance_id)
    assert len(inputs) == 1
    assert inputs[0].input_entity_id == source.message_id
    assert inputs[0].input_revision_id == source.revision_id
    assert inputs[0].input_role == "chat_message_source"
    assert inputs[0].ordinal == 0

    provenance = database.connection.execute(
        """
        SELECT actor_id, model_signature_id, processing_run_id, reason
        FROM provenance_records
        WHERE provenance_id = ?
        """,
        (uuid_to_blob(revision.provenance_id),),
    ).fetchone()
    assert provenance is not None
    assert provenance["model_signature_id"] is None
    assert provenance["processing_run_id"] is None
    assert provenance["reason"] == "explicit user promotion from chat"

    entity = database.connection.execute(
        "SELECT domain, entity_type FROM entity_registry WHERE entity_id = ?",
        (uuid_to_blob(revision.knowledge_id),),
    ).fetchone()
    assert entity is not None
    assert tuple(entity) == ("knowledge", "knowledge_unit")
    database.stop()


def test_direct_revision_preserves_immutable_history_and_moves_head(tmp_path) -> None:
    database, chat, repository, knowledge = _services(tmp_path)
    chat_id = chat.create_chat()
    chat.add_user_message(chat_id=chat_id, content="Original body")
    created = knowledge.promote_chat_message(
        chat_id=chat_id,
        sequence_no=1,
        knowledge_kind=KnowledgeKind.IDEA,
        title="Original title",
    )

    revised = knowledge.revise(
        knowledge_id=created.knowledge_id,
        body="Corrected body",
        epistemic_status=EpistemicStatus.SUPPORTED,
    )

    assert revised.revision_no == 2
    history = repository.list_revisions(created.knowledge_id)
    assert [item.revision_no for item in history] == [1, 2]
    assert history[0].payload.body == "Original body"
    assert history[0].payload.title == "Original title"
    assert history[1].payload.body == "Corrected body"
    assert history[1].payload.title == "Original title"
    assert history[1].payload.epistemic_status is EpistemicStatus.SUPPORTED

    current = repository.load_current(created.knowledge_id)
    assert current.revision.revision_id == revised.revision_id
    assert repository.list_provenance_inputs(revised.provenance_id) == ()

    parent = database.connection.execute(
        "SELECT parent_revision_id FROM revisions WHERE revision_id = ?",
        (uuid_to_blob(revised.revision_id),),
    ).fetchone()
    assert parent is not None
    assert bytes(parent["parent_revision_id"]) == uuid_to_blob(created.revision_id)
    database.stop()


def test_stale_expected_revision_is_rejected_without_partial_write(tmp_path) -> None:
    database, chat, repository, knowledge = _services(tmp_path)
    actor_id = chat.ensure_local_user()
    chat_id = chat.create_chat()
    source = chat.add_user_message(chat_id=chat_id, content="v1")
    created = repository.create_knowledge_unit(
        actor_id=actor_id,
        draft=KnowledgeUnitDraft(knowledge_kind=KnowledgeKind.FACT, body="v1"),
        source_entity_id=source.message_id,
        source_revision_id=source.revision_id,
    )
    repository.revise_knowledge_unit(
        actor_id=actor_id,
        knowledge_id=created.knowledge_id,
        expected_revision_id=created.revision_id,
        draft=KnowledgeUnitDraft(knowledge_kind=KnowledgeKind.FACT, body="v2"),
    )

    with pytest.raises(KnowledgeConflictError):
        repository.revise_knowledge_unit(
            actor_id=actor_id,
            knowledge_id=created.knowledge_id,
            expected_revision_id=created.revision_id,
            draft=KnowledgeUnitDraft(knowledge_kind=KnowledgeKind.FACT, body="stale"),
        )

    history = repository.list_revisions(created.knowledge_id)
    assert len(history) == 2
    assert repository.load_current(created.knowledge_id).revision.payload.body == "v2"
    database.stop()


def test_knowledge_survives_database_restart(tmp_path) -> None:
    path = tmp_path / "athena.db"
    database = SQLiteDatabase(path)
    database.start()
    chat = ChatService(ChatRepository(database))
    repository = KnowledgeRepository(database)
    knowledge = KnowledgeService(repository, chat)
    chat_id = chat.create_chat()
    chat.add_user_message(chat_id=chat_id, content="Persistent knowledge")
    created = knowledge.promote_chat_message(
        chat_id=chat_id,
        sequence_no=1,
        knowledge_kind=KnowledgeKind.FACT,
    )
    database.stop()

    reopened = SQLiteDatabase(path)
    reopened.start()
    loaded = KnowledgeRepository(reopened).load_current(created.knowledge_id)
    assert loaded.revision.payload.body == "Persistent knowledge"
    assert loaded.revision.revision_no == 1
    reopened.stop()
