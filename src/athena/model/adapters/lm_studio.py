"""LM Studio discovery and stateless streamed-chat adapter."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from athena.model.domain import ModelChatMessage, ModelInfo, ProviderHealth, ProviderHealthStatus


class ModelProviderError(RuntimeError):
    """Base error for model-provider operations."""


class ProviderUnavailableError(ModelProviderError):
    """Raised when the local backend cannot be reached."""


class ProviderProtocolError(ModelProviderError):
    """Raised when a backend response violates the expected contract."""


class ProviderContextLimitError(ModelProviderError):
    """Raised when the backend rejects a request for exceeding context capacity."""


@dataclass(frozen=True, slots=True)
class LMStudioProvider:
    """LM Studio adapter.

    Discovery uses LM Studio's native v1 API. Chat generation intentionally
    uses the OpenAI-compatible stateless chat-completions endpoint so ATHENA's
    own persistent chat remains the source of truth for conversation history.
    """

    base_url: str
    timeout_seconds: float = 2.0
    generation_timeout_seconds: float = 300.0

    @property
    def provider_id(self) -> str:
        return "lm_studio"

    @property
    def models_url(self) -> str:
        return f"{self.base_url}/api/v1/models"

    @property
    def chat_completions_url(self) -> str:
        return f"{self.base_url}/v1/chat/completions"

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

    def stream_chat(
        self,
        *,
        model_id: str,
        messages: Sequence[ModelChatMessage],
    ) -> Iterator[str]:
        """Stream assistant text from LM Studio using SSE chat completions."""
        if not model_id:
            raise ValueError("model_id must not be empty.")
        if not messages:
            raise ValueError("At least one chat message is required.")

        request_payload = {
            "model": model_id,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in messages
            ],
            "stream": True,
        }
        raw_body = json.dumps(request_payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            self.chat_completions_url,
            data=raw_body,
            method="POST",
            headers={
                "Accept": "text/event-stream",
                "Content-Type": "application/json",
            },
        )

        try:
            with urlopen(request, timeout=self.generation_timeout_seconds) as response:
                saw_done = False
                for raw_line in response:
                    try:
                        line = raw_line.decode("utf-8").strip()
                    except UnicodeDecodeError as exc:
                        raise ProviderProtocolError(
                            "LM Studio returned invalid UTF-8 in its chat stream."
                        ) from exc

                    if not line or line.startswith(":"):
                        continue
                    if not line.startswith("data:"):
                        continue

                    data = line[5:].strip()
                    if data == "[DONE]":
                        saw_done = True
                        break
                    if not data:
                        continue

                    chunk = self._parse_chat_chunk(data)
                    if chunk:
                        yield chunk

                if not saw_done:
                    raise ProviderProtocolError(
                        "LM Studio chat stream ended without a [DONE] marker."
                    )
        except HTTPError as exc:
            detail = self._http_error_detail(exc)
            if self._is_context_limit_error(exc.code, detail):
                raise ProviderContextLimitError(
                    f"LM Studio rejected chat generation for context capacity{detail}."
                ) from exc
            raise ModelProviderError(
                f"LM Studio returned HTTP {exc.code} during chat generation{detail}."
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise ProviderUnavailableError(
                f"LM Studio chat generation failed at {self.base_url}."
            ) from exc

    def generate_structured(
        self,
        *,
        model_id: str,
        messages: Sequence[ModelChatMessage],
        schema_id: str,
        json_schema: Mapping[str, Any],
        max_output_tokens: int | None = None,
    ) -> Mapping[str, Any]:
        """Generate one JSON object constrained by LM Studio structured output."""
        if not model_id:
            raise ValueError("model_id must not be empty.")
        if not messages:
            raise ValueError("At least one chat message is required.")
        normalized_schema_id = schema_id.strip()
        if not normalized_schema_id:
            raise ValueError("schema_id must not be empty.")
        if max_output_tokens is not None and max_output_tokens < 1:
            raise ValueError("max_output_tokens must be positive when provided.")

        request_payload = {
            "model": model_id,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in messages
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": normalized_schema_id,
                    "strict": True,
                    "schema": dict(json_schema),
                },
            },
            "temperature": 0.0,
            "stream": False,
        }
        if max_output_tokens is not None:
            request_payload["max_tokens"] = max_output_tokens
        raw_body = json.dumps(request_payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            self.chat_completions_url,
            data=raw_body,
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )

        try:
            with urlopen(request, timeout=self.generation_timeout_seconds) as response:
                raw = response.read()
        except HTTPError as exc:
            detail = self._http_error_detail(exc)
            if self._is_context_limit_error(exc.code, detail):
                raise ProviderContextLimitError(
                    f"LM Studio rejected structured generation for context capacity{detail}."
                ) from exc
            raise ModelProviderError(
                f"LM Studio returned HTTP {exc.code} during structured generation{detail}."
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise ProviderUnavailableError(
                f"LM Studio structured generation failed at {self.base_url}."
            ) from exc

        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderProtocolError(
                "LM Studio returned invalid JSON for structured generation."
            ) from exc
        if not isinstance(payload, Mapping):
            raise ProviderProtocolError(
                "LM Studio returned a non-object structured response."
            )

        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ProviderProtocolError(
                "LM Studio structured response is missing choices."
            )
        choice = choices[0]
        if not isinstance(choice, Mapping):
            raise ProviderProtocolError(
                "LM Studio returned an invalid structured choice."
            )
        message = choice.get("message")
        if not isinstance(message, Mapping):
            raise ProviderProtocolError(
                "LM Studio structured choice is missing a message object."
            )
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ProviderProtocolError(
                "LM Studio structured response is missing JSON content."
            )
        try:
            structured = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ProviderProtocolError(
                "LM Studio structured content is not valid JSON."
            ) from exc
        if not isinstance(structured, Mapping):
            raise ProviderProtocolError(
                "LM Studio structured content must be a JSON object."
            )
        return cast(Mapping[str, Any], structured)

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

    @staticmethod
    def _parse_chat_chunk(data: str) -> str:
        try:
            payload = json.loads(data)
        except json.JSONDecodeError as exc:
            raise ProviderProtocolError(
                "LM Studio returned invalid JSON in its chat stream."
            ) from exc
        if not isinstance(payload, Mapping):
            raise ProviderProtocolError("LM Studio returned a non-object chat chunk.")

        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ProviderProtocolError("LM Studio chat chunk is missing choices.")
        choice = choices[0]
        if not isinstance(choice, Mapping):
            raise ProviderProtocolError("LM Studio returned an invalid chat choice.")
        delta = choice.get("delta")
        if not isinstance(delta, Mapping):
            raise ProviderProtocolError("LM Studio chat choice is missing a delta object.")
        content = delta.get("content")
        if content is None:
            return ""
        if not isinstance(content, str):
            raise ProviderProtocolError("LM Studio returned non-text chat content.")
        return content

    @staticmethod
    def _is_context_limit_error(status_code: int, detail: str) -> bool:
        if status_code not in {400, 413, 422}:
            return False
        normalized = detail.casefold()
        markers = (
            "maximum context length",
            "context length exceeded",
            "context window",
            "context capacity",
            "too many tokens",
            "token limit",
            "exceeds the context",
        )
        return any(marker in normalized for marker in markers)

    @staticmethod
    def _http_error_detail(exc: HTTPError) -> str:
        try:
            raw = exc.read()
            payload = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return ""
        if not isinstance(payload, Mapping):
            return ""
        error = payload.get("error")
        if isinstance(error, Mapping):
            message = error.get("message")
            if isinstance(message, str) and message:
                return f": {message}"
        if isinstance(error, str) and error:
            return f": {error}"
        return ""

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
