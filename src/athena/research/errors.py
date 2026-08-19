"""Research persistence and orchestration error hierarchy."""

from __future__ import annotations

from athena.jobs.repository import JobLeaseError


class ResearchNotFoundError(LookupError):
    """Raised when durable Research state does not exist."""

class ResearchStateError(RuntimeError):
    """Raised when an invalid Research state transition is requested."""

class ResearchScopeUnsupportedError(ValueError):
    """Raised when foundation discovery cannot honestly honor a persisted scope."""

class ResearchSnapshotError(RuntimeError):
    """Raised when an explicit candidate cannot exist inside the pinned snapshot."""

class ResearchFenceError(JobLeaseError):
    """Raised when a stale Research parent tries to commit orchestration state."""


# Preserve historical import/pickle identity through
# athena.research.repository while the implementations live here.
for _error_type in (
    ResearchNotFoundError,
    ResearchStateError,
    ResearchScopeUnsupportedError,
    ResearchSnapshotError,
    ResearchFenceError,
):
    _error_type.__module__ = "athena.research.repository"

del _error_type
