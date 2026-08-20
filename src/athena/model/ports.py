"""Core-facing model provider ports."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from typing import Any, Protocol

from athena.model.domain import ModelChatMessage, ModelInfo, ProviderHealth

CONTROLLED_STRUCTURED_CONTRACT_VERSION = "athena.controlled_structured_json/1"


def controlled_structured_contract_prefix(schema_id: str) -> str:
    """Return the exact fixed prompt wrapper used before a supplied JSON Schema."""
    return (
        f"\n\nATHENA_STRUCTURED_CONTRACT_VERSION: {CONTROLLED_STRUCTURED_CONTRACT_VERSION}\n"
        f"ATHENA_SCHEMA_ID: {schema_id}\n"
        "Return exactly one JSON object and nothing else. Do not use Markdown fences. "
        "The object must conform exactly to the JSON Schema below; do not add keys that "
        "the schema does not allow.\n"
        "ATHENA_JSON_SCHEMA: "
    )


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
        max_output_tokens: int | None = None,
        reasoning_mode: str | None = None,
        temperature: float | None = None,
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
        max_output_tokens: int | None = None,
    ) -> Mapping[str, Any]:
        """Return one JSON object constrained by the supplied schema and output cap."""
        ...


class ControlledStructuredModelProvider(ChatModelProvider, Protocol):
    """Provider with explicit per-request controls for fail-closed JSON generation."""

    @property
    def controlled_structured_transport_id(self) -> str:
        """Stable identity of the transport that honors the explicit controls."""
        ...

    def generate_controlled_structured(
        self,
        *,
        model_id: str,
        messages: Sequence[ModelChatMessage],
        schema_id: str,
        json_schema: Mapping[str, Any],
        reasoning_mode: str,
        context_length: int,
        max_output_tokens: int,
        temperature: float,
        top_p: float,
        top_k: int,
        min_p: float,
        repeat_penalty: float,
    ) -> Mapping[str, Any]:
        """Return one JSON object under explicit provider-side inference controls."""
        ...
