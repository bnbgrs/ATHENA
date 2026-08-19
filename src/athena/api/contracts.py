"""Versioned transport-neutral contracts exposed to ATHENA clients."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import cast

# Python 3.12 does not expose a stdlib JsonValue alias. Keep the public
# contracts explicit and serializable without leaking domain objects.
JsonScalar = str | int | float | bool | None
JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]

API_VERSION = "v1"


@dataclass(frozen=True, slots=True)
class ApiContract:
    """Mixin for immutable client DTOs with a JSON-safe representation."""

    def to_dict(self) -> dict[str, JsonValue]:
        return cast(dict[str, JsonValue], _json_safe(asdict(self)))


def _json_safe(value: object) -> JsonValue:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        result: dict[str, JsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("API contract dictionaries require string keys.")
            result[key] = _json_safe(item)
        return result
    raise TypeError(f"Unsupported API contract value: {type(value).__name__}.")


@dataclass(frozen=True, slots=True)
class HealthResponse(ApiContract):
    api_version: str
    core_status: str
    detail: str | None


@dataclass(frozen=True, slots=True)
class CapabilitiesResponse(ApiContract):
    api_version: str
    features: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ChatSummaryResponse(ApiContract):
    chat_id: str
    started_at_us: int
    ended_at_us: int | None
    archive_mode: str
    lifecycle_state: str
    message_count: int


@dataclass(frozen=True, slots=True)
class ChatMessageResponse(ApiContract):
    message_id: str
    chat_id: str
    sequence_no: int
    message_type: str
    actor_id: str | None
    created_at_us: int
    revision_id: str
    content: str | None
    content_format: str | None


@dataclass(frozen=True, slots=True)
class ChatThreadResponse(ApiContract):
    chat_id: str
    started_at_us: int
    ended_at_us: int | None
    archive_mode: str
    lifecycle_state: str
    messages: tuple[ChatMessageResponse, ...]


@dataclass(frozen=True, slots=True)
class ProviderHealthResponse(ApiContract):
    provider: str
    status: str
    detail: str | None


@dataclass(frozen=True, slots=True)
class ModelResponse(ApiContract):
    provider: str
    backend_model_id: str
    display_name: str
    model_type: str
    context_capacity: int | None
    quantization: str | None
    loaded: bool
    vision: bool | None
    trained_for_tool_use: bool | None
    loaded_context_length: int | None
