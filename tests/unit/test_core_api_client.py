from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError

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


def _bootstrap(runtime_root: Path, *, port: int = 32123, token: str = "token-one") -> None:
    runtime_root.mkdir(parents=True, exist_ok=True)
    token_path = runtime_root / "core-api.token"
    token_path.write_text(token + "\n", encoding="ascii")
    (runtime_root / "core-api.json").write_text(
        json.dumps(
            {
                "api_version": "v1",
                "host": "127.0.0.1",
                "port": port,
                "token_path": str(token_path),
                "process_id": 1234,
            }
        ),
        encoding="utf-8",
    )


def _request_header(request: Any, name: str) -> str | None:
    return request.get_header(name)


def test_client_health_reads_discovery_and_authenticates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_root = tmp_path / "api"
    _bootstrap(runtime_root)
    seen: list[tuple[str, str, str | None]] = []

    def fake_urlopen(request: Any, timeout: float) -> _Response:
        assert timeout == 2.5
        seen.append(
            (
                request.get_method(),
                request.full_url,
                _request_header(request, "Authorization"),
            )
        )
        return _Response({"api_version": "v1", "core_status": "ready", "detail": None})

    monkeypatch.setattr(client_module, "urlopen", fake_urlopen)

    response = CoreApiClient(runtime_root, timeout_seconds=2.5).health()

    assert response.core_status == "ready"
    assert seen == [
        (
            "GET",
            "http://127.0.0.1:32123/api/v1/health",
            "Bearer token-one",
        )
    ]


def test_client_reloads_bootstrap_and_retries_safe_get_after_core_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_root = tmp_path / "api"
    _bootstrap(runtime_root, port=32123, token="token-one")
    calls = 0

    def fake_urlopen(request: Any, timeout: float) -> _Response:
        nonlocal calls
        del timeout
        calls += 1
        if calls == 1:
            _bootstrap(runtime_root, port=32124, token="token-two")
            raise URLError("old core stopped")
        assert request.full_url == "http://127.0.0.1:32124/api/v1/capabilities"
        assert _request_header(request, "Authorization") == "Bearer token-two"
        return _Response({"api_version": "v1", "features": ["health"]})

    monkeypatch.setattr(client_module, "urlopen", fake_urlopen)

    response = CoreApiClient(runtime_root).capabilities()

    assert response.features == ("health",)
    assert calls == 2


