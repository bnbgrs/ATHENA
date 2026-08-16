import pytest

from athena.chat.repository import ChatRepository
from athena.chat.service import ChatService
from athena.common.ids import uuid_to_blob
from athena.knowledge.claim_repository import ClaimRelationError, ClaimRepository
from athena.knowledge.claim_service import ClaimService
from athena.knowledge.models import ClaimDraft, ClaimKind, EpistemicStatus, EvidenceRole
from athena.storage.database import SQLiteDatabase


def _services(tmp_path):
    database = SQLiteDatabase(tmp_path / "athena.db")
    database.start()
    chat = ChatService(ChatRepository(database))
    repository = ClaimRepository(database)
    claims = ClaimService(repository, chat)
    return database, chat, repository, claims


def test_promoted_chat_message_becomes_claim_with_exact_source_revision(tmp_path) -> None:
    database, chat, repository, claims = _services(tmp_path)
    chat_id = chat.create_chat()
    source = chat.add_user_message(chat_id=chat_id, content="The sky is blue.")

    revision = claims.promote_chat_message(
        chat_id=chat_id,
        sequence_no=1,
        claim_kind=ClaimKind.USER_STATEMENT,
    )

    snapshot = repository.load_current(revision.claim_id)
    assert snapshot.revision.payload.statement == "The sky is blue."
    assert snapshot.revision.payload.claim_kind is ClaimKind.USER_STATEMENT

    inputs = repository.list_provenance_inputs(revision.provenance_id)
    assert len(inputs) == 1
    assert inputs[0].input_entity_id == source.message_id
    assert inputs[0].input_revision_id == source.revision_id
    assert inputs[0].input_role == "chat_message_source"

    evidence = repository.list_evidence(revision.claim_id)
    assert len(evidence) == 1
    assert evidence[0].evidence_role is EvidenceRole.ORIGINATES
    assert evidence[0].message_id == source.message_id
    assert evidence[0].evidence_entity_id == source.message_id
    assert evidence[0].evidence_revision_id == source.revision_id

    entity = database.connection.execute(
        "SELECT domain, entity_type FROM entity_registry WHERE entity_id = ?",
        (uuid_to_blob(revision.claim_id),),
    ).fetchone()
    assert entity is not None
    assert tuple(entity) == ("knowledge", "claim")
    database.stop()


def test_direct_claim_revision_preserves_immutable_history(tmp_path) -> None:
    database, chat, repository, claims = _services(tmp_path)
    chat_id = chat.create_chat()
    chat.add_user_message(chat_id=chat_id, content="Version one.")
    created = claims.promote_chat_message(
        chat_id=chat_id,
        sequence_no=1,
        claim_kind=ClaimKind.FACTUAL_ASSERTION,
    )

    revised = claims.revise(
        claim_id=created.claim_id,
        statement="Version two.",
        epistemic_status=EpistemicStatus.SUPPORTED,
    )

    history = repository.list_revisions(created.claim_id)
    assert [item.revision_no for item in history] == [1, 2]
    assert history[0].payload.statement == "Version one."
    assert history[1].payload.statement == "Version two."
    assert history[1].payload.epistemic_status is EpistemicStatus.SUPPORTED
    assert revised.revision_id != created.revision_id
    assert repository.load_current(created.claim_id).revision.revision_id == revised.revision_id
    database.stop()


def test_two_contradictory_claims_coexist_with_reciprocal_links(tmp_path) -> None:
    database, chat, repository, claims = _services(tmp_path)
    first_chat = chat.create_chat()
    second_chat = chat.create_chat()
    chat.add_user_message(chat_id=first_chat, content="The switch is on.")
    chat.add_user_message(chat_id=second_chat, content="The switch is off.")
    left = claims.promote_chat_message(
        chat_id=first_chat,
        sequence_no=1,
        claim_kind=ClaimKind.FACTUAL_ASSERTION,
    )
    right = claims.promote_chat_message(
        chat_id=second_chat,
        sequence_no=1,
        claim_kind=ClaimKind.FACTUAL_ASSERTION,
    )

    left_link, right_link = claims.mark_contradiction(
        left_claim_id=left.claim_id,
        right_claim_id=right.claim_id,
    )

    assert repository.load_current(left.claim_id).revision.payload.statement == "The switch is on."
    assert repository.load_current(right.claim_id).revision.payload.statement == "The switch is off."
    assert left_link.evidence_entity_id == right.claim_id
    assert right_link.evidence_entity_id == left.claim_id

    left_evidence = repository.list_evidence(left.claim_id)
    right_evidence = repository.list_evidence(right.claim_id)
    assert any(
        item.evidence_role is EvidenceRole.CONTRADICTS
        and item.evidence_entity_id == right.claim_id
        and item.evidence_revision_id == right.revision_id
        for item in left_evidence
    )
    assert any(
        item.evidence_role is EvidenceRole.CONTRADICTS
        and item.evidence_entity_id == left.claim_id
        and item.evidence_revision_id == left.revision_id
        for item in right_evidence
    )

    contradiction_commits = database.connection.execute(
        "SELECT COUNT(*) AS count FROM commit_records WHERE operation_type = ?",
        ("claim.contradiction.link",),
    ).fetchone()
    assert contradiction_commits is not None
    assert int(contradiction_commits["count"]) == 1
    database.stop()


