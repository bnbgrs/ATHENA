from __future__ import annotations

import io
import json
from collections.abc import Mapping
from typing import Any
from urllib.error import HTTPError, URLError

import pytest

from athena.model.adapters import lm_studio
from athena.model.adapters.lm_studio import (
    LMStudioProvider,
    ModelProviderError,
    ProviderContextLimitError,
)
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


def _kwargs() -> dict[str, Any]:
    return {
        "model_id": "example/model-q4",
        "messages": (
            ModelChatMessage(
                role="system",
                content="Return structured output.",
            ),
            ModelChatMessage(
                role="user",
                content="Give the answer.",
            ),
        ),
        "schema_id": "answer_v1",
        "json_schema": {
            "type": "object",
            "properties": {
                "answer": {
                    "type": "integer",
                }
            },
            "required": ["answer"],
        },
        "reasoning_mode": "off",
        "context_length": 5300,
        "max_output_tokens": 2000,
        "temperature": 0.0,
        "top_p": 0.95,
        "top_k": 40,
        "min_p": 0.05,
        "repeat_penalty": 1.1,
    }


def _chat_response(instance_id: str) -> _FakeResponse:
    return _FakeResponse(
        {
            "model_instance_id": instance_id,
            "output": [
                {
                    "type": "message",
                    "content": '{"answer":42}',
                }
            ],
            "stats": {
                "input_tokens": 20,
                "total_output_tokens": 5,
                "reasoning_output_tokens": 0,
            },
        }
    )


def _http_error(
    url: str,
    *,
    code: int,
    detail: str,
) -> HTTPError:
    body = json.dumps(
        {
            "error": {
                "message": detail,
            }
        }
    ).encode("utf-8")

    return HTTPError(
        url,
        code,
        detail,
        hdrs=None,
        fp=io.BytesIO(body),
    )


def test_controlled_structured_recovers_after_cached_instance_unload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider()
    calls: list[tuple[str, str, dict[str, Any] | None]] = []
    chat_no = 0

    def fake_urlopen(
        request: Any,
        timeout: float,
    ) -> _FakeResponse:
        nonlocal chat_no
        del timeout

        method = request.get_method()
        payload = (
            None
            if request.data is None
            else json.loads(request.data.decode("utf-8"))
        )
        calls.append((method, request.full_url, payload))

        if request.full_url == provider.models_url:
            return _FakeResponse(
                {
                    "models": [
                        {
                            "key": "example/model-q4",
                            "loaded_instances": [],
                        }
                    ]
                }
            )

        chat_no += 1

        if chat_no == 1:
            return _chat_response("example/model-q4:runtime-1")

        if chat_no == 2:
            raise _http_error(
                request.full_url,
                code=404,
                detail="model instance not found",
            )

        if chat_no == 3:
            return _chat_response("example/model-q4:runtime-2")

        if chat_no == 4:
            return _chat_response("example/model-q4:runtime-2")

        raise AssertionError("Unexpected native-chat call.")

    monkeypatch.setattr(
        lm_studio,
        "urlopen",
        fake_urlopen,
    )

    kwargs = _kwargs()

    assert provider.generate_controlled_structured(
        **kwargs
    ) == {"answer": 42}
    assert provider.generate_controlled_structured(
        **kwargs
    ) == {"answer": 42}
    assert provider.generate_controlled_structured(
        **kwargs
    ) == {"answer": 42}

    assert len(calls) == 5

    first = calls[0][2]
    stale = calls[1][2]
    reacquire = calls[3][2]
    reused = calls[4][2]

    assert first is not None
    assert stale is not None
    assert reacquire is not None
    assert reused is not None

    assert first["model"] == "example/model-q4"
    assert first["context_length"] == 5300

    assert stale["model"] == "example/model-q4:runtime-1"
    assert "context_length" not in stale

    assert calls[2][0] == "GET"
    assert calls[2][1] == provider.models_url
    assert calls[2][2] is None

    assert reacquire["model"] == "example/model-q4"
    assert reacquire["context_length"] == 5300

    assert reused["model"] == "example/model-q4:runtime-2"
    assert "context_length" not in reused


