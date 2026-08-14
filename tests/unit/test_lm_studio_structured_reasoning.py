from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import pytest

from athena.model.adapters import lm_studio
from athena.model.adapters.lm_studio import LMStudioProvider, ProviderProtocolError
from athena.model.domain import ModelChatMessage


class _FakeResponse:
    def __init__(self, payload: Mapping[str, Any]) -> None:
        self._raw = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: object) -> bool:
        del args
        return False

    def read(self) -> bytes:
        return self._raw


def _provider() -> LMStudioProvider:
    return LMStudioProvider(
        base_url="http://127.0.0.1:1234",
        timeout_seconds=1.0,
        generation_timeout_seconds=1.0,
    )


def _schema() -> Mapping[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["ok"],
        "properties": {"ok": {"type": "boolean"}},
    }


def test_generate_structured_forces_reasoning_off_per_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(request: Any, timeout: float) -> _FakeResponse:
        del timeout
        assert request.data is not None
        captured.update(json.loads(request.data.decode("utf-8")))
        return _FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps({"ok": True}),
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr(lm_studio, "urlopen", fake_urlopen)

    result = _provider().generate_structured(
        model_id="fake-model",
        messages=(ModelChatMessage(role="user", content="Return JSON."),),
        schema_id="athena_test_schema",
        json_schema=_schema(),
        max_output_tokens=64,
    )

    assert result == {"ok": True}
    assert captured["reasoning_effort"] == "none"
    assert captured["temperature"] == 0.0
    assert captured["stream"] is False
    assert captured["max_tokens"] == 64


@pytest.mark.parametrize("reasoning_key", ["reasoning", "reasoning_content"])
def test_generate_structured_rejects_backend_reasoning_despite_off_pin(
    monkeypatch: pytest.MonkeyPatch,
    reasoning_key: str,
) -> None:
    def fake_urlopen(request: Any, timeout: float) -> _FakeResponse:
        del request, timeout
        return _FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            reasoning_key: "hidden reasoning that must not exist",
                            "content": json.dumps({"ok": True}),
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr(lm_studio, "urlopen", fake_urlopen)

    with pytest.raises(
        ProviderProtocolError,
        match="reasoning content despite ATHENA",
    ):
        _provider().generate_structured(
            model_id="fake-model",
            messages=(ModelChatMessage(role="user", content="Return JSON."),),
            schema_id="athena_test_schema",
            json_schema=_schema(),
            max_output_tokens=64,
        )
