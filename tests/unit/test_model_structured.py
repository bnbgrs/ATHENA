import io
import json
from unittest.mock import patch
from urllib.error import HTTPError

import pytest

from athena.model.adapters.lm_studio import (
    LMStudioProvider,
    ProviderContextLimitError,
    ProviderOutputLimitError,
    ProviderProtocolError,
    ProviderRefusalError,
)
from athena.model.domain import ModelChatMessage


class FakeResponse:
    def __init__(self, payload: object) -> None:
        self._bytes = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return self._bytes


def test_lm_studio_generates_schema_constrained_json() -> None:
    response = FakeResponse(
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": json.dumps({"items": [{"name": "alpha"}]}),
                    }
                }
            ]
        }
    )
    provider = LMStudioProvider("http://127.0.0.1:1234")
    schema = {
        "type": "object",
        "properties": {"items": {"type": "array"}},
        "required": ["items"],
    }

    with patch("athena.model.adapters.lm_studio.urlopen", return_value=response) as mocked:
        result = provider.generate_structured(
            model_id="example/model",
            messages=(ModelChatMessage(role="user", content="Extract."),),
            schema_id="example_schema_v1",
            json_schema=schema,
        )

    assert result == {"items": [{"name": "alpha"}]}
    request = mocked.call_args.args[0]
    payload = json.loads(request.data.decode("utf-8"))
    assert payload["model"] == "example/model"
    assert payload["stream"] is False
    assert payload["temperature"] == 0.0
    assert payload["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "example_schema_v1",
            "strict": True,
            "schema": schema,
        },
    }


def test_lm_studio_rejects_non_json_structured_content() -> None:
    response = FakeResponse(
        {"choices": [{"message": {"role": "assistant", "content": "not-json"}}]}
    )
    provider = LMStudioProvider("http://127.0.0.1:1234")

    with patch("athena.model.adapters.lm_studio.urlopen", return_value=response):
        with pytest.raises(ProviderProtocolError, match="not valid JSON"):
            provider.generate_structured(
                model_id="example/model",
                messages=(ModelChatMessage(role="user", content="Extract."),),
                schema_id="example_schema_v1",
                json_schema={"type": "object"},
            )


def test_lm_studio_classifies_structured_output_token_limit() -> None:
    response = FakeResponse(
        {
            "choices": [
                {
                    "finish_reason": "length",
                    "message": {
                        "role": "assistant",
                        "content": '{"items": [',
                    },
                }
            ]
        }
    )
    provider = LMStudioProvider("http://127.0.0.1:1234")

    with patch("athena.model.adapters.lm_studio.urlopen", return_value=response):
        with pytest.raises(
            ProviderOutputLimitError,
            match="output-token limit",
        ):
            provider.generate_structured(
                model_id="example/model",
                messages=(ModelChatMessage(role="user", content="Extract."),),
                schema_id="example_schema_v1",
                json_schema={"type": "object"},
                max_output_tokens=100,
            )


def test_lm_studio_classifies_backend_context_overflow() -> None:
    provider = LMStudioProvider("http://127.0.0.1:1234")
    body = io.BytesIO(
        json.dumps(
            {
                "error": {
                    "message": (
                        "ATHENA_HTTP_SECRET_CANARY "
                        "maximum context length exceeded: too many tokens"
                    )
                }
            }
        ).encode("utf-8")
    )
    error = HTTPError(
        provider.chat_completions_url,
        400,
        "Bad Request",
        hdrs=None,
        fp=body,
    )

    with patch("athena.model.adapters.lm_studio.urlopen", side_effect=error):
        with pytest.raises(
            ProviderContextLimitError,
            match="context capacity",
        ) as caught:
            provider.generate_structured(
                model_id="example/model",
                messages=(ModelChatMessage(role="user", content="Analyze."),),
                schema_id="example_schema_v1",
                json_schema={"type": "object"},
            )

    assert "ATHENA_HTTP_SECRET_CANARY" not in str(caught.value)


def test_lm_studio_structured_generation_honors_max_output_tokens() -> None:
    response = FakeResponse(
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": json.dumps({"items": []}),
                    }
                }
            ]
        }
    )
    provider = LMStudioProvider("http://127.0.0.1:1234")

    with patch("athena.model.adapters.lm_studio.urlopen", return_value=response) as mocked:
        provider.generate_structured(
            model_id="example/model",
            messages=(ModelChatMessage(role="user", content="Extract."),),
            schema_id="example_schema_v1",
            json_schema={"type": "object"},
            max_output_tokens=900,
        )

    request = mocked.call_args.args[0]
    payload = json.loads(request.data.decode("utf-8"))
    assert payload["max_tokens"] == 900


def test_lm_studio_classifies_explicit_structured_refusal() -> None:
    response = FakeResponse(
        {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "refusal": "ATHENA_REFUSAL_SECRET_CANARY",
                    },
                }
            ]
        }
    )
    provider = LMStudioProvider("http://127.0.0.1:1234")

    with patch("athena.model.adapters.lm_studio.urlopen", return_value=response):
        with pytest.raises(
            ProviderRefusalError,
            match="refused by the model",
        ) as caught:
            provider.generate_structured(
                model_id="example/model",
                messages=(ModelChatMessage(role="user", content="Extract."),),
                schema_id="example_schema_v1",
                json_schema={"type": "object"},
            )

    assert "ATHENA_REFUSAL_SECRET_CANARY" not in str(caught.value)
