from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

from athena.api.asgi import CoreApiAsgiApp
from athena.api.runtime import LocalApiRuntime
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

    def list_chats(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[ChatSummary, ...]:
        assert limit > 0
        assert offset >= 0
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


def _facade() -> CoreApiFacade:
    health = HealthService()
    health.mark_ok()
    return CoreApiFacade(
        health=health,
        chat=_Chat(),  # type: ignore[arg-type]
        model_provider=_Provider(),
    )


async def _request(
    app: CoreApiAsgiApp,
    runtime: LocalApiRuntime,
    *,
    method: str,
    path: str,
    query: bytes = b"",
    token: str | None = None,
    origin: str | None = None,
    body: bytes = b"",
) -> tuple[int, dict[str, str], dict[str, Any]]:
    headers: list[tuple[bytes, bytes]] = []
    if token is not None:
        headers.append((b"authorization", f"Bearer {token}".encode("ascii")))
    if origin is not None:
        headers.append((b"origin", origin.encode("ascii")))

    scope: dict[str, Any] = {
        "type": "http",
        "method": method,
        "path": path,
        "query_string": query,
        "headers": headers,
    }
    receive_calls = 0

    async def receive() -> dict[str, Any]:
        nonlocal receive_calls
        receive_calls += 1
        return {
            "type": "http.request",
            "body": body,
            "more_body": False,
        }

    sent: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    await app(scope, receive, send)

    assert len(sent) == 2
    start, response = sent
    assert start["type"] == "http.response.start"
    assert response["type"] == "http.response.body"
    response_headers = {
        key.decode("ascii"): value.decode("ascii") for key, value in start["headers"]
    }
    payload = json.loads(response["body"].decode("utf-8"))
    return int(start["status"]), response_headers, payload


def _app(tmp_path) -> tuple[CoreApiAsgiApp, LocalApiRuntime, str]:
    runtime = LocalApiRuntime(tmp_path / "api")
    runtime.publish(port=32123)
    token = runtime.token_path.read_text(encoding="utf-8").strip()
    return CoreApiAsgiApp(facade=_facade(), runtime=runtime), runtime, token


def test_asgi_requires_session_token(tmp_path) -> None:
    app, runtime, _token = _app(tmp_path)

    status, headers, payload = asyncio.run(
        _request(app, runtime, method="GET", path="/api/v1/health")
    )

    assert status == 401
    assert headers["www-authenticate"] == "Bearer"
    assert payload["code"] == "unauthorized"
    assert "request_id" in payload


def test_asgi_rejects_browser_origin_even_with_token(tmp_path) -> None:
    app, runtime, token = _app(tmp_path)

    status, _headers, payload = asyncio.run(
        _request(
            app,
            runtime,
            method="GET",
            path="/api/v1/health",
            token=token,
            origin="http://example.test",
        )
    )

    assert status == 403
    assert payload["code"] == "browser_origin_rejected"


def test_asgi_health_and_capabilities(tmp_path) -> None:
    app, runtime, token = _app(tmp_path)

    health_status, health_headers, health = asyncio.run(
        _request(
            app,
            runtime,
            method="GET",
            path="/api/v1/health",
            token=token,
        )
    )
    capabilities_status, _, capabilities = asyncio.run(
        _request(
            app,
            runtime,
            method="GET",
            path="/api/v1/capabilities",
            token=token,
        )
    )

    assert health_status == 200
    assert health["core_status"] == "ok"
    assert health_headers["content-type"] == "application/json; charset=utf-8"
    assert health_headers["x-request-id"]
    assert capabilities_status == 200
    assert "chat.read" in capabilities["features"]


def test_asgi_chat_routes_and_limit_validation(tmp_path) -> None:
    app, runtime, token = _app(tmp_path)

    list_status, _, listed = asyncio.run(
        _request(
            app,
            runtime,
            method="GET",
            path="/api/v1/chats",
            query=b"limit=20&offset=1",
            token=token,
        )
    )
    create_status, _, created = asyncio.run(
        _request(
            app,
            runtime,
            method="POST",
            path="/api/v1/chats",
            token=token,
        )
    )
    load_status, _, loaded = asyncio.run(
        _request(
            app,
            runtime,
            method="GET",
            path="/api/v1/chats/11111111-1111-1111-1111-111111111111",
            token=token,
        )
    )
    invalid_status, _, invalid = asyncio.run(
        _request(
            app,
            runtime,
            method="GET",
            path="/api/v1/chats",
            query=b"limit=0",
            token=token,
        )
    )
    invalid_offset_status, _, invalid_offset = asyncio.run(
        _request(
            app,
            runtime,
            method="GET",
            path="/api/v1/chats",
            query=b"limit=20&offset=-1",
            token=token,
        )
    )

    assert list_status == 200
    assert listed["items"][0]["message_count"] == 1
    assert create_status == 201
    assert created["chat_id"] == "11111111-1111-1111-1111-111111111111"
    assert load_status == 200
    assert loaded["messages"][0]["content"] == "hello"
    assert invalid_status == 400
    assert invalid["code"] == "invalid_request"
    assert invalid_offset_status == 400
    assert invalid_offset["code"] == "invalid_request"
    assert "offset" in invalid_offset["message"]


def test_asgi_model_routes(tmp_path) -> None:
    app, runtime, token = _app(tmp_path)

    health_status, _, health = asyncio.run(
        _request(
            app,
            runtime,
            method="GET",
            path="/api/v1/models/health",
            token=token,
        )
    )
    list_status, _, models = asyncio.run(
        _request(
            app,
            runtime,
            method="GET",
            path="/api/v1/models",
            token=token,
        )
    )

    assert health_status == 200
    assert health["status"] == "ready"
    assert list_status == 200
    assert models["items"][0]["backend_model_id"] == "example/model"


def test_asgi_invalid_chat_id_is_safe_400(tmp_path) -> None:
    app, runtime, token = _app(tmp_path)

    status, _, payload = asyncio.run(
        _request(
            app,
            runtime,
            method="GET",
            path="/api/v1/chats/not-a-uuid",
            token=token,
        )
    )

    assert status == 400
    assert payload["code"] == "invalid_request"
    assert "badly formed" in payload["message"]


def test_asgi_unknown_route_is_safe_404(tmp_path) -> None:
    app, runtime, token = _app(tmp_path)

    status, _, payload = asyncio.run(
        _request(
            app,
            runtime,
            method="GET",
            path="/api/v1/does-not-exist",
            token=token,
        )
    )

    assert status == 404
    assert payload["code"] == "not_found"


def test_asgi_known_route_with_wrong_method_is_405(tmp_path) -> None:
    app, runtime, token = _app(tmp_path)

    status, _, payload = asyncio.run(
        _request(
            app,
            runtime,
            method="POST",
            path="/api/v1/health",
            token=token,
        )
    )

    assert status == 405
    assert payload["code"] == "method_not_allowed"


def test_asgi_shutdown_requires_dedicated_process_opt_in(tmp_path) -> None:
    app, runtime, token = _app(tmp_path)

    unavailable_status, _, unavailable = asyncio.run(
        _request(
            app,
            runtime,
            method="POST",
            path="/api/v1/system/shutdown",
            token=token,
        )
    )

    enabled = CoreApiAsgiApp(
        facade=_facade(),
        runtime=runtime,
        allow_shutdown=True,
    )
    accepted_status, _, accepted = asyncio.run(
        _request(
            enabled,
            runtime,
            method="POST",
            path="/api/v1/system/shutdown",
            token=token,
        )
    )

    assert unavailable_status == 409
    assert unavailable["code"] == "shutdown_unavailable"
    assert accepted_status == 202
    assert accepted == {"accepted": True}
