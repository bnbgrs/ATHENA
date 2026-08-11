"""LM Studio model discovery adapter."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from athena.model.domain import ModelInfo, ProviderHealth, ProviderHealthStatus


class ModelProviderError(RuntimeError):
    """Base error for model-provider operations."""


class ProviderUnavailableError(ModelProviderError):
    """Raised when the local backend cannot be reached."""


class ProviderProtocolError(ModelProviderError):
    """Raised when a backend response violates the expected contract."""


@dataclass(frozen=True, slots=True)
class LMStudioProvider:
    """LM Studio adapter using its native v1 API for model discovery."""

    base_url: str
    timeout_seconds: float = 2.0

    @property
    def provider_id(self) -> str:
        return "lm_studio"

    @property
    def models_url(self) -> str:
        return f"{self.base_url}/api/v1/models"

    def health(self) -> ProviderHealth:
        try:
            self.discover_models()
        except ProviderUnavailableError as exc:
            return ProviderHealth(ProviderHealthStatus.UNAVAILABLE, str(exc))
        except ModelProviderError as exc:
            return ProviderHealth(ProviderHealthStatus.ERROR, str(exc))
        return ProviderHealth(ProviderHealthStatus.READY)

    def discover_models(self) -> tuple[ModelInfo, ...]:
        payload = self._get_json(self.models_url)
        models_value = payload.get("models")
        if not isinstance(models_value, list):
            raise ProviderProtocolError("LM Studio response is missing a 'models' array.")

        models: list[ModelInfo] = []
        for raw_model in models_value:
            if not isinstance(raw_model, Mapping):
                raise ProviderProtocolError("LM Studio returned a non-object model entry.")
            models.append(self._parse_model(cast(Mapping[str, Any], raw_model)))
        return tuple(models)

    def _get_json(self, url: str) -> Mapping[str, Any]:
        request = Request(url, headers={"Accept": "application/json"})
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read()
        except HTTPError as exc:
            raise ModelProviderError(
                f"LM Studio returned HTTP {exc.code} for {url}."
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise ProviderUnavailableError(
                f"LM Studio is not reachable at {self.base_url}."
            ) from exc

        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderProtocolError("LM Studio returned invalid JSON.") from exc

        if not isinstance(payload, Mapping):
            raise ProviderProtocolError("LM Studio returned a non-object JSON response.")
        return cast(Mapping[str, Any], payload)

    def _parse_model(self, raw: Mapping[str, Any]) -> ModelInfo:
        key = self._required_string(raw, "key")
        display_name = self._required_string(raw, "display_name")
        model_type = self._required_string(raw, "type")

        context_capacity = self._optional_positive_int(raw.get("max_context_length"))
        quantization = self._parse_quantization(raw.get("quantization"))
        loaded_instances = raw.get("loaded_instances")
        if not isinstance(loaded_instances, list):
            raise ProviderProtocolError(
                f"LM Studio model {key!r} has invalid 'loaded_instances'."
            )

        vision: bool | None = None
        trained_for_tool_use: bool | None = None
        capabilities = raw.get("capabilities")
        if capabilities is not None:
            if not isinstance(capabilities, Mapping):
                raise ProviderProtocolError(
                    f"LM Studio model {key!r} has invalid 'capabilities'."
                )
            vision = self._optional_bool(capabilities.get("vision"))
            trained_for_tool_use = self._optional_bool(
                capabilities.get("trained_for_tool_use")
            )

        return ModelInfo(
            provider=self.provider_id,
            backend_model_id=key,
            display_name=display_name,
            model_type=model_type,
            context_capacity=context_capacity,
            quantization=quantization,
            loaded=bool(loaded_instances),
            vision=vision,
            trained_for_tool_use=trained_for_tool_use,
        )

    @staticmethod
    def _required_string(raw: Mapping[str, Any], field: str) -> str:
        value = raw.get(field)
        if not isinstance(value, str) or not value:
            raise ProviderProtocolError(
                f"LM Studio model entry has invalid {field!r}."
            )
        return value

    @staticmethod
    def _optional_positive_int(value: object) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ProviderProtocolError("LM Studio returned an invalid context capacity.")
        return value

    @staticmethod
    def _optional_bool(value: object) -> bool | None:
        if value is None:
            return None
        if not isinstance(value, bool):
            raise ProviderProtocolError("LM Studio returned an invalid boolean capability.")
        return value

    @staticmethod
    def _parse_quantization(value: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, Mapping):
            raise ProviderProtocolError("LM Studio returned invalid quantization metadata.")
        name = value.get("name")
        if name is None:
            return None
        if not isinstance(name, str) or not name:
            raise ProviderProtocolError("LM Studio returned an invalid quantization name.")
        return name
