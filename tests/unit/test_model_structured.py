import json
from unittest.mock import patch

import pytest

from athena.model.adapters.lm_studio import LMStudioProvider, ProviderProtocolError
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
