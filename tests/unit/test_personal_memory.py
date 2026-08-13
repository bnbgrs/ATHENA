import hashlib

import pytest

from athena.chat.repository import ChatRepository
from athena.chat.service import ChatService
from athena.common.ids import uuid_to_blob
from athena.knowledge.models import KnowledgeKind
from athena.knowledge.repository import KnowledgeRepository
from athena.knowledge.service import KnowledgeService
from athena.memory.models import (
    MemoryKind,
    MemoryLearningMode,
    MemoryScopeKind,
    MemorySensitivity,
    PersonalMemoryDraft,
)
from athena.memory.repository import (
    PersonalMemoryConflictError,
    PersonalMemoryNotFoundError,
    PersonalMemoryProtectionError,
    PersonalMemoryRepository,
)
from athena.memory.service import PersonalMemoryService
from athena.source.blob_store import PreparedBlob
from athena.source.models import BlobStorageArea
from athena.source.repository import SourceRepository
from athena.storage.database import SQLiteDatabase


def _services(tmp_path):
    database = SQLiteDatabase(tmp_path / "athena.db")
    database.start()
    chat = ChatService(ChatRepository(database))
    repository = PersonalMemoryRepository(database)
    memory = PersonalMemoryService(repository, chat)
    return database, chat, repository, memory


def test_explicit_user_memory_has_personal_memory_domain_and_no_model_signature(tmp_path) -> None:
    database, _chat, repository, memory = _services(tmp_path)

    revision = memory.remember(
        content="Bitte antworte technisch präzise.",
        memory_kind=MemoryKind.RESPONSE_STYLE,
    )

    snapshot = repository.load_current(revision.memory_id)
    assert snapshot.lifecycle_state == "active"
    assert snapshot.revision.payload.content == "Bitte antworte technisch präzise."
    assert snapshot.revision.payload.learning_mode is MemoryLearningMode.EXPLICIT_USER
    assert snapshot.revision.payload.confidence is None
    assert snapshot.revision.payload.last_confirmed_at_us is not None

    entity = database.connection.execute(
        "SELECT domain, entity_type FROM entity_registry WHERE entity_id = ?",
        (uuid_to_blob(revision.memory_id),),
    ).fetchone()
    assert entity is not None
    assert tuple(entity) == ("personal_memory", "personal_memory_entry")

    provenance = database.connection.execute(
        """
        SELECT a.actor_type, p.model_signature_id, p.processing_run_id, p.operation
        FROM provenance_records AS p
        JOIN actors AS a ON a.actor_id = p.actor_id
        WHERE p.provenance_id = ?
        """,
        (uuid_to_blob(revision.provenance_id),),
    ).fetchone()
    assert provenance is not None
    assert tuple(provenance) == ("user", None, None, "personal_memory.create")
    database.stop()


def test_personal_memory_revision_is_immutable_and_stale_update_fails(tmp_path) -> None:
    database, chat, repository, memory = _services(tmp_path)
    created = memory.remember(
        content="Kurz antworten.",
        memory_kind=MemoryKind.DETAIL_PREFERENCE,
    )
    revised = memory.revise(
        memory_id=created.memory_id,
        content="Ausführlich antworten.",
    )

    history = repository.list_revisions(created.memory_id)
    assert [item.revision_no for item in history] == [1, 2]
    assert history[0].payload.content == "Kurz antworten."
    assert history[1].payload.content == "Ausführlich antworten."
    assert revised.memory_id == created.memory_id

    actor_id = chat.ensure_local_user()
    with pytest.raises(PersonalMemoryConflictError):
        repository.revise(
            actor_id=actor_id,
            memory_id=created.memory_id,
            expected_revision_id=created.revision_id,
            draft=PersonalMemoryDraft(
                memory_kind=MemoryKind.DETAIL_PREFERENCE,
                content="Stale write",
            ),
        )
    assert len(repository.list_revisions(created.memory_id)) == 2
    database.stop()


def test_scope_and_explicit_confidence_validation() -> None:
    with pytest.raises(ValueError):
        PersonalMemoryDraft(
            memory_kind=MemoryKind.WORKFLOW_PREFERENCE,
            content="Use workflow X",
            scope_kind=MemoryScopeKind.PROJECT,
        )

    with pytest.raises(ValueError):
        PersonalMemoryDraft(
            memory_kind=MemoryKind.RESPONSE_STYLE,
            content="Short",
            confidence=0.9,
        )


def test_protected_memory_fails_closed_until_protected_content_path_exists(tmp_path) -> None:
    database, _chat, _repository, memory = _services(tmp_path)
    with pytest.raises(PersonalMemoryProtectionError):
        memory.remember(
            content="Protected preference",
            sensitivity=MemorySensitivity.PROTECTED,
        )
    count = database.connection.execute(
        "SELECT COUNT(*) FROM personal_memory_entries"
    ).fetchone()[0]
    assert count == 0
    database.stop()


