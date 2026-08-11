"""Core-facing model provider ports."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Protocol

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
    """Provider capable of stateless streamed text chat."""

    def stream_chat(
        self,
        *,
        model_id: str,
        messages: Sequence[ModelChatMessage],
    ) -> Iterator[str]:
        """Yield assistant text deltas for a complete local chat history."""
        ...
