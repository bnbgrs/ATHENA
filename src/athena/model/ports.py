"""Core-facing model provider ports."""

from __future__ import annotations

from typing import Protocol

from athena.model.domain import ModelInfo, ProviderHealth


class ModelDiscoveryProvider(Protocol):
    """Minimal discovery/health port used while Vertical Slice 1 is built."""

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
