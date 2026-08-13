import json
from unittest.mock import patch
from urllib.error import URLError

import pytest

from athena.model.adapters.lm_studio import (
    LMStudioProvider,
    ProviderProtocolError,
)
from athena.model.domain import ModelChatMessage, ProviderHealthStatus


class FakeResponse:
    def __init__(self, payload: object) -> None:
        self._bytes = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return self._bytes


class FakeStreamResponse:
    def __init__(self, lines: tuple[bytes, ...]) -> None:
        self.lines = lines

    def __enter__(self) -> "FakeStreamResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def __iter__(self):
        return iter(self.lines)


def test_lm_studio_stream_chat_enforces_max_output_tokens() -> None:
    provider = LMStudioProvider("http://127.0.0.1:1234")
    captured: dict[str, object] = {}

    def fake_urlopen(request, timeout):
        captured["timeout"] = timeout
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return FakeStreamResponse(
            (
                b'data: {"choices":[{"delta":{"content":"ok"}}]}\n',
                b'data: [DONE]\n',
            )
        )

    with patch("athena.model.adapters.lm_studio.urlopen", side_effect=fake_urlopen):
        chunks = tuple(
            provider.stream_chat(
                model_id="example/model-q4",
                messages=(ModelChatMessage(role="user", content="test"),),
                max_output_tokens=1000,
                reasoning_mode="off",
            )
        )

    assert chunks == ("ok",)
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["max_tokens"] == 1000
    assert payload["reasoning_effort"] == "none"
    assert payload["stream"] is True


def test_lm_studio_stream_chat_rejects_non_positive_output_cap() -> None:
    provider = LMStudioProvider("http://127.0.0.1:1234")

    with pytest.raises(ValueError, match="max_output_tokens"):
        tuple(
            provider.stream_chat(
                model_id="example/model-q4",
                messages=(ModelChatMessage(role="user", content="test"),),
                max_output_tokens=0,
            )
        )


def test_lm_studio_stream_chat_rejects_unsupported_reasoning_mode() -> None:
    provider = LMStudioProvider("http://127.0.0.1:1234")

    with pytest.raises(ValueError, match="reasoning_mode"):
        tuple(
            provider.stream_chat(
                model_id="example/model-q4",
                messages=(ModelChatMessage(role="user", content="test"),),
                reasoning_mode="on",
            )
        )


def test_lm_studio_discovers_and_normalizes_models() -> None:
    provider = LMStudioProvider("http://127.0.0.1:1234")
    payload = {
        "models": [
            {
                "type": "llm",
                "publisher": "example",
                "key": "example/model-q4",
                "display_name": "Example Model",
                "architecture": "example",
                "quantization": {"name": "Q4_K_M", "bits_per_weight": 4.5},
                "size_bytes": 123,
                "params_string": "7B",
                "loaded_instances": [
                    {"id": "example/model-q4", "config": {"context_length": 8192}}
                ],
                "max_context_length": 32768,
                "format": "gguf",
                "capabilities": {
                    "vision": False,
                    "trained_for_tool_use": True,
                },
            }
        ]
    }

    with patch(
        "athena.model.adapters.lm_studio.urlopen",
        return_value=FakeResponse(payload),
    ):
        models = provider.discover_models()

    assert len(models) == 1
    model = models[0]
    assert model.provider == "lm_studio"
    assert model.backend_model_id == "example/model-q4"
    assert model.display_name == "Example Model"
    assert model.model_type == "llm"
    assert model.context_capacity == 32768
    assert model.loaded_context_length == 8192
    assert model.quantization == "Q4_K_M"
    assert model.loaded is True
    assert model.vision is False
    assert model.trained_for_tool_use is True


def test_lm_studio_health_is_unavailable_when_server_cannot_be_reached() -> None:
    provider = LMStudioProvider("http://127.0.0.1:1234")

    with patch(
        "athena.model.adapters.lm_studio.urlopen",
        side_effect=URLError("connection refused"),
    ):
        health = provider.health()

    assert health.status is ProviderHealthStatus.UNAVAILABLE
    assert health.detail is not None
    assert "not reachable" in health.detail


def test_lm_studio_rejects_malformed_model_payload() -> None:
    provider = LMStudioProvider("http://127.0.0.1:1234")

    with patch(
        "athena.model.adapters.lm_studio.urlopen",
        return_value=FakeResponse({"unexpected": []}),
    ):
        with pytest.raises(ProviderProtocolError, match="models"):
            provider.discover_models()


