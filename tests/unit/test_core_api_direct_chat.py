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

CHAT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
USER_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
MODEL_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")


class _Chat:
    def __init__(self) -> None:
        self.generated = False

    def list_chats(self, *, limit: int = 50) -> tuple[ChatSummary, ...]:
        del limit
        return ()

    def create_chat(self) -> uuid.UUID:
        return CHAT_ID

    def load_chat(self, chat_id: uuid.UUID) -> ChatThread:
        assert chat_id == CHAT_ID
        messages: tuple[ChatMessage, ...] = ()
        if self.generated:
            messages = (
                ChatMessage(
                    message_id=uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
                    chat_id=CHAT_ID,
                    sequence_no=1,
                    message_type=MessageType.USER,
                    actor_id=USER_ID,
                    created_at_us=10,
                    revision_id=uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
                    content="hello from desktop",
                    content_format="text/plain",
                ),
                ChatMessage(
                    message_id=uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc"),
                    chat_id=CHAT_ID,
                    sequence_no=2,
                    message_type=MessageType.ASSISTANT,
                    actor_id=MODEL_ID,
                    created_at_us=11,
                    revision_id=uuid.UUID("dddddddd-dddd-dddd-dddd-dddddddddddd"),
                    content="hello from ATHENA",
                    content_format="text/plain",
                ),
            )
        return ChatThread(
            chat_id=CHAT_ID,
            started_at_us=1,
            ended_at_us=None,
            archive_mode="standard",
            lifecycle_state="active",
            messages=messages,
        )


class _DirectChat:
    def __init__(self, chat: _Chat) -> None:
        self.chat = chat
        self.calls: list[tuple[uuid.UUID, str, str | None]] = []

    def send_message(
        self,
        *,
        chat_id: uuid.UUID,
        content: str,
        requested_model_id: str | None = None,
    ) -> object:
        self.calls.append((chat_id, content, requested_model_id))
        self.chat.generated = True
        return object()


class _Provider:
    @property
    def provider_id(self) -> str:
        return "lm_studio"

    def health(self) -> ProviderHealth:
        return ProviderHealth(status=ProviderHealthStatus.READY)

    def discover_models(self) -> tuple[ModelInfo, ...]:
        return ()


def _facade() -> tuple[CoreApiFacade, _DirectChat]:
    chat = _Chat()
    direct = _DirectChat(chat)
    health = HealthService()
    health.mark_ok()
    facade = CoreApiFacade(
        health=health,
        chat=chat,  # type: ignore[arg-type]
        model_provider=_Provider(),
        direct_chat=direct,
    )
    return facade, direct


def test_facade_exposes_and_delegates_direct_chat_send() -> None:
    facade, direct = _facade()

    assert "chat.send.direct" in facade.capabilities().features

    thread = facade.send_chat_message(
        str(CHAT_ID),
        content="hello from desktop",
        requested_model_id="qwen-test",
    )

    assert direct.calls == [
        (CHAT_ID, "hello from desktop", "qwen-test"),
    ]
    assert [message.content for message in thread.messages] == [
        "hello from desktop",
        "hello from ATHENA",
    ]


async def _request(
    app: CoreApiAsgiApp,
    runtime: LocalApiRuntime,
    *,
    token: str,
    body: bytes,
) -> tuple[int, dict[str, Any]]:
    scope: dict[str, Any] = {
        "type": "http",
        "method": "POST",
        "path": f"/api/v1/chats/{CHAT_ID}/messages",
        "query_string": b"",
        "headers": [
            (b"authorization", f"Bearer {token}".encode("ascii")),
            (b"content-type", b"application/json"),
        ],
    }

    delivered = False

    async def receive() -> dict[str, Any]:
        nonlocal delivered
        if delivered:
            return {"type": "http.request", "body": b"", "more_body": False}
        delivered = True
        return {"type": "http.request", "body": body, "more_body": False}

    sent: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    await app(scope, receive, send)
    start, response = sent
    return int(start["status"]), json.loads(response["body"].decode("utf-8"))


def test_asgi_direct_chat_route_accepts_bounded_json(tmp_path) -> None:
    facade, direct = _facade()
    runtime = LocalApiRuntime(tmp_path / "api")
    runtime.publish(port=32123)
    token = runtime.token_path.read_text(encoding="utf-8").strip()
    app = CoreApiAsgiApp(facade=facade, runtime=runtime)

    body = json.dumps(
        {
            "content": "hello from desktop",
            "model_id": "qwen-test",
        }
    ).encode("utf-8")
    status, payload = asyncio.run(
        _request(app, runtime, token=token, body=body)
    )

    assert status == 200
    assert payload["messages"][-1]["content"] == "hello from ATHENA"
    assert len(direct.calls) == 1


def test_asgi_direct_chat_route_rejects_unknown_fields(tmp_path) -> None:
    facade, direct = _facade()
    runtime = LocalApiRuntime(tmp_path / "api")
    runtime.publish(port=32123)
    token = runtime.token_path.read_text(encoding="utf-8").strip()
    app = CoreApiAsgiApp(facade=facade, runtime=runtime)

    body = json.dumps(
        {
            "content": "hello from desktop",
            "unexpected": True,
        }
    ).encode("utf-8")
    status, payload = asyncio.run(
        _request(app, runtime, token=token, body=body)
    )

    assert status == 400
    assert payload["code"] == "invalid_request"
    assert direct.calls == []