def test_non_overlapping_claims_are_not_marked_as_temporal_contradiction(tmp_path) -> None:
    database, chat, repository, claims = _services(tmp_path)
    actor_id = chat.ensure_local_user()
    left = repository.create_claim(
        actor_id=actor_id,
        draft=ClaimDraft(
            claim_kind=ClaimKind.FACTUAL_ASSERTION,
            statement="A works at X in the first period.",
            valid_from_us=100,
            valid_to_us=200,
        ),
    )
    right = repository.create_claim(
        actor_id=actor_id,
        draft=ClaimDraft(
            claim_kind=ClaimKind.FACTUAL_ASSERTION,
            statement="A works at Y in the later period.",
            valid_from_us=300,
            valid_to_us=400,
        ),
    )

    with pytest.raises(ClaimRelationError, match="non-overlapping"):
        claims.mark_contradiction(
            left_claim_id=left.claim_id,
            right_claim_id=right.claim_id,
        )

    assert not any(
        item.evidence_role is EvidenceRole.CONTRADICTS
        for item in repository.list_evidence(left.claim_id)
    )
    assert not any(
        item.evidence_role is EvidenceRole.CONTRADICTS
        for item in repository.list_evidence(right.claim_id)
    )
    database.stop()


def test_duplicate_contradiction_is_rejected_without_partial_write(tmp_path) -> None:
    database, chat, repository, claims = _services(tmp_path)
    actor_id = chat.ensure_local_user()
    left = repository.create_claim(
        actor_id=actor_id,
        draft=ClaimDraft(claim_kind=ClaimKind.FACTUAL_ASSERTION, statement="A"),
    )
    right = repository.create_claim(
        actor_id=actor_id,
        draft=ClaimDraft(claim_kind=ClaimKind.FACTUAL_ASSERTION, statement="Not A"),
    )
    claims.mark_contradiction(left_claim_id=left.claim_id, right_claim_id=right.claim_id)

    before = database.connection.execute(
        "SELECT COUNT(*) AS count FROM claim_evidence WHERE evidence_role = 'contradicts'"
    ).fetchone()
    assert before is not None

    with pytest.raises(ClaimRelationError, match="already linked"):
        claims.mark_contradiction(left_claim_id=left.claim_id, right_claim_id=right.claim_id)

    after = database.connection.execute(
        "SELECT COUNT(*) AS count FROM claim_evidence WHERE evidence_role = 'contradicts'"
    ).fetchone()
    assert after is not None
    assert int(after["count"]) == int(before["count"]) == 2
    database.stop()



def test_grounded_assistant_promotion_strips_trace_but_preserves_claim_origin(
    tmp_path,
) -> None:
    database, chat, repository, claims = _services(
        tmp_path
    )

    try:
        chat_id = chat.create_chat()

        chat.add_user_message(
            chat_id=chat_id,
            content="What archive code?",
        )

        assistant = chat.add_assistant_message(
            chat_id=chat_id,
            content=(
                "The archive code is 8842 "
                "[SOURCE:CTX-001].\n\n"
                'ATHENA_PROVENANCE '
                '{"athena_provenance_version":3,'
                '"evidence":[{"context_id":"CTX-001"}]}'
            ),
            provider_id="lm_studio",
            model_id="primary",
        )

        revision = claims.promote_chat_message(
            chat_id=chat_id,
            sequence_no=2,
            claim_kind=ClaimKind.FACTUAL_ASSERTION,
        )

        snapshot = repository.load_current(
            revision.claim_id
        )

        assert (
            snapshot.revision.payload.statement
            == "The archive code is 8842."
        )

        assert (
            "CTX-"
            not in snapshot.revision.payload.statement
        )

        assert (
            "ATHENA_PROVENANCE"
            not in snapshot.revision.payload.statement
        )

        inputs = repository.list_provenance_inputs(
            revision.provenance_id
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

        evidence = repository.list_evidence(
            revision.claim_id
        )

        assert len(evidence) == 1
        assert (
            evidence[0].evidence_role
            is EvidenceRole.ORIGINATES
        )
        assert (
            evidence[0].message_id
            == assistant.message_id
        )
        assert (
            evidence[0].evidence_revision_id
            == assistant.revision_id
        )

        persisted = chat.load_chat(
            chat_id
        ).messages[1]

        assert (
            "[SOURCE:CTX-001]"
            in persisted.content
        )
        assert (
            "ATHENA_PROVENANCE"
            in persisted.content
        )

    finally:
        database.stop()
