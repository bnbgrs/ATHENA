from __future__ import annotations

import uuid
from dataclasses import replace
from types import SimpleNamespace

from athena.api.contracts import KnowledgeReviewResponse
from athena.api.executor import SerializedCoreApiSurface
from athena.api.service import CoreApiFacade
from athena.knowledge.deduplication import (
    CanonicalMergeCandidate,
    DedupAction,
    DedupDecision,
    DeduplicationPlan,
)
from athena.knowledge.extraction_models import ProposalEntityType
from athena.knowledge.review_service import ReviewStatus

RUN_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
SIGNATURE_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
REVIEW_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
EXISTING_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")
EXISTING_REVISION_ID = uuid.UUID("55555555-5555-5555-5555-555555555555")
SOURCE_ID = uuid.UUID("66666666-6666-6666-6666-666666666666")
SOURCE_REVISION_ID = uuid.UUID("77777777-7777-7777-7777-777777777777")
ACTOR_ID = uuid.UUID("88888888-8888-8888-8888-888888888888")


def _result(*, extractor_merge: bool = False):
    merge_candidates = (
        (SimpleNamespace(proposal_type=ProposalEntityType.KNOWLEDGE),)
        if extractor_merge
        else ()
    )
    return SimpleNamespace(
        processing_run=SimpleNamespace(processing_run_id=RUN_ID),
        model_signature=SimpleNamespace(model_signature_id=SIGNATURE_ID),
        proposals=SimpleNamespace(merge_candidates=merge_candidates),
    )


class _Snapshots:
    def __init__(self, result) -> None:
        self.result = result
        self.calls = 0

    def load(self, processing_run_id: uuid.UUID):
        self.calls += 1
        assert processing_run_id == RUN_ID
        return self.result


class _Planner:
    def __init__(self, plan: DeduplicationPlan) -> None:
        self.plan = plan
        self.preflight_calls = 0
        self.queue_calls = 0

    def preflight(self, result):
        del result
        self.preflight_calls += 1
        return self.plan

    def queue_merge_reviews(self, result, plan):
        del result
        assert plan == self.plan
        self.queue_calls += 1
        return (REVIEW_ID,) * len(plan.merge_candidates)


class _Reviews:
    def __init__(self) -> None:
        self.status = ReviewStatus.PENDING
        self.decision: str | None = None
        self.resolve_calls = 0

    def get(self, review_id: uuid.UUID):
        assert review_id == REVIEW_ID
        return SimpleNamespace(
            review_id=REVIEW_ID,
            review_type="merge_candidate",
            status=self.status,
        )

    def merge_details(self, review_id: uuid.UUID):
        assert review_id == REVIEW_ID
        return SimpleNamespace(
            review_id=REVIEW_ID,
            proposal_type=ProposalEntityType.KNOWLEDGE,
            proposal_index=0,
            source_entity_id=SOURCE_ID,
            source_revision_id=SOURCE_REVISION_ID,
            proposal_text="Berlin is the capital of Germany.",
            proposal_kind="fact",
            proposal_epistemic_status="asserted",
            similarity=0.97,
            decision=self.decision,
            existing_entity_id=EXISTING_ID,
            existing_revision_id=EXISTING_REVISION_ID,
        )

    def resolve_merge(
        self,
        review_id: uuid.UUID,
        *,
        actor_id: uuid.UUID,
        decision: str,
    ):
        assert review_id == REVIEW_ID
        assert actor_id == ACTOR_ID
        self.resolve_calls += 1
        self.status = ReviewStatus.ACCEPTED
        self.decision = decision
        return self.get(review_id)


class _Chat:
    def ensure_local_user(self) -> uuid.UUID:
        return ACTOR_ID


class _Health:
    pass


class _Provider:
    pass


def _facade(result, plan: DeduplicationPlan):
    facade = CoreApiFacade.__new__(CoreApiFacade)
    facade._chat = _Chat()
    facade._extraction_snapshots = _Snapshots(result)
    facade._proposal_review_planner = _Planner(plan)
    facade._knowledge_reviews = _Reviews()
    return facade


def _create_plan() -> DeduplicationPlan:
    return DeduplicationPlan(
        knowledge=(
            DedupDecision(
                proposal_type=ProposalEntityType.KNOWLEDGE,
                proposal_index=0,
                action=DedupAction.CREATE,
            ),
        ),
        claims=(),
        merge_candidates=(),
    )


def test_review_preflight_ready_exposes_stable_digest() -> None:
    facade = _facade(_result(), _create_plan())

    first = facade.prepare_knowledge_review(str(RUN_ID))
    second = facade.prepare_knowledge_review(str(RUN_ID))

    assert isinstance(first, KnowledgeReviewResponse)
    assert first.ready_to_accept is True
    assert first.blocked_reason is None
    assert first.preflight_digest is not None
    assert len(first.preflight_digest) == 64
    assert second.preflight_digest == first.preflight_digest
    assert first.knowledge_decisions[0].action == "create"


def test_extractor_merge_candidate_blocks_before_canonical_preflight() -> None:
    planner = _Planner(_create_plan())
    facade = _facade(_result(extractor_merge=True), _create_plan())
    facade._proposal_review_planner = planner

    review = facade.prepare_knowledge_review(str(RUN_ID))

    assert review.ready_to_accept is False
    assert review.blocked_reason == "extractor_merge_candidates"
    assert review.preflight_digest is None
    assert planner.preflight_calls == 0
    assert planner.queue_calls == 0


def test_canonical_near_duplicate_is_queued_and_blocks_acceptance() -> None:
    candidate = CanonicalMergeCandidate(
        proposal_type=ProposalEntityType.KNOWLEDGE,
        proposal_index=0,
        existing_entity_id=EXISTING_ID,
        existing_revision_id=EXISTING_REVISION_ID,
        similarity=0.97,
        reason="possible textual near-duplicate of canonical Knowledge",
    )
    plan = replace(_create_plan(), merge_candidates=(candidate,))
    facade = _facade(_result(), plan)

    review = facade.prepare_knowledge_review(str(RUN_ID))

    assert review.ready_to_accept is False
    assert review.blocked_reason == "canonical_merge_candidates"
    assert review.preflight_digest is None
    assert review.canonical_merge_candidates[0].review_id == str(REVIEW_ID)
    assert review.canonical_merge_candidates[0].similarity == 0.97


def test_merge_resolution_is_idempotent_for_same_explicit_decision() -> None:
    facade = _facade(_result(), _create_plan())
    reviews = facade._knowledge_reviews

    first = facade.resolve_knowledge_merge_review(
        str(REVIEW_ID),
        decision="merge",
    )
    second = facade.resolve_knowledge_merge_review(
        str(REVIEW_ID),
        decision="merge",
    )

    assert first.status == "accepted"
    assert first.decision == "merge"
    assert second == first
    assert reviews.resolve_calls == 1


def test_serialized_surface_exposes_all_review_protocol_methods() -> None:
    required = {
        "prepare_knowledge_review",
        "load_knowledge_merge_review",
        "resolve_knowledge_merge_review",
    }
    assert required.issubset(vars(SerializedCoreApiSurface))
