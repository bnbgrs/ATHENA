"""Shared conservative lexical thresholds for cross-domain retrieval."""

from __future__ import annotations


def required_term_matches(
    term_count: int,
) -> int:
    """Return a conservative informative-term match threshold.

    Probes containing at most three informative terms require complete
    agreement. This prevents generic shared terms from making a
    higher-priority domain shadow the actual named entity.

    Four- and five-term natural-language probes require three matches,
    tolerating limited morphology or auxiliary-word differences.

    Longer probes require a two-thirds majority.
    """

    if term_count < 1:
        raise ValueError(
            "Informative term count "
            "must be positive."
        )

    if term_count <= 3:
        return term_count

    if term_count <= 5:
        return 3

    return (
        2 * term_count + 2
    ) // 3
