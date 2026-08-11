import pytest

from athena.knowledge.models import ClaimDraft, ClaimKind


def test_claim_rejects_invalid_temporal_range() -> None:
    with pytest.raises(ValueError, match="valid_to_us"):
        ClaimDraft(
            claim_kind=ClaimKind.FACTUAL_ASSERTION,
            statement="A temporal claim.",
            valid_from_us=20,
            valid_to_us=10,
        )


def test_attributed_opinion_requires_attribution() -> None:
    with pytest.raises(ValueError, match="attributed_to_entity_id"):
        ClaimDraft(
            claim_kind=ClaimKind.ATTRIBUTED_OPINION,
            statement="Source A considers X problematic.",
        )
