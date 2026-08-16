from __future__ import annotations

import pytest

from athena.retrieval.lexical_relevance import (
    required_term_matches,
)


@pytest.mark.parametrize(
    (
        "term_count",
        "expected",
    ),
    (
        (1, 1),
        (2, 2),
        (3, 3),
        (4, 3),
        (5, 3),
        (6, 4),
        (7, 5),
        (8, 6),
        (9, 6),
        (12, 8),
    ),
)
def test_required_term_matches_balances_entity_precision_and_wording_drift(
    term_count: int,
    expected: int,
) -> None:
    assert (
        required_term_matches(
            term_count
        )
        == expected
    )


def test_required_term_matches_rejects_non_positive_counts() -> None:
    with pytest.raises(
        ValueError,
        match="positive",
    ):
        required_term_matches(
            0
        )