def test_controlled_structured_reacquires_when_cached_context_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider()
    chat_no = 0
    payloads: list[dict[str, Any]] = []

    def fake_urlopen(
        request: Any,
        timeout: float,
    ) -> _FakeResponse:
        nonlocal chat_no
        del timeout

        if request.full_url == provider.models_url:
            return _FakeResponse(
                {
                    "models": [
                        {
                            "key": "example/model-q4",
                            "loaded_instances": [
                                {
                                    "id": "example/model-q4:runtime-1",
                                    "config": {
                                        "context_length": 8192,
                                    },
                                }
                            ],
                        }
                    ]
                }
            )

        payload = json.loads(request.data.decode("utf-8"))
        payloads.append(payload)
        chat_no += 1

        if chat_no == 1:
            return _chat_response("example/model-q4:runtime-1")

        if chat_no == 2:
            raise _http_error(
                request.full_url,
                code=404,
                detail="model instance unavailable",
            )

        return _chat_response("example/model-q4:runtime-2")

    monkeypatch.setattr(
        lm_studio,
        "urlopen",
        fake_urlopen,
    )

    kwargs = _kwargs()

    assert provider.generate_controlled_structured(
        **kwargs
    ) == {"answer": 42}
    assert provider.generate_controlled_structured(
        **kwargs
    ) == {"answer": 42}

    assert len(payloads) == 3
    assert payloads[1]["model"] == "example/model-q4:runtime-1"
    assert payloads[2]["model"] == "example/model-q4"
    assert payloads[2]["context_length"] == 5300


def test_controlled_structured_does_not_retry_unrelated_cached_instance_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider()
    chat_no = 0
    calls = 0

    def fake_urlopen(
        request: Any,
        timeout: float,
    ) -> _FakeResponse:
        nonlocal chat_no, calls
        del timeout
        calls += 1

        if request.full_url == provider.models_url:
            return _FakeResponse(
                {
                    "models": [
                        {
                            "key": "example/model-q4",
                            "loaded_instances": [
                                {
                                    "id": "example/model-q4:runtime-1",
                                    "config": {
                                        "context_length": 5300,
                                    },
                                }
                            ],
                        }
                    ]
                }
            )

        chat_no += 1

        if chat_no == 1:
            return _chat_response("example/model-q4:runtime-1")

        raise _http_error(
            request.full_url,
            code=500,
            detail="synthetic backend failure",
        )

    monkeypatch.setattr(
        lm_studio,
        "urlopen",
        fake_urlopen,
    )

    kwargs = _kwargs()

    assert provider.generate_controlled_structured(
        **kwargs
    ) == {"answer": 42}

    with pytest.raises(
        ModelProviderError,
        match="HTTP 500",
    ):
        provider.generate_controlled_structured(
            **kwargs
        )

    assert chat_no == 2
    assert calls == 3


def test_controlled_structured_preserves_error_when_lifecycle_probe_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider()
    chat_no = 0
    calls = 0

    def fake_urlopen(
        request: Any,
        timeout: float,
    ) -> _FakeResponse:
        nonlocal chat_no, calls
        del timeout
        calls += 1

        if request.full_url == provider.models_url:
            raise URLError(
                "synthetic models endpoint outage"
            )

        chat_no += 1

        if chat_no == 1:
            return _chat_response("example/model-q4:runtime-1")

        raise _http_error(
            request.full_url,
            code=404,
            detail="model instance not found",
        )

    monkeypatch.setattr(
        lm_studio,
        "urlopen",
        fake_urlopen,
    )

    kwargs = _kwargs()

    assert provider.generate_controlled_structured(
        **kwargs
    ) == {"answer": 42}

    with pytest.raises(
        ModelProviderError,
        match="HTTP 404",
    ):
        provider.generate_controlled_structured(
            **kwargs
        )

    assert chat_no == 2
    assert calls == 3


def test_controlled_structured_context_limit_error_is_not_lifecycle_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider()
    chat_no = 0
    calls = 0

    def fake_urlopen(
        request: Any,
        timeout: float,
    ) -> _FakeResponse:
        nonlocal chat_no, calls
        del timeout
        calls += 1

        if request.full_url == provider.models_url:
            raise AssertionError(
                "Context-limit failures must not trigger lifecycle probing."
            )

        chat_no += 1

        if chat_no == 1:
            return _chat_response("example/model-q4:runtime-1")

        raise _http_error(
            request.full_url,
            code=400,
            detail="maximum context length exceeded",
        )

    monkeypatch.setattr(
        lm_studio,
        "urlopen",
        fake_urlopen,
    )

    kwargs = _kwargs()

    assert provider.generate_controlled_structured(
        **kwargs
    ) == {"answer": 42}

    with pytest.raises(
        ProviderContextLimitError,
        match="context capacity",
    ):
        provider.generate_controlled_structured(
            **kwargs
        )

    assert chat_no == 2
    assert calls == 2


def test_controlled_structured_transport_identity_remains_v2() -> None:
    assert (
        _provider().controlled_structured_transport_id
        == "lmstudio_native_chat_instance_reuse_v2"
    )
