"""Stable model-provider domain types."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ProviderHealthStatus(str, Enum):
    """Normalized provider health states used by the Core."""

    UNAVAILABLE = "unavailable"
    READY = "ready"
    DEGRADED = "degraded"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class ProviderHealth:
    """Health snapshot without backend-specific exception leakage."""

    status: ProviderHealthStatus
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class ModelInfo:
    """Backend model metadata normalized for ATHENA."""

    provider: str
    backend_model_id: str
    display_name: str
    model_type: str
    context_capacity: int | None
    quantization: str | None
    loaded: bool
    vision: bool | None
    trained_for_tool_use: bool | None
    loaded_context_length: int | None = None


@dataclass(frozen=True, slots=True)
class ModelChatMessage:
    """One stateless chat-history item passed to a model provider."""

    role: str
    content: str
