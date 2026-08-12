from __future__ import annotations

import uuid

from athena.chat.repository import ChatRepository
from athena.chat.service import ChatService
from athena.knowledge.claim_repository import ClaimRepository
from athena.knowledge.models import ClaimDraft, ClaimKind, EpistemicStatus
from athena.knowledge.review_service import ReviewService
from athena.model.domain import ModelInfo
from athena.model.provenance import ModelRunRepository
from athena.storage.database import SQLiteDatabase


def _setup_claims(tmp_path):
    database = SQLiteDatabase(tmp_path / "athena.db")
    database.start()
    chat = ChatService(ChatRepository(database))
    actor = chat.ensure_local_user()
    claims = ClaimRepository(database)

    c1 = claims.create_claim(
        actor_id=actor,
        draft=ClaimDraft(
            claim_kind=ClaimKind.FACTUAL_ASSERTION,
            statement="Berlin ist die Hauptstadt von Deutschland.",
            epistemic_status=EpistemicStatus.ASSERTED,
        ),
        reason="review test",
    )
    c2 = claims.create_claim(
        actor_id=actor,
        draft=ClaimDraft(
            claim_kind=ClaimKind.FACTUAL_ASSERTION,
            statement="München ist die Hauptstadt von Deutschland.",
            epistemic_status=EpistemicStatus.ASSERTED,
        ),
        reason="review test",
    )

    runs = ModelRunRepository(database)
    signature = runs.get_or_create_signature(
        model=ModelInfo(
            provider="fake",
            backend_model_id="fake/model",
            display_name="Fake Model",
            model_type="llm",
            context_capacity=32768,
            quantization=None,
            loaded=True,
            vision=False,
            trained_for_tool_use=False,
        ),
        generation_parameters={"temperature": 0},
        context_configuration=None,
    )
    run = runs.start_run(
        run_type="test.review",
        trigger_actor_id=actor,
        pipeline_version="test",
        input_snapshot={"test": True},
        configuration={"test": True},
        model_signature_id=signature.model_signature_id,
        prompt_template_id=None,
        prompt_template_version=None,
    )
    run = runs.finish_run(run.processing_run_id, status="succeeded")
    return database, chat, actor, c1, c2, signature, run


def test_pending_contradiction_survives_and_can_be_rejected(tmp_path) -> None:
    database, _chat, actor, c1, c2, signature, run = _setup_claims(tmp_path)
    reviews = ReviewService(database)
    try:
        with database.write_transaction() as connection:
            review_id = reviews.enqueue_contradiction(
                connection,
                processing_run_id=run.processing_run_id,
                model_signature_id=signature.model_signature_id,
                left_entity_id=c1.claim_id,
                left_revision_id=c1.revision_id,
                right_entity_id=c2.claim_id,
                right_revision_id=c2.revision_id,
                confidence=0.80,
                reason="uncertain contradiction",
                created_at_us=1,
            )
        assert [item.review_id for item in reviews.list_pending()] == [review_id]
        rejected = reviews.reject(review_id, actor_id=actor)
        assert rejected.status.value == "rejected"
        assert reviews.list_pending() == ()
    finally:
        database.stop()


def test_accepting_review_creates_reciprocal_contradiction(tmp_path) -> None:
    database, _chat, actor, c1, c2, signature, run = _setup_claims(tmp_path)
    reviews = ReviewService(database)
    try:
        with database.write_transaction() as connection:
            review_id = reviews.enqueue_contradiction(
                connection,
                processing_run_id=run.processing_run_id,
                model_signature_id=signature.model_signature_id,
                left_entity_id=c1.claim_id,
                left_revision_id=c1.revision_id,
                right_entity_id=c2.claim_id,
                right_revision_id=c2.revision_id,
                confidence=0.80,
                reason="uncertain contradiction",
                created_at_us=1,
            )
        accepted = reviews.accept(review_id, actor_id=actor)
        assert accepted.status.value == "accepted"
        rows = database.connection.execute(
            """
            SELECT claim_id, evidence_entity_id
            FROM claim_evidence
            WHERE evidence_role = 'contradicts'
            """
        ).fetchall()
        assert len(rows) == 2
        pairs = {(uuid.UUID(bytes=bytes(r["claim_id"])), uuid.UUID(bytes=bytes(r["evidence_entity_id"]))) for r in rows}
        assert (c1.claim_id, c2.claim_id) in pairs
        assert (c2.claim_id, c1.claim_id) in pairs
    finally:
        database.stop()
