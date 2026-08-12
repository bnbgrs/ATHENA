from __future__ import annotations


def test_model_confidence_one_does_not_bypass_review_queue(tmp_path) -> None:
    from tests.unit.test_proposal_acceptance import _extracted

    database, result, _knowledge, _claims, acceptance = _extracted(tmp_path)
    try:
        relation = result.proposals.relations[0]
        assert relation.confidence == 1.0
        accepted = acceptance.accept_all(result)
        assert accepted.contradiction_pairs == ()
        assert len(accepted.contradiction_review_ids) == 1
        pending = acceptance.reviews.list_pending(review_type="contradiction")
        assert len(pending) == 1
        assert pending[0].confidence == 1.0
    finally:
        database.stop()