def test_disable_enable_and_delete_control_retrieval_visibility(tmp_path) -> None:
    database, _chat, repository, memory = _services(tmp_path)
    created = memory.remember(content="Use Markdown.", memory_kind=MemoryKind.RESPONSE_STYLE)

    memory.disable(created.memory_id)
    assert repository.list_current() == ()
    disabled = repository.list_current(include_inactive=True)
    assert len(disabled) == 1
    assert disabled[0].lifecycle_state == "inactive"

    memory.enable(created.memory_id)
    assert len(repository.list_current()) == 1

    memory.delete(created.memory_id)
    assert repository.list_current(include_inactive=True) == ()
    with pytest.raises(PersonalMemoryNotFoundError):
        memory.load(created.memory_id)
    deleted = repository.load_current(created.memory_id, include_deleted=True)
    assert deleted.lifecycle_state == "deleted"
    database.stop()


def test_confirm_creates_revision_and_updates_confirmation_timestamp(tmp_path) -> None:
    database, _chat, repository, memory = _services(tmp_path)
    created = memory.remember(content="Prefer German.", memory_kind=MemoryKind.LANGUAGE_PREFERENCE)
    confirmed = memory.confirm(created.memory_id)

    assert confirmed.revision_no == 2
    assert confirmed.payload.content == created.payload.content
    assert confirmed.payload.last_confirmed_at_us is not None
    assert created.payload.last_confirmed_at_us is not None
    assert confirmed.payload.last_confirmed_at_us >= created.payload.last_confirmed_at_us

    provenance = database.connection.execute(
        "SELECT operation, model_signature_id FROM provenance_records WHERE provenance_id = ?",
        (uuid_to_blob(confirmed.provenance_id),),
    ).fetchone()
    assert provenance is not None
    assert tuple(provenance) == ("personal_memory.confirm", None)
    assert len(repository.list_revisions(created.memory_id)) == 2
    database.stop()


def test_bulk_reset_does_not_modify_knowledge_or_raw_archive(tmp_path) -> None:
    database, chat, _repository, memory = _services(tmp_path)

    chat_id = chat.create_chat()
    chat.add_user_message(chat_id=chat_id, content="Persistent Knowledge")
    knowledge = KnowledgeService(KnowledgeRepository(database), chat)
    knowledge_revision = knowledge.promote_chat_message(
        chat_id=chat_id,
        sequence_no=1,
        knowledge_kind=KnowledgeKind.FACT,
    )

    actor_id = chat.ensure_local_user()
    source = SourceRepository(database).capture_file(
        actor_id=actor_id,
        original_name="source.txt",
        source_uri="file:///source.txt",
        prepared_blob=PreparedBlob(
            byte_length=3,
            media_type="text/plain",
            integrity_sha256=hashlib.sha256(b"raw").digest(),
            storage_area=BlobStorageArea.SPOOL,
            storage_locator="test/raw",
            source_modified_at_us=None,
        ),
    )

    first = memory.remember(content="Use Markdown.")
    second = memory.remember(content="Prefer German.")
    before_knowledge = database.connection.execute(
        "SELECT COUNT(*) FROM knowledge_units"
    ).fetchone()[0]
    before_sources = database.connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0]

    result = memory.reset()

    assert result.deleted_count == 2
    assert result.commit_id is not None
    assert memory.list(include_inactive=True) == ()
    assert database.connection.execute("SELECT COUNT(*) FROM knowledge_units").fetchone()[0] == before_knowledge
    assert database.connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == before_sources
    assert KnowledgeRepository(database).load_current(knowledge_revision.knowledge_id)
    assert SourceRepository(database).get(source.source.source_id)

    for memory_id in (first.memory_id, second.memory_id):
        state = database.connection.execute(
            "SELECT lifecycle_state FROM entity_registry WHERE entity_id = ?",
            (uuid_to_blob(memory_id),),
        ).fetchone()
        assert state is not None
        assert state["lifecycle_state"] == "deleted"

    database.stop()


def test_context_candidates_include_global_and_exact_scope_only(tmp_path) -> None:
    import uuid

    database, _chat, _repository, memory = _services(tmp_path)
    project_a = uuid.uuid4()
    project_b = uuid.uuid4()

    core = memory.remember(
        content="Prefer German.",
        memory_kind=MemoryKind.LANGUAGE_PREFERENCE,
    )
    exact = memory.remember(
        content="For project A, answer with implementation details.",
        memory_kind=MemoryKind.WORKFLOW_PREFERENCE,
        scope_kind=MemoryScopeKind.PROJECT,
        scope_entity_id=project_a,
    )
    other = memory.remember(
        content="For project B, stay high level.",
        memory_kind=MemoryKind.WORKFLOW_PREFERENCE,
        scope_kind=MemoryScopeKind.PROJECT,
        scope_entity_id=project_b,
    )

    candidates = memory.context_candidates(
        scope_kind=MemoryScopeKind.PROJECT,
        scope_entity_id=project_a,
    )
    ids = tuple(item.memory_id for item in candidates)
    assert ids[0] == core.memory_id
    assert exact.memory_id in ids
    assert other.memory_id not in ids

    global_only = memory.context_candidates()
    assert tuple(item.memory_id for item in global_only) == (core.memory_id,)
    database.stop()