def test_client_does_not_retry_ambiguous_post_transport_failure(
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

    with pytest.raises(CoreApiClientError, match="unavailable") as exc_info:
        CoreApiClient(runtime_root).create_chat()

    assert exc_info.value.retryable is True
    assert calls == 1


def test_client_rejects_non_loopback_discovery(tmp_path: Path) -> None:
    runtime_root = tmp_path / "api"
    _bootstrap(runtime_root)
    discovery = runtime_root / "core-api.json"
    payload = json.loads(discovery.read_text(encoding="utf-8"))
    payload["host"] = "192.168.1.10"
    discovery.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(CoreApiClientError, match="non-loopback") as exc_info:
        CoreApiClient(runtime_root).health()

    assert exc_info.value.code == "invalid_discovery"


def test_client_rejects_token_path_outside_runtime_root(tmp_path: Path) -> None:
    runtime_root = tmp_path / "api"
    _bootstrap(runtime_root)
    external = tmp_path / "foreign.token"
    external.write_text("foreign-token\n", encoding="ascii")
    discovery = runtime_root / "core-api.json"
    payload = json.loads(discovery.read_text(encoding="utf-8"))
    payload["token_path"] = str(external)
    discovery.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(CoreApiClientError, match="unexpected token path") as exc_info:
        CoreApiClient(runtime_root).health()

    assert exc_info.value.code == "invalid_discovery"


def test_client_surfaces_structured_problem_without_stacktrace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_root = tmp_path / "api"
    _bootstrap(runtime_root)

    def fake_urlopen(request: Any, timeout: float) -> _Response:
        del timeout
        raw = json.dumps(
            {
                "code": "chat_not_found",
                "message": "The requested chat does not exist.",
                "request_id": "request-123",
                "retryable": False,
                "details": None,
            }
        ).encode("utf-8")
        raise HTTPError(
            request.full_url,
            404,
            "Not Found",
            hdrs=None,
            fp=io.BytesIO(raw),
        )

    monkeypatch.setattr(client_module, "urlopen", fake_urlopen)

    with pytest.raises(CoreApiClientError, match="does not exist") as exc_info:
        CoreApiClient(runtime_root).load_chat("019ffake")

    error = exc_info.value
    assert error.status == 404
    assert error.code == "chat_not_found"
    assert error.request_id == "request-123"
    assert "Traceback" not in str(error)


def test_client_parses_chat_and_model_lists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_root = tmp_path / "api"
    _bootstrap(runtime_root)

    def fake_urlopen(request: Any, timeout: float) -> _Response:
        del timeout
        if request.full_url.endswith(
            "/api/v1/chats?limit=7&offset=3"
        ):
            return _Response(
                {
                    "items": [
                        {
                            "chat_id": "chat-1",
                            "started_at_us": 10,
                            "ended_at_us": None,
                            "archive_mode": "default",
                            "lifecycle_state": "active",
                            "message_count": 3,
                        }
                    ]
                }
            )
        if request.full_url.endswith("/api/v1/models"):
            return _Response(
                {
                    "items": [
                        {
                            "provider": "lm_studio",
                            "backend_model_id": "model-1",
                            "display_name": "Model One",
                            "model_type": "llm",
                            "context_capacity": 128000,
                            "quantization": "Q4_K_S",
                            "loaded": True,
                            "vision": False,
                            "trained_for_tool_use": True,
                            "loaded_context_length": 48000,
                        }
                    ]
                }
            )
        raise AssertionError(request.full_url)

    monkeypatch.setattr(client_module, "urlopen", fake_urlopen)
    client = CoreApiClient(runtime_root)

    chats = client.list_chats(
        limit=7,
        offset=3,
    )
    models = client.list_models()

    assert chats[0].chat_id == "chat-1"
    assert chats[0].message_count == 3
    assert models[0].backend_model_id == "model-1"
    assert models[0].loaded_context_length == 48000


def test_client_rejects_invalid_response_shape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_root = tmp_path / "api"
    _bootstrap(runtime_root)

    monkeypatch.setattr(
        client_module,
        "urlopen",
        lambda request, timeout: _Response({"items": ["not-an-object"]}),
    )

    with pytest.raises(CoreApiClientError, match="invalid item") as exc_info:
        CoreApiClient(runtime_root).list_models()

    assert exc_info.value.code == "invalid_response"


def test_client_from_environment_uses_core_api_runtime_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local_root = (tmp_path / "athena-local").resolve()
    monkeypatch.setenv("ATHENA_LOCAL_ROOT", str(local_root))
    monkeypatch.delenv("ATHENA_ARCHIVE_ROOT", raising=False)
    monkeypatch.delenv("ATHENA_BACKUP_ROOT", raising=False)
    monkeypatch.delenv("ATHENA_PROJECTION_ROOT", raising=False)

    client = CoreApiClient.from_environment(timeout_seconds=1.25)

    assert client.runtime_root == local_root / "tmp" / "core-api"
    assert client.timeout_seconds == 1.25


def test_client_exposes_trusted_discovery_process_id(tmp_path: Path) -> None:
    runtime_root = tmp_path / "api"
    _bootstrap(runtime_root)

    assert CoreApiClient(runtime_root).discovery_process_id() == 1234


def test_client_shutdown_command_is_not_retried(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_root = tmp_path / "api"
    _bootstrap(runtime_root)
    calls = 0

    def fake_urlopen(request: Any, timeout: float) -> _Response:
        nonlocal calls
        del timeout
        calls += 1
        assert request.get_method() == "POST"
        assert request.full_url.endswith("/api/v1/system/shutdown")
        return _Response({"accepted": True}, status=202)

    monkeypatch.setattr(client_module, "urlopen", fake_urlopen)

    CoreApiClient(runtime_root).request_shutdown()

    assert calls == 1



def test_client_rejects_negative_chat_offset(
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "api"
    _bootstrap(runtime_root)

    with pytest.raises(
        ValueError,
        match="offset",
    ):
        CoreApiClient(
            runtime_root
        ).list_chats(
            offset=-1
        )
