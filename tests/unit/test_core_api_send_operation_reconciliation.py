from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

import pytest

from athena.api import client as client_module
from athena.api.asgi import CoreApiAsgiApp
from athena.api.client import CoreApiClient
from athena.api.executor import SerializedCoreApiSurface
from athena.api.runtime import LocalApiRuntime
from athena.api.service import CoreApiFacade
from athena.chat.models import ChatMessage, ChatThread, MessageType
from athena.chat.send_identity import (
    SendOperationState,
    SendOperationStateError,
    SendOperationStatus,
    assistant_message_id_for_operation,
)
from athena.model.domain import (
    ModelInfo,
    ProviderHealth,
    ProviderHealthStatus,
)
from athena.observability.health import HealthService

CHAT_ID = uuid.UUID(
    "11111111-1111-1111-1111-111111111111"
)
USER_ID = uuid.UUID(
    "22222222-2222-4222-8222-222222222222"
)
MODEL_ID = uuid.UUID(
    "33333333-3333-4333-8333-333333333333"
)
OPERATION_ID = uuid.UUID(
    "44444444-4444-4444-8444-444444444444"
)


class _Chat:
    def __init__(self) -> None:
        self.generated = False

    def load_chat(
        self,
        chat_id: uuid.UUID,
    ) -> ChatThread:
        assert chat_id == CHAT_ID

        messages: tuple[ChatMessage, ...] = ()

        if self.generated:
            messages = (
                ChatMessage(
                    message_id=OPERATION_ID,
                    chat_id=CHAT_ID,
                    sequence_no=1,
                    message_type=MessageType.USER,
                    actor_id=USER_ID,
                    created_at_us=10,
                    revision_id=uuid.UUID(
                        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
                    ),
                    content="hello",
                    content_format="text/plain",
                ),
                ChatMessage(
                    message_id=(
                        assistant_message_id_for_operation(
                            OPERATION_ID
                        )
                    ),
                    chat_id=CHAT_ID,
                    sequence_no=2,
                    message_type=MessageType.ASSISTANT,
                    actor_id=MODEL_ID,
                    created_at_us=11,
                    revision_id=uuid.UUID(
                        "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
                    ),
                    content="answer",
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


class _Direct:
    def __init__(
        self,
        chat: _Chat,
    ) -> None:
        self.chat = chat
        self.calls: list[uuid.UUID | None] = []
        self.state: SendOperationState | None = None

    def send_message(
        self,
        *,
        chat_id: uuid.UUID,
        content: str,
        requested_model_id: str | None = None,
        operation_id: uuid.UUID | None = None,
        effective_context_limit: int | None = None,
        output_reserve: int = 2048,
        temperature: float | None = None,
        reasoning_mode: str | None = "off",
    ) -> object:
        del (
            requested_model_id,
            effective_context_limit,
            output_reserve,
            temperature,
            reasoning_mode,
        )

        assert chat_id == CHAT_ID
        assert content == "hello"

        self.calls.append(
            operation_id
        )

        if self.state is not None:
            assert operation_id is not None

            if self.state is SendOperationState.COMPLETE:
                self.chat.generated = True

            raise SendOperationStateError(
                SendOperationStatus(
                    chat_id=chat_id,
                    operation_id=operation_id,
                    user_message_id=operation_id,
                    assistant_message_id=(
                        assistant_message_id_for_operation(
                            operation_id
                        )
                    ),
                    state=self.state,
                )
            )

        self.chat.generated = True
        return object()


class _Provider:
    @property
    def provider_id(self) -> str:
        return "lm_studio"

    def health(self) -> ProviderHealth:
        return ProviderHealth(
            status=ProviderHealthStatus.READY
        )

    def discover_models(
        self,
    ) -> tuple[ModelInfo, ...]:
        return ()


class _InlineExecutor:
    def call(
        self,
        callback: Any,
    ) -> Any:
        return callback()


def _facade() -> tuple[
    CoreApiFacade,
    _Direct,
]:
    chat = _Chat()
    direct = _Direct(chat)
    health = HealthService()
    health.mark_ok()

    return (
        CoreApiFacade(
            health=health,
            chat=chat,  # type: ignore[arg-type]
            model_provider=_Provider(),
            direct_chat=direct,
        ),
        direct,
    )


def test_facade_reconciles_complete_operation() -> None:
    facade, direct = _facade()
    direct.state = SendOperationState.COMPLETE

    thread = facade.send_chat_message(
        str(CHAT_ID),
        content="hello",
        operation_id=str(OPERATION_ID),
    )

    assert direct.calls == [
        OPERATION_ID
    ]

    assert [
        message.message_id
        for message in thread.messages
    ] == [
        str(OPERATION_ID),
        str(
            assistant_message_id_for_operation(
                OPERATION_ID
            )
        ),
    ]


def test_facade_keeps_incomplete_fail_closed() -> None:
    facade, direct = _facade()
    direct.state = SendOperationState.INCOMPLETE

    with pytest.raises(
        SendOperationStateError
    ) as raised:
        facade.send_chat_message(
            str(CHAT_ID),
            content="hello",
            operation_id=str(OPERATION_ID),
        )

    assert (
        raised.value.status.state
        is SendOperationState.INCOMPLETE
    )

    assert direct.calls == [
        OPERATION_ID
    ]


def test_serialized_surface_forwards_operation_id() -> None:
    facade, direct = _facade()

    surface = SerializedCoreApiSurface(
        facade,
        _InlineExecutor(),  # type: ignore[arg-type]
    )

    surface.send_chat_message(
        str(CHAT_ID),
        content="hello",
        operation_id=str(OPERATION_ID),
    )

    assert direct.calls == [
        OPERATION_ID
    ]


async def _asgi_request(
    app: CoreApiAsgiApp,
    *,
    token: str,
    body: dict[str, Any],
) -> tuple[int, dict[str, Any]]:
    scope: dict[str, Any] = {
        "type": "http",
        "method": "POST",
        "path": (
            f"/api/v1/chats/"
            f"{CHAT_ID}/messages"
        ),
        "query_string": b"",
        "headers": [
            (
                b"authorization",
                f"Bearer {token}".encode(
                    "ascii"
                ),
            ),
            (
                b"content-type",
                b"application/json",
            ),
        ],
    }

    delivered = False

    async def receive() -> dict[str, Any]:
        nonlocal delivered

        if delivered:
            return {
                "type": "http.request",
                "body": b"",
                "more_body": False,
            }

        delivered = True

        return {
            "type": "http.request",
            "body": json.dumps(
                body
            ).encode(
                "utf-8"
            ),
            "more_body": False,
        }

    sent: list[dict[str, Any]] = []

    async def send(
        message: dict[str, Any],
    ) -> None:
        sent.append(
            message
        )

    await app(
        scope,
        receive,
        send,
    )

    start, response = sent

    return (
        int(
            start["status"]
        ),
        json.loads(
            response[
                "body"
            ].decode(
                "utf-8"
            )
        ),
    )


def _asgi_runtime(
    tmp_path: Path,
) -> tuple[
    CoreApiAsgiApp,
    str,
    _Direct,
]:
    facade, direct = _facade()

    runtime = LocalApiRuntime(
        tmp_path / "api"
    )
    runtime.publish(
        port=32123
    )

    token = (
        runtime.token_path
        .read_text(
            encoding="utf-8"
        )
        .strip()
    )

    return (
        CoreApiAsgiApp(
            facade=facade,
            runtime=runtime,
        ),
        token,
        direct,
    )


def test_asgi_forwards_operation_id(
    tmp_path: Path,
) -> None:
    app, token, direct = _asgi_runtime(
        tmp_path
    )

    status, payload = asyncio.run(
        _asgi_request(
            app,
            token=token,
            body={
                "content": "hello",
                "operation_id": str(
                    OPERATION_ID
                ),
            },
        )
    )

    assert status == 200
    assert payload["messages"][-1]["content"] == "answer"
    assert direct.calls == [
        OPERATION_ID
    ]


@pytest.mark.parametrize(
    ("state", "expected_code"),
    (
        (
            SendOperationState.INCOMPLETE,
            "send_operation_incomplete",
        ),
        (
            SendOperationState.CONFLICT,
            "send_operation_conflict",
        ),
    ),
)
def test_asgi_maps_blocked_operation_state(
    tmp_path: Path,
    state: SendOperationState,
    expected_code: str,
) -> None:
    app, token, direct = _asgi_runtime(
        tmp_path
    )

    direct.state = state

    status, payload = asyncio.run(
        _asgi_request(
            app,
            token=token,
            body={
                "content": "hello",
                "operation_id": str(
                    OPERATION_ID
                ),
            },
        )
    )

    assert status == 409
    assert payload["code"] == expected_code
    assert payload["retryable"] is False
    assert direct.calls == [
        OPERATION_ID
    ]


def test_asgi_rejects_invalid_operation_id(
    tmp_path: Path,
) -> None:
    app, token, direct = _asgi_runtime(
        tmp_path
    )

    status, payload = asyncio.run(
        _asgi_request(
            app,
            token=token,
            body={
                "content": "hello",
                "operation_id": "not-a-uuid",
            },
        )
    )

    assert status == 400
    assert payload["code"] == "invalid_request"
    assert direct.calls == []


class _Response:
    def __init__(
        self,
        payload: dict[str, Any],
    ) -> None:
        self.status = 200
        self._raw = json.dumps(
            payload
        ).encode(
            "utf-8"
        )

    def __enter__(self) -> "_Response":
        return self

    def __exit__(
        self,
        *args: object,
    ) -> bool:
        del args
        return False

    def read(self) -> bytes:
        return self._raw


def _bootstrap_client(
    runtime_root: Path,
) -> None:
    runtime_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    token_path = (
        runtime_root
        / "core-api.token"
    )

    token_path.write_text(
        "token-one\n",
        encoding="ascii",
    )

    (
        runtime_root
        / "core-api.json"
    ).write_text(
        json.dumps(
            {
                "api_version": "v1",
                "host": "127.0.0.1",
                "port": 32123,
                "token_path": str(
                    token_path
                ),
                "process_id": 1234,
            }
        ),
        encoding="utf-8",
    )


def test_client_posts_canonical_operation_id_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_root = tmp_path / "api"
    _bootstrap_client(
        runtime_root
    )

    calls = 0

    def fake_urlopen(
        request: Any,
        timeout: float,
    ) -> _Response:
        nonlocal calls
        calls += 1

        assert timeout == 45.0

        payload = json.loads(
            request.data.decode(
                "utf-8"
            )
        )

        assert payload == {
            "content": "hello",
            "operation_id": str(
                OPERATION_ID
            ),
        }

        return _Response(
            {
                "chat_id": str(
                    CHAT_ID
                ),
                "started_at_us": 1,
                "ended_at_us": None,
                "archive_mode": "standard",
                "lifecycle_state": "active",
                "messages": [],
            }
        )

    monkeypatch.setattr(
        client_module,
        "urlopen",
        fake_urlopen,
    )

    client = CoreApiClient(
        runtime_root,
        timeout_seconds=2.0,
        generation_timeout_seconds=45.0,
    )

    result = client.send_chat_message(
        str(CHAT_ID),
        content="hello",
        operation_id=str(
            OPERATION_ID
        ).upper(),
    )

    assert result.chat_id == str(
        CHAT_ID
    )
    assert calls == 1


def test_client_rejects_invalid_operation_id(
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "api"
    _bootstrap_client(
        runtime_root
    )

    client = CoreApiClient(
        runtime_root,
    )

    with pytest.raises(
        ValueError,
        match="operation_id",
    ):
        client.send_chat_message(
            str(CHAT_ID),
            content="hello",
            operation_id="not-a-uuid",
        )
