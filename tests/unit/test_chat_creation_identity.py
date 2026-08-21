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
from athena.chat.models import ChatThread
from athena.chat.repository import ChatRepository
from athena.chat.service import ChatService
from athena.model.domain import (
    ModelInfo,
    ProviderHealth,
    ProviderHealthStatus,
)
from athena.observability.health import HealthService
from athena.storage.database import SQLiteDatabase

CHAT_ID = uuid.UUID(
    "11111111-2222-4333-8444-555555555555"
)


def test_chat_service_explicit_creation_is_idempotent(
    tmp_path: Path,
) -> None:
    database = SQLiteDatabase(
        tmp_path / "athena.db"
    )
    database.start()

    try:
        service = ChatService(
            ChatRepository(
                database
            )
        )

        first = service.create_chat(
            chat_id=CHAT_ID
        )

        second = service.create_chat(
            chat_id=CHAT_ID
        )

        assert first == CHAT_ID
        assert second == CHAT_ID

        chat_count = database.connection.execute(
            """
            SELECT COUNT(*)
            FROM chats
            WHERE chat_id = ?
            """,
            (
                CHAT_ID.bytes,
            ),
        ).fetchone()[0]

        assert chat_count == 1

        thread = service.load_chat(
            CHAT_ID
        )

        assert thread.chat_id == CHAT_ID
        assert thread.messages == ()

    finally:
        database.stop()


class _Chat:
    def __init__(self) -> None:
        self.created: list[
            uuid.UUID | None
        ] = []
        self.chat_ids: set[
            uuid.UUID
        ] = set()

    def create_chat(
        self,
        *,
        chat_id: uuid.UUID | None = None,
    ) -> uuid.UUID:
        resolved = (
            chat_id
            if chat_id is not None
            else CHAT_ID
        )

        self.created.append(
            chat_id
        )

        self.chat_ids.add(
            resolved
        )

        return resolved

    def load_chat(
        self,
        chat_id: uuid.UUID,
    ) -> ChatThread:
        assert chat_id in self.chat_ids

        return ChatThread(
            chat_id=chat_id,
            started_at_us=1,
            ended_at_us=None,
            archive_mode="standard",
            lifecycle_state="active",
            messages=(),
        )


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
    _Chat,
]:
    health = HealthService()
    health.mark_ok()

    chat = _Chat()

    return (
        CoreApiFacade(
            health=health,
            chat=chat,  # type: ignore[arg-type]
            model_provider=_Provider(),
        ),
        chat,
    )


def test_facade_accepts_client_selected_chat_id() -> None:
    facade, chat = _facade()

    thread = facade.create_chat(
        str(
            CHAT_ID
        )
    )

    assert thread.chat_id == str(
        CHAT_ID
    )

    assert chat.created == [
        CHAT_ID
    ]


def test_serialized_surface_forwards_chat_id() -> None:
    facade, chat = _facade()

    surface = SerializedCoreApiSurface(
        facade,
        _InlineExecutor(),  # type: ignore[arg-type]
    )

    thread = surface.create_chat(
        str(
            CHAT_ID
        )
    )

    assert thread.chat_id == str(
        CHAT_ID
    )

    assert chat.created == [
        CHAT_ID
    ]


async def _put_chat(
    app: CoreApiAsgiApp,
    *,
    token: str,
) -> tuple[int, dict[str, Any]]:
    scope: dict[str, Any] = {
        "type": "http",
        "method": "PUT",
        "path": (
            "/api/v1/chats/"
            + str(
                CHAT_ID
            )
        ),
        "query_string": b"",
        "headers": [
            (
                b"authorization",
                (
                    "Bearer "
                    + token
                ).encode(
                    "ascii"
                ),
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
            "body": b"",
            "more_body": False,
        }

    sent: list[
        dict[str, Any]
    ] = []

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


def test_asgi_put_creates_requested_chat_id(
    tmp_path: Path,
) -> None:
    facade, chat = _facade()

    runtime = LocalApiRuntime(
        tmp_path / "api"
    )
    runtime.publish(
        port=32123
    )

    token = runtime.token_path.read_text(
        encoding="utf-8"
    ).strip()

    app = CoreApiAsgiApp(
        facade=facade,
        runtime=runtime,
    )

    status, payload = asyncio.run(
        _put_chat(
            app,
            token=token,
        )
    )

    assert status == 201
    assert payload["chat_id"] == str(
        CHAT_ID
    )
    assert chat.created == [
        CHAT_ID
    ]


class _Response:
    def __init__(
        self,
        payload: dict[str, Any],
    ) -> None:
        self.status = 201
        self._raw = json.dumps(
            payload
        ).encode(
            "utf-8"
        )

    def __enter__(
        self,
    ) -> "_Response":
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


def test_client_uses_put_for_requested_chat_id(
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

        assert timeout == 5.0
        assert request.get_method() == "PUT"

        assert request.full_url.endswith(
            "/api/v1/chats/"
            + str(
                CHAT_ID
            )
        )

        assert request.data is None

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
        runtime_root
    )

    result = client.create_chat(
        str(
            CHAT_ID
        ).upper()
    )

    assert result.chat_id == str(
        CHAT_ID
    )
    assert calls == 1


def test_client_rejects_invalid_requested_chat_id(
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "api"

    _bootstrap_client(
        runtime_root
    )

    client = CoreApiClient(
        runtime_root
    )

    with pytest.raises(
        ValueError,
        match="valid UUID",
    ):
        client.create_chat(
            "not-a-uuid"
        )
