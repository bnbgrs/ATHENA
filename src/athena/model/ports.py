"""Core-facing model provider ports."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from typing import Any, Protocol

from athena.model.domain import ModelChatMessage, ModelInfo, ProviderHealth


class ModelDiscoveryProvider(Protocol):
    """Discovery/health operations used by the Core."""

    @property
    def provider_id(self) -> str:
        """Stable provider identifier."""
        ...

    def health(self) -> ProviderHealth:
        """Return normalized provider health without raising transport errors."""
        ...

    def discover_models(self) -> tuple[ModelInfo, ...]:
        """Return normalized models or raise a provider error."""
        ...


class ChatModelProvider(ModelDiscoveryProvider, Protocol):
    """Provider capable of streamed chat and schema-constrained output."""

    def stream_chat(
        self,
        *,
        model_id: str,
        messages: Sequence[ModelChatMessage],
    ) -> Iterator[str]:
        """Yield assistant text deltas for a complete local chat history."""
        ...

    def generate_structured(
        self,
        *,
        model_id: str,
        messages: Sequence[ModelChatMessage],
        schema_id: str,
        json_schema: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        """Return one JSON object constrained by the supplied schema."""
        ...
