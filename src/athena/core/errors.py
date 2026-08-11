"""Core lifecycle exceptions."""

from __future__ import annotations


class AthenaCoreError(RuntimeError):
    """Base class for ATHENA Core lifecycle errors."""


class StartupError(AthenaCoreError):
    """Raised when one or more Core services cannot be started safely."""


class ShutdownError(AthenaCoreError):
    """Raised when one or more Core services cannot be stopped safely."""
