"""Rank-based fusion primitives for heterogeneous retrieval methods."""

from __future__ import annotations

DEFAULT_RRF_K = 60


def reciprocal_rank_contribution(rank: int, *, k: int = DEFAULT_RRF_K) -> float:
    """Return one Reciprocal Rank Fusion contribution for a 1-based rank."""
    if rank <= 0:
        raise ValueError("RRF rank must be positive and 1-based.")
    if k <= 0:
        raise ValueError("RRF k must be positive.")
    return 1.0 / (k + rank)
