from __future__ import annotations

import json
import socket
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from athena.api.client import CoreApiClient, CoreApiClientError
from athena.api.server import CoreApiServer
from athena.api.service import CoreApiFacade
from athena.chat.models import ChatMessage, ChatSummary, ChatThread, MessageType
from athena.model.domain import ModelInfo, ProviderHealth, ProviderHealthStatus
from athena.observability.health import HealthService


class _Chat:
    def __init__(self) -> None:
        self.chat_id = uuid.UUID("11111111-1111-1111-1111-111111111111")
        self.message_id = uuid.UUID("22222222-2222-2222-2222-222222222222")
        self.revision_id = uuid.UUID("33333333-3333-3333-3333-333333333333")
        self.actor_id = uuid.UUID("44444444-4444-4444-4444-444444444444")
        self.create_calls = 0

    def list_chats(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[ChatSummary, ...]:
        assert 1 <= limit <= 200
        assert offset == 0
        return (
            ChatSummary(
                chat_id=self.chat_id,
                started_at_us=10,
                ended_at_us=None,
                archive_mode="standard",
                lifecycle_state="active",
                message_count=1,
            ),
        )

    def create_chat(self) -> uuid.UUID:
        self.create_calls += 1
        return self.chat_id

    def load_chat(self, chat_id: uuid.UUID) -> ChatThread:
        assert chat_id == self.chat_id
        return ChatThread(
            chat_id=self.chat_id,
            started_at_us=10,
            ended_at_us=None,
            archive_mode="standard",
            lifecycle_state="active",
            messages=(
                ChatMessage(
                    message_id=self.message_id,
                    chat_id=self.chat_id,
                    sequence_no=1,
                    message_type=MessageType.USER,
                    actor_id=self.actor_id,
                    created_at_us=11,
                    revision_id=self.revision_id,
                    content="hello",
                    content_format="text/plain",
                ),
            ),
        )


class _Provider:
    @property
    def provider_id(self) -> str:
        return "lm_studio"

    def health(self) -> ProviderHealth:
        return ProviderHealth(status=ProviderHealthStatus.READY)

    def discover_models(self) -> tuple[ModelInfo, ...]:
        return (
            ModelInfo(
                provider="lm_studio",
                backend_model_id="example/model",
                display_name="Example Model",
                model_type="llm",
                context_capacity=262144,
                quantization="Q4_K_S",
                loaded=True,
                vision=True,
                trained_for_tool_use=True,
                loaded_context_length=8192,
            ),
        )


def _facade() -> tuple[CoreApiFacade, _Chat]:
    chat = _Chat()
    health = HealthService()
    health.mark_ok()
    facade = CoreApiFacade(
        health=health,
        chat=chat,  # type: ignore[arg-type]
        model_provider=_Provider(),
    )
    return facade, chat


def _server(tmp_path: Path) -> tuple[CoreApiServer, _Chat]:
    facade, chat = _facade()
    return (
        CoreApiServer(
            facade=facade,
            runtime_root=tmp_path / "api",
        ),
        chat,
    )


def test_loopback_server_and_desktop_client_roundtrip(tmp_path: Path) -> None:
    server, chat = _server(tmp_path)
    server.start()
    try:
        assert server.running is True
        assert server.discovery is not None
        assert server.discovery.host == "127.0.0.1"
        assert server.port is not None
        assert server.port > 0

        client = CoreApiClient(tmp_path / "api", timeout_seconds=2.0)
        health = client.health()
        capabilities = client.capabilities()
        chats = client.list_chats(limit=7)
        created = client.create_chat()
        loaded = client.load_chat(str(chat.chat_id))
        models = client.list_models()

        assert health.core_status == "ok"
        assert "chat.read" in capabilities.features
        assert chats[0].chat_id == str(chat.chat_id)
        assert created.chat_id == str(chat.chat_id)
        assert loaded.messages[0].content == "hello"
        assert models[0].backend_model_id == "example/model"
        assert chat.create_calls == 1
    finally:
        server.stop()

    assert server.running is False
    assert not (tmp_path / "api" / "core-api.json").exists()
    assert not (tmp_path / "api" / "core-api.token").exists()

    with pytest.raises(CoreApiClientError, match="discovery"):
        CoreApiClient(tmp_path / "api", timeout_seconds=0.2).health()


def test_loopback_server_requires_real_session_token(tmp_path: Path) -> None:
    server, _chat = _server(tmp_path)
    server.start()
    try:
        assert server.port is not None
        request = Request(
            f"http://127.0.0.1:{server.port}/api/v1/health",
            headers={"Accept": "application/json"},
        )
        with pytest.raises(HTTPError) as exc_info:
            urlopen(request, timeout=2.0)
        error = exc_info.value
        payload = json.loads(error.read().decode("utf-8"))
        assert error.code == 401
        assert payload["code"] == "unauthorized"
        assert "Traceback" not in payload["message"]
    finally:
        server.stop()


def test_loopback_server_rejects_non_loopback_binding(tmp_path: Path) -> None:
    facade, _chat = _facade()

    with pytest.raises(ValueError, match="loopback"):
        CoreApiServer(
            facade=facade,
            runtime_root=tmp_path / "other-api",
            host="0.0.0.0",
        )


def test_loopback_server_start_stop_are_idempotent(tmp_path: Path) -> None:
    server, _chat = _server(tmp_path)

    server.start()
    first_port = server.port
    server.start()

    assert server.running is True
    assert server.port == first_port

    server.stop()
    server.stop()

    assert server.running is False


def test_loopback_listener_is_closed_after_stop(tmp_path: Path) -> None:
    server, _chat = _server(tmp_path)
    server.start()
    assert server.port is not None
    port = server.port
    server.stop()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        assert probe.connect_ex(("127.0.0.1", port)) != 0


def test_loopback_server_rolls_back_when_discovery_publication_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server, _chat = _server(tmp_path)

    def fail_publish(*, port: int) -> None:
        assert port > 0
        raise RuntimeError("synthetic discovery failure")

    monkeypatch.setattr(server.runtime, "publish", fail_publish)

    with pytest.raises(RuntimeError, match="synthetic discovery failure"):
        server.start()

    assert server.running is False
    assert server.discovery is None
    assert not (tmp_path / "api" / "core-api.json").exists()
    assert not (tmp_path / "api" / "core-api.token").exists()

    server.stop()
