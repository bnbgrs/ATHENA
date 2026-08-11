from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from athena.model.adapters.lm_studio import LMStudioProvider, ProviderProtocolError
from athena.model.domain import ModelChatMessage


class FakeStreamResponse:
    def __init__(self, lines: list[bytes]) -> None:
        self.lines = lines

    def __enter__(self) -> "FakeStreamResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def __iter__(self):
        return iter(self.lines)


def _data(payload: object) -> bytes:
    return f"data: {json.dumps(payload)}\n".encode()


def test_lm_studio_streams_openai_chat_completion_content() -> None:
    response = FakeStreamResponse(
        [
            _data({"choices": [{"delta": {"role": "assistant", "content": ""}}]}),
            _data({"choices": [{"delta": {"content": "Hello"}}]}),
            _data({"choices": [{"delta": {"content": " world"}}]}),
            b"data: [DONE]\n",
        ]
    )
    provider = LMStudioProvider("http://127.0.0.1:1234")

    with patch("athena.model.adapters.lm_studio.urlopen", return_value=response) as mocked:
        chunks = tuple(
            provider.stream_chat(
                model_id="example/model",
                messages=(ModelChatMessage(role="user", content="Hi"),),
            )
        )

    assert chunks == ("Hello", " world")
    request = mocked.call_args.args[0]
    assert request.full_url == "http://127.0.0.1:1234/v1/chat/completions"
    payload = json.loads(request.data.decode("utf-8"))
    assert payload == {
        "model": "example/model",
        "messages": [{"role": "user", "content": "Hi"}],
        "stream": True,
    }


def test_lm_studio_requires_done_marker() -> None:
    response = FakeStreamResponse(
        [_data({"choices": [{"delta": {"content": "partial"}}]})]
    )
    provider = LMStudioProvider("http://127.0.0.1:1234")

    with patch("athena.model.adapters.lm_studio.urlopen", return_value=response):
        with pytest.raises(ProviderProtocolError, match="DONE"):
            tuple(
                provider.stream_chat(
                    model_id="example/model",
                    messages=(ModelChatMessage(role="user", content="Hi"),),
                )
            )
