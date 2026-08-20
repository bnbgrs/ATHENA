from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.error import URLError

import pytest

from athena.api import client as client_module
from athena.api.client import CoreApiClient, CoreApiClientError


class _Response:
    def __init__(self, payload: dict[str, Any], *, status: int = 200) -> None:
        self.status = status
        self._raw = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *args: object) -> bool:
        del args
        return False

    def read(self) -> bytes:
        return self._raw


def _bootstrap(runtime_root: Path) -> None:
    runtime_root.mkdir(parents=True, exist_ok=True)
    token_path = runtime_root / "core-api.token"
    token_path.write_text("token-one\n", encoding="ascii")
    (runtime_root / "core-api.json").write_text(
        json.dumps(
            {
                "api_version": "v1",
                "host": "127.0.0.1",
                "port": 32123,
                "token_path": str(token_path),
                "process_id": 1234,
            }
        ),
        encoding="utf-8",
    )


def _thread_payload() -> dict[str, Any]:
    return {
        "chat_id": "11111111-1111-1111-1111-111111111111",
        "started_at_us": 1,
        "ended_at_us": None,
        "archive_mode": "standard",
        "lifecycle_state": "active",
        "messages": [],
    }


def test_direct_chat_client_posts_json_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_root = tmp_path / "api"
    _bootstrap(runtime_root)
    calls = 0

    def fake_urlopen(request: Any, timeout: float) -> _Response:
        nonlocal calls
        calls += 1
        assert timeout == 45.0
        assert request.get_method() == "POST"
        assert request.full_url.endswith(
            "/api/v1/chats/11111111-1111-1111-1111-111111111111/messages"
        )
        assert request.get_header("Content-type") == "application/json"
        assert json.loads(request.data.decode("utf-8")) == {
            "content": "hello",
            "model_id": "qwen-test",
        }
        return _Response(_thread_payload())

    monkeypatch.setattr(client_module, "urlopen", fake_urlopen)

    client = CoreApiClient(
        runtime_root,
        timeout_seconds=2.0,
        generation_timeout_seconds=45.0,
    )
    response = client.send_chat_message(
        "11111111-1111-1111-1111-111111111111",
        content="hello",
        model_id="qwen-test",
    )

    assert response.chat_id == "11111111-1111-1111-1111-111111111111"
    assert calls == 1


def test_direct_chat_client_never_retries_ambiguous_post(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_root = tmp_path / "api"
    _bootstrap(runtime_root)
    calls = 0

    def fake_urlopen(request: Any, timeout: float) -> _Response:
        nonlocal calls
        del request, timeout
        calls += 1
        raise URLError("response lost")

    monkeypatch.setattr(client_module, "urlopen", fake_urlopen)

    client = CoreApiClient(
        runtime_root,
        generation_timeout_seconds=45.0,
    )
    with pytest.raises(CoreApiClientError, match="unavailable"):
        client.send_chat_message(
            "11111111-1111-1111-1111-111111111111",
            content="hello",
        )

    assert calls == 1
