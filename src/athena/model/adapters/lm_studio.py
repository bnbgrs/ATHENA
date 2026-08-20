"""LM Studio discovery and stateless streamed-chat adapter."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from threading import Lock
from time import monotonic
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from athena.model.domain import ModelChatMessage, ModelInfo, ProviderHealth, ProviderHealthStatus
from athena.model.ports import controlled_structured_contract_prefix


class ModelProviderError(RuntimeError):
    """Base error for model-provider operations."""


class ProviderUnavailableError(ModelProviderError):
    """Raised when the local backend cannot be reached."""


class ProviderProtocolError(ModelProviderError):
    """Raised when a backend response violates the expected contract."""


class ProviderContextLimitError(ModelProviderError):
    """Raised when the backend rejects a request for exceeding context capacity."""


class ProviderOutputLimitError(ModelProviderError):
    """Raised when structured generation exhausts its output-token budget."""


class ProviderRefusalError(ModelProviderError):
    """Raised when the selected model explicitly refuses a generation request."""


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
    _controlled_instance_ids: dict[tuple[str, int], str] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )
    _model_discovery_cache: list[tuple[float, tuple[ModelInfo, ...]]] = field(
        default_factory=list, init=False, repr=False, compare=False
    )
    _model_discovery_lock: Any = field(
        default_factory=Lock, init=False, repr=False, compare=False
    )

    @property
    def provider_id(self) -> str:
        return "lm_studio"

    @property
    def models_url(self) -> str:
        return f"{self.base_url}/api/v1/models"

    @property
    def chat_completions_url(self) -> str:
        return f"{self.base_url}/v1/chat/completions"

    @property
    def native_chat_url(self) -> str:
        return f"{self.base_url}/api/v1/chat"

    @property
    def controlled_structured_transport_id(self) -> str:
        return "lmstudio_native_chat_instance_reuse_v2"

    def health(self) -> ProviderHealth:
        try:
            self.discover_models()
        except ProviderUnavailableError as exc:
            return ProviderHealth(ProviderHealthStatus.UNAVAILABLE, str(exc))
        except ModelProviderError as exc:
            return ProviderHealth(ProviderHealthStatus.ERROR, str(exc))
        return ProviderHealth(ProviderHealthStatus.READY)

    def discover_models(self) -> tuple[ModelInfo, ...]:
        now = monotonic()
        with self._model_discovery_lock:
            if self._model_discovery_cache:
                cached_at, cached_models = self._model_discovery_cache[0]
                if now - cached_at <= 1.0:
                    return cached_models

            payload = self._get_json(self.models_url)
            models_value = payload.get("models")
            if not isinstance(models_value, list):
                raise ProviderProtocolError(
                    "LM Studio response is missing a 'models' array."
                )

            models: list[ModelInfo] = []
            for raw_model in models_value:
                if not isinstance(raw_model, Mapping):
                    raise ProviderProtocolError(
                        "LM Studio returned a non-object model entry."
                    )
                models.append(
                    self._parse_model(cast(Mapping[str, Any], raw_model))
                )

            normalized = tuple(models)
            self._model_discovery_cache[:] = [(monotonic(), normalized)]
            return normalized
    def stream_chat(
        self,
        *,
        model_id: str,
        messages: Sequence[ModelChatMessage],
        max_output_tokens: int | None = None,
        reasoning_mode: str | None = None,
        temperature: float | None = None,
    ) -> Iterator[str]:
        """Stream assistant text from LM Studio using SSE chat completions."""
        if not model_id:
            raise ValueError("model_id must not be empty.")
        if not messages:
            raise ValueError("At least one chat message is required.")
        if max_output_tokens is not None and max_output_tokens < 1:
            raise ValueError("max_output_tokens must be positive when provided.")
        if reasoning_mode not in {None, "off"}:
            raise ValueError("reasoning_mode must be None or 'off'.")
        if temperature is not None and not 0.0 <= temperature <= 2.0:
            raise ValueError("temperature must be between 0.0 and 2.0 when provided.")

        request_payload: dict[str, Any] = {
            "model": model_id,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in messages
            ],
            "stream": True,
        }
        if max_output_tokens is not None:
            request_payload["max_tokens"] = max_output_tokens
        if reasoning_mode == "off":
            request_payload["reasoning_effort"] = "none"
        if temperature is not None:
            request_payload["temperature"] = temperature

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
                    "LM Studio rejected chat generation for context capacity."
                ) from exc
            raise ModelProviderError(
                f"LM Studio returned HTTP {exc.code} during chat generation."
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
            # ATHENA structured generation is deterministic/non-reasoning.
            # Force this per request so LM Studio GUI/model defaults cannot
            # silently enable thinking for persistence-relevant calls.
            "reasoning_effort": "none",
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
                    "LM Studio rejected structured generation for context capacity."
                ) from exc
            raise ModelProviderError(
                f"LM Studio returned HTTP {exc.code} during structured generation."
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
        if choice.get("finish_reason") == "length":
            raise ProviderOutputLimitError(
                "LM Studio structured generation reached the configured "
                "output-token limit."
            )
        message = choice.get("message")
        if not isinstance(message, Mapping):
            raise ProviderProtocolError(
                "LM Studio structured choice is missing a message object."
            )

        refusal = message.get("refusal")
        if refusal is not None:
            if not isinstance(refusal, str):
                raise ProviderProtocolError(
                    "LM Studio structured response has an invalid refusal field."
                )
            normalized_refusal = refusal.strip()
            if normalized_refusal:
                raise ProviderRefusalError(
                    "LM Studio structured generation was refused by the model."
                )

        # LM Studio can expose reasoning separately from message.content.
        # Structured ATHENA calls pin reasoning off, so any non-empty reasoning
        # channel means the backend ignored the request contract.
        for reasoning_key in ("reasoning", "reasoning_content"):
            reasoning_value = message.get(reasoning_key)
            if isinstance(reasoning_value, str):
                has_reasoning = bool(reasoning_value.strip())
            elif isinstance(reasoning_value, (list, tuple, Mapping)):
                has_reasoning = bool(reasoning_value)
            else:
                has_reasoning = reasoning_value not in (None, 0, 0.0, False)
            if has_reasoning:
                raise ProviderProtocolError(
                    "LM Studio returned reasoning content despite ATHENA "
                    "pinning structured generation reasoning off."
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
        """Generate JSON through native chat with explicit reasoning and sampling controls.

        LM Studio's native chat endpoint does not enforce JSON Schema. ATHENA therefore
        supplies the schema as an explicit model contract, parses exactly one JSON object,
        and leaves strict stage-specific validation to the Core before any artifact commit.
        """
        if not model_id:
            raise ValueError("model_id must not be empty.")
        if len(messages) != 2 or messages[0].role != "system" or messages[1].role != "user":
            raise ValueError(
                "Controlled structured generation requires exactly one system and one user message."
            )
        normalized_schema_id = schema_id.strip()
        if not normalized_schema_id:
            raise ValueError("schema_id must not be empty.")
        if reasoning_mode not in {"off", "low", "medium", "high", "on"}:
            raise ValueError("reasoning_mode is invalid.")
        if context_length < 1:
            raise ValueError("context_length must be positive.")
        if max_output_tokens < 1:
            raise ValueError("max_output_tokens must be positive.")

        schema_text = json.dumps(
            dict(json_schema),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        system_prompt = (
            f"{messages[0].content}"
            f"{controlled_structured_contract_prefix(normalized_schema_id)}"
            f"{schema_text}"
        )
        instance_key = (model_id, context_length)
        pinned_instance_id = self._controlled_instance_ids.get(instance_key)
        request_payload = {
            "model": pinned_instance_id or model_id,
            "system_prompt": system_prompt,
            "input": messages[1].content,
            "reasoning": reasoning_mode,
            "temperature": temperature,
            "top_p": top_p,
            "top_k": top_k,
            "min_p": min_p,
            "repeat_penalty": repeat_penalty,
            "max_output_tokens": max_output_tokens,
            "stream": False,
            "store": False,
        }
        if pinned_instance_id is None:
            # Apply the pinned physical context only when acquiring the runtime instance.
            # Subsequent calls address that exact instance without asking LM Studio to JIT-load
            # another copy for the same model/configuration.
            request_payload["context_length"] = context_length
        raw_body = json.dumps(request_payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            self.native_chat_url,
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
                    "LM Studio rejected controlled structured generation for context capacity."
                ) from exc

            if pinned_instance_id is not None:
                current = self._cached_controlled_instance_is_current(
                    model_id=model_id,
                    instance_id=pinned_instance_id,
                    context_length=context_length,
                )

                if current is False:
                    if (
                        self._controlled_instance_ids.get(instance_key)
                        == pinned_instance_id
                    ):
                        self._controlled_instance_ids.pop(
                            instance_key,
                            None,
                        )

                    return self.generate_controlled_structured(
                        model_id=model_id,
                        messages=messages,
                        schema_id=schema_id,
                        json_schema=json_schema,
                        reasoning_mode=reasoning_mode,
                        context_length=context_length,
                        max_output_tokens=max_output_tokens,
                        temperature=temperature,
                        top_p=top_p,
                        top_k=top_k,
                        min_p=min_p,
                        repeat_penalty=repeat_penalty,
                    )

            raise ModelProviderError(
                f"LM Studio returned HTTP {exc.code} during controlled structured generation."
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise ProviderUnavailableError(
                f"LM Studio controlled structured generation failed at {self.base_url}."
            ) from exc

        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderProtocolError(
                "LM Studio returned invalid JSON for controlled structured generation."
            ) from exc
        if not isinstance(payload, Mapping):
            raise ProviderProtocolError(
                "LM Studio returned a non-object controlled structured response."
            )

        model_instance_id = payload.get("model_instance_id")
        if not isinstance(model_instance_id, str) or not model_instance_id.strip():
            raise ProviderProtocolError(
                "LM Studio controlled structured response is missing model_instance_id."
            )
        normalized_instance_id = model_instance_id.strip()
        if pinned_instance_id is None:
            self._controlled_instance_ids[instance_key] = normalized_instance_id
        elif normalized_instance_id != pinned_instance_id:
            raise ProviderProtocolError(
                "LM Studio switched model instances during one controlled extraction runtime."
            )

        stats = payload.get("stats")
        if not isinstance(stats, Mapping):
            raise ProviderProtocolError(
                "LM Studio controlled structured response is missing stats."
            )
        reasoning_tokens = stats.get("reasoning_output_tokens")
        if (
            isinstance(reasoning_tokens, bool)
            or not isinstance(reasoning_tokens, (int, float))
            or reasoning_tokens < 0
        ):
            raise ProviderProtocolError(
                "LM Studio controlled structured response has invalid reasoning token usage."
            )
        if reasoning_mode == "off" and reasoning_tokens != 0:
            raise ProviderProtocolError(
                "LM Studio used reasoning tokens despite ATHENA pinning reasoning_mode='off'."
            )

        output = payload.get("output")
        if not isinstance(output, list) or len(output) != 1:
            raise ProviderProtocolError(
                "LM Studio controlled structured response must contain exactly one output item."
            )
        message = output[0]
        if not isinstance(message, Mapping) or message.get("type") != "message":
            raise ProviderProtocolError(
                "LM Studio controlled structured response did not return one message item."
            )
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ProviderProtocolError(
                "LM Studio controlled structured response is missing JSON content."
            )
        try:
            structured = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ProviderProtocolError(
                "LM Studio controlled structured content is not valid JSON."
            ) from exc
        if not isinstance(structured, Mapping):
            raise ProviderProtocolError(
                "LM Studio controlled structured content must be a JSON object."
            )
        return cast(Mapping[str, Any], structured)


    def _cached_controlled_instance_is_current(
        self,
        *,
        model_id: str,
        instance_id: str,
        context_length: int,
    ) -> bool | None:
        """Best-effort reconciliation of one cached LM Studio runtime instance."""
        try:
            payload = self._get_json(
                self.models_url
            )
            models = payload.get("models")

            if not isinstance(models, list):
                return None

            for raw_model in models:
                if not isinstance(
                    raw_model,
                    Mapping,
                ):
                    return None

                key = raw_model.get("key")

                if not isinstance(key, str):
                    return None

                if key != model_id:
                    continue

                loaded_instances = raw_model.get(
                    "loaded_instances"
                )

                if not isinstance(
                    loaded_instances,
                    list,
                ):
                    return None

                for raw_instance in loaded_instances:
                    if not isinstance(
                        raw_instance,
                        Mapping,
                    ):
                        return None

                    candidate_id = raw_instance.get(
                        "id"
                    )

                    if not isinstance(
                        candidate_id,
                        str,
                    ):
                        return None

                    if candidate_id != instance_id:
                        continue

                    config = raw_instance.get(
                        "config"
                    )

                    if not isinstance(
                        config,
                        Mapping,
                    ):
                        return None

                    reported_context = (
                        self._optional_positive_int(
                            config.get(
                                "context_length"
                            )
                        )
                    )

                    if reported_context is None:
                        return None

                    return (
                        reported_context
                        == context_length
                    )

                return False

            return False

        except ModelProviderError:
            # Reconciliation is deliberately best-effort. A transient models
            # endpoint failure must not replace the original generation error.
            return None

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
        finish_reason = choice.get("finish_reason")
        if finish_reason is not None and not isinstance(finish_reason, str):
            raise ProviderProtocolError(
                "LM Studio returned an invalid chat finish_reason."
            )
        if finish_reason == "length":
            raise ProviderOutputLimitError(
                "LM Studio chat generation reached the configured output-token limit."
            )
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
        loaded_context_length = self._loaded_context_length(key, loaded_instances)

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
            loaded_context_length=loaded_context_length,
        )

    def _loaded_context_length(
        self,
        model_key: str,
        loaded_instances: list[object],
    ) -> int | None:
        lengths: list[int] = []
        for instance in loaded_instances:
            if not isinstance(instance, Mapping):
                raise ProviderProtocolError(
                    f"LM Studio model {model_key!r} has invalid loaded instance metadata."
                )
            config = instance.get("config")
            if config is None:
                continue
            if not isinstance(config, Mapping):
                raise ProviderProtocolError(
                    f"LM Studio model {model_key!r} has invalid loaded instance config."
                )
            value = config.get("context_length")
            if value is None:
                continue
            lengths.append(self._optional_positive_int(value) or 0)
        if not lengths:
            return None
        # Multiple runtime instances may have different limits. Normal chat does
        # not target a specific instance, so use the smallest reported limit as
        # the fail-closed effective capacity.
        return min(lengths)

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
