from __future__ import annotations

from dataclasses import replace

from athena.knowledge.deduplication import CanonicalMergeCandidate
from athena.knowledge.extraction_models import ProposalEntityType


def _near_duplicate_plan(result, canonical_id, canonical_revision_id):
    candidate = CanonicalMergeCandidate(
        proposal_type=ProposalEntityType.KNOWLEDGE,
        proposal_index=0,
        existing_entity_id=canonical_id,
        existing_revision_id=canonical_revision_id,
        similarity=0.95,
        reason="test near duplicate",
    )
    return candidate


def test_merge_review_decision_is_persistent_and_reusable(tmp_path) -> None:
    from tests.unit.test_proposal_acceptance import _extracted

    database, result, knowledge, _claims, acceptance = _extracted(tmp_path)
    try:
        first = acceptance.accept_all(replace(result, proposals=replace(result.proposals, relations=())))
        canonical_id = first.knowledge_ids[0]
        canonical = knowledge.load_current(canonical_id)

        # Rebind first proposal to a fresh source-backed run shape while manually
        # supplying a deterministic near-duplicate candidate for review service testing.
        candidate = CanonicalMergeCandidate(
            proposal_type=ProposalEntityType.KNOWLEDGE,
            proposal_index=0,
            existing_entity_id=canonical_id,
            existing_revision_id=canonical.revision.revision_id,
            similarity=0.95,
            reason="test near duplicate",
        )
        thread = acceptance.chat.load_chat(result.chat_id)
        sources = {message.sequence_no: message for message in thread.messages}
        review_ids = acceptance.reviews.enqueue_merge_candidates(
            result=result,
            candidates=(candidate,),
            source_by_sequence=sources,
        )
        assert len(review_ids) == 1
        review_id = review_ids[0]
        details = acceptance.reviews.merge_details(review_id)
        assert details.decision is None
        assert details.existing_entity_id == canonical_id

        actor_id = acceptance.chat.ensure_local_user()
        acceptance.reviews.resolve_merge(
            review_id,
            actor_id=actor_id,
            decision="merge",
        )
        details = acceptance.reviews.merge_details(review_id)
        assert details.decision == "merge"

        source = sources[result.proposals.knowledge_units[0].source_sequence_no]
        assert (
            acceptance.reviews.lookup_merge_decision(
                candidate=candidate,
                result=result,
                source_entity_id=source.message_id,
                source_revision_id=source.revision_id,
            )
            == "merge"
        )
    finally:
        database.stop()


def test_keep_separate_decision_is_persistent(tmp_path) -> None:
    from tests.unit.test_proposal_acceptance import _extracted

    database, result, knowledge, _claims, acceptance = _extracted(tmp_path)
    try:
        first = acceptance.accept_all(replace(result, proposals=replace(result.proposals, relations=())))
        canonical_id = first.knowledge_ids[0]
        canonical = knowledge.load_current(canonical_id)
        candidate = CanonicalMergeCandidate(
            proposal_type=ProposalEntityType.KNOWLEDGE,
            proposal_index=0,
            existing_entity_id=canonical_id,
            existing_revision_id=canonical.revision.revision_id,
            similarity=0.95,
            reason="test near duplicate",
        )
        thread = acceptance.chat.load_chat(result.chat_id)
        sources = {message.sequence_no: message for message in thread.messages}
        review_id = acceptance.reviews.enqueue_merge_candidates(
            result=result,
            candidates=(candidate,),
            source_by_sequence=sources,
        )[0]
        actor_id = acceptance.chat.ensure_local_user()
        acceptance.reviews.resolve_merge(
            review_id,
            actor_id=actor_id,
            decision="keep_separate",
        )
        source = sources[result.proposals.knowledge_units[0].source_sequence_no]
        assert (
            acceptance.reviews.lookup_merge_decision(
                candidate=candidate,
                result=result,
                source_entity_id=source.message_id,
                source_revision_id=source.revision_id,
            )
            == "keep_separate"
        )
    finally:
        database.stop()


def test_one_proposal_can_queue_multiple_distinct_merge_targets(tmp_path) -> None:
    from tests.unit.test_proposal_acceptance import _extracted

    database, result, knowledge, _claims, acceptance = _extracted(tmp_path)
    try:
        first = acceptance.accept_all(
            replace(result, proposals=replace(result.proposals, relations=()))
        )
        first_id = first.knowledge_ids[0]
        second_id = first.knowledge_ids[1]
        first_current = knowledge.load_current(first_id)
        second_current = knowledge.load_current(second_id)

        candidates = (
            CanonicalMergeCandidate(
                proposal_type=ProposalEntityType.KNOWLEDGE,
                proposal_index=0,
                existing_entity_id=first_id,
                existing_revision_id=first_current.revision.revision_id,
                similarity=0.961,
                reason="near duplicate target one",
            ),
            CanonicalMergeCandidate(
                proposal_type=ProposalEntityType.KNOWLEDGE,
                proposal_index=0,
                existing_entity_id=second_id,
                existing_revision_id=second_current.revision.revision_id,
                similarity=0.946,
                reason="near duplicate target two",
            ),
        )
        thread = acceptance.chat.load_chat(result.chat_id)
        sources = {message.sequence_no: message for message in thread.messages}

        review_ids = acceptance.reviews.enqueue_merge_candidates(
            result=result,
            candidates=candidates,
            source_by_sequence=sources,
        )

        assert len(review_ids) == 2
        assert review_ids[0] != review_ids[1]
        details = tuple(acceptance.reviews.merge_details(review_id) for review_id in review_ids)
        assert {item.existing_entity_id for item in details} == {first_id, second_id}
    finally:
        database.stop()