def test_lm_studio_controlled_structured_uses_native_reasoning_off() -> None:
    provider = LMStudioProvider("http://127.0.0.1:1234")
    captured: dict[str, object] = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse(
            {
                "model_instance_id": "example/model-q4",
                "output": [{"type": "message", "content": '{"answer":42}'}],
                "stats": {
                    "input_tokens": 20,
                    "total_output_tokens": 5,
                    "reasoning_output_tokens": 0,
                },
            }
        )

    with patch("athena.model.adapters.lm_studio.urlopen", side_effect=fake_urlopen):
        result = provider.generate_controlled_structured(
            model_id="example/model-q4",
            messages=(
                ModelChatMessage(role="system", content="Return structured output."),
                ModelChatMessage(role="user", content="Give the answer."),
            ),
            schema_id="answer_v1",
            json_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {"answer": {"type": "integer"}},
                "required": ["answer"],
            },
            reasoning_mode="off",
            context_length=5300,
            max_output_tokens=2000,
            temperature=0.0,
            top_p=0.95,
            top_k=40,
            min_p=0.05,
            repeat_penalty=1.1,
        )

    assert result == {"answer": 42}
    assert provider.controlled_structured_transport_id == "lmstudio_native_chat_instance_reuse_v2"
    assert captured["url"] == "http://127.0.0.1:1234/api/v1/chat"
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["reasoning"] == "off"
    assert payload["context_length"] == 5300
    assert payload["max_output_tokens"] == 2000
    assert payload["temperature"] == 0.0
    assert payload["top_p"] == 0.95
    assert payload["top_k"] == 40
    assert payload["min_p"] == 0.05
    assert payload["repeat_penalty"] == 1.1
    assert payload["stream"] is False
    assert payload["store"] is False
    assert "ATHENA_SCHEMA_ID: answer_v1" in payload["system_prompt"]
    assert "athena.controlled_structured_json/1" in payload["system_prompt"]


def test_lm_studio_controlled_structured_rejects_reasoning_tokens_when_off() -> None:
    provider = LMStudioProvider("http://127.0.0.1:1234")
    response = FakeResponse(
        {
            "model_instance_id": "example/model-q4",
            "output": [{"type": "message", "content": '{"answer":42}'}],
            "stats": {
                "input_tokens": 20,
                "total_output_tokens": 6,
                "reasoning_output_tokens": 1,
            },
        }
    )

    with patch("athena.model.adapters.lm_studio.urlopen", return_value=response):
        with pytest.raises(ProviderProtocolError, match="reasoning tokens"):
            provider.generate_controlled_structured(
                model_id="example/model-q4",
                messages=(
                    ModelChatMessage(role="system", content="Return structured output."),
                    ModelChatMessage(role="user", content="Give the answer."),
                ),
                schema_id="answer_v1",
                json_schema={"type": "object"},
                reasoning_mode="off",
                context_length=5300,
                max_output_tokens=2000,
                temperature=0.0,
                top_p=0.95,
                top_k=40,
                min_p=0.05,
                repeat_penalty=1.1,
            )


def test_lm_studio_controlled_structured_reuses_returned_runtime_instance() -> None:
    provider = LMStudioProvider("http://127.0.0.1:1234")
    payloads: list[dict[str, object]] = []

    def fake_urlopen(request, timeout):
        del timeout
        payload = json.loads(request.data.decode("utf-8"))
        payloads.append(payload)
        return FakeResponse(
            {
                "model_instance_id": "example/model-q4:runtime-1",
                "output": [{"type": "message", "content": '{"answer":42}'}],
                "stats": {
                    "input_tokens": 20,
                    "total_output_tokens": 5,
                    "reasoning_output_tokens": 0,
                },
            }
        )

    kwargs = {
        "model_id": "example/model-q4",
        "messages": (
            ModelChatMessage(role="system", content="Return structured output."),
            ModelChatMessage(role="user", content="Give the answer."),
        ),
        "schema_id": "answer_v1",
        "json_schema": {"type": "object"},
        "reasoning_mode": "off",
        "context_length": 5300,
        "max_output_tokens": 2000,
        "temperature": 0.0,
        "top_p": 0.95,
        "top_k": 40,
        "min_p": 0.05,
        "repeat_penalty": 1.1,
    }

    with patch("athena.model.adapters.lm_studio.urlopen", side_effect=fake_urlopen):
        assert provider.generate_controlled_structured(**kwargs) == {"answer": 42}
        assert provider.generate_controlled_structured(**kwargs) == {"answer": 42}

    assert len(payloads) == 2
    assert payloads[0]["model"] == "example/model-q4"
    assert payloads[0]["context_length"] == 5300
    assert payloads[1]["model"] == "example/model-q4:runtime-1"
    assert "context_length" not in payloads[1]
