import json
from unittest.mock import patch
from urllib.error import URLError

import pytest

from athena.model.adapters.lm_studio import (
    LMStudioProvider,
    ProviderProtocolError,
)
from athena.model.domain import ProviderHealthStatus


class FakeResponse:
    def __init__(self, payload: object) -> None:
        self._bytes = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return self._bytes


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
