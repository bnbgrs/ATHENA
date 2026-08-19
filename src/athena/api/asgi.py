"""Minimal versioned ASGI transport for the local ATHENA Core API."""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, cast
from urllib.parse import parse_qs

from athena.api.contracts import ApiContract, JsonValue
from athena.api.runtime import LocalApiRuntime
from athena.api.service import CoreApiFacade
from athena.chat.repository import ChatNotFoundError

AsgiMessage = dict[str, Any]
AsgiScope = dict[str, Any]
AsgiReceive = Callable[[], Awaitable[AsgiMessage]]
AsgiSend = Callable[[AsgiMessage], Awaitable[None]]

_JSON_HEADERS = ((b"content-type", b"application/json; charset=utf-8"),)


class CoreApiAsgiApp:
    """Small authenticated ASGI surface around :class:`CoreApiFacade`."""

    def __init__(
        self,
        *,
        facade: CoreApiFacade,
        runtime: LocalApiRuntime,
        allow_shutdown: bool = False,
    ) -> None:
        self._facade = facade
        self._runtime = runtime
        self._allow_shutdown = allow_shutdown

    async def __call__(
        self,
        scope: AsgiScope,
        receive: AsgiReceive,
        send: AsgiSend,
    ) -> None:
        if scope.get("type") != "http":
            await _send_problem(
                send,
                status=400,
                code="unsupported_transport",
                message="This ATHENA API endpoint accepts HTTP requests only.",
            )
            return

        request_id = str(uuid.uuid4())
        headers = _headers(scope)

        # Native desktop clients do not need browser Origin semantics. Reject
        # browser-originated requests by default rather than enabling wildcard
        # CORS or accidentally creating a localhost-CSRF surface.
        if "origin" in headers:
            await _send_problem(
                send,
                status=403,
                code="browser_origin_rejected",
                message="Browser-originated access is not enabled for this local ATHENA API.",
                request_id=request_id,
            )
            return

        token = _bearer_token(headers.get("authorization"))
        if token is None or not self._runtime.authenticate(token):
            await _send_problem(
                send,
                status=401,
                code="unauthorized",
                message="A valid local ATHENA session token is required.",
                request_id=request_id,
                extra_headers=((b"www-authenticate", b"Bearer"),),
            )
            return

        method = str(scope.get("method", "GET")).upper()
        path = str(scope.get("path", ""))

        try:
            if method == "GET" and path == "/api/v1/health":
                await _send_contract(send, self._facade.health(), request_id=request_id)
                return

            if method == "GET" and path == "/api/v1/capabilities":
                await _send_contract(send, self._facade.capabilities(), request_id=request_id)
                return

            if method == "GET" and path == "/api/v1/chats":
                limit = _positive_limit(scope, default=50, maximum=200)
                await _send_json(
                    send,
                    status=200,
                    payload={
                        "items": [item.to_dict() for item in self._facade.list_chats(limit=limit)]
                    },
                    request_id=request_id,
                )
                return

            if method == "POST" and path == "/api/v1/chats":
                await _consume_empty_body(receive)
                await _send_contract(
                    send,
                    self._facade.create_chat(),
                    status=201,
                    request_id=request_id,
                )
                return

            if method == "GET" and path.startswith("/api/v1/chats/"):
                chat_id = path.removeprefix("/api/v1/chats/")
                if not chat_id or "/" in chat_id:
                    raise ValueError("Invalid chat resource path.")
                await _send_contract(
                    send,
                    self._facade.load_chat(chat_id),
                    request_id=request_id,
                )
                return

            if method == "GET" and path == "/api/v1/models/health":
                await _send_contract(
                    send,
                    self._facade.provider_health(),
                    request_id=request_id,
                )
                return

            if method == "GET" and path == "/api/v1/models":
                await _send_json(
                    send,
                    status=200,
                    payload={
                        "items": [item.to_dict() for item in self._facade.list_models()]
                    },
                    request_id=request_id,
                )
                return

            if method == "POST" and path == "/api/v1/system/shutdown":
                await _consume_empty_body(receive)
                if not self._allow_shutdown:
                    await _send_problem(
                        send,
                        status=409,
                        code="shutdown_unavailable",
                        message="ATHENA Core shutdown is unavailable in this process.",
                        request_id=request_id,
                    )
                    return
                await _send_json(
                    send,
                    status=202,
                    payload={"accepted": True},
                    request_id=request_id,
                )
                return
        except (ValueError, TypeError) as exc:
            await _send_problem(
                send,
                status=400,
                code="invalid_request",
                message=str(exc),
                request_id=request_id,
            )
            return
        except ChatNotFoundError:
            await _send_problem(
                send,
                status=404,
                code="chat_not_found",
                message="The requested chat does not exist.",
                request_id=request_id,
            )
            return
        except Exception:
            # Client responses must never expose stack traces or provider/DB
            # implementation details. Server-side logging is added with the
            # concrete CoreApiServer lifecycle wrapper.
            await _send_problem(
                send,
                status=500,
                code="internal_error",
                message="ATHENA could not complete the request.",
                request_id=request_id,
                retryable=False,
            )
            return

        if _known_path(path):
            await _send_problem(
                send,
                status=405,
                code="method_not_allowed",
                message="The requested ATHENA API resource does not support this method.",
                request_id=request_id,
            )
            return

        await _send_problem(
            send,
            status=404,
            code="not_found",
            message="The requested ATHENA API resource does not exist.",
            request_id=request_id,
        )


def _known_path(path: str) -> bool:
    if path in {
        "/api/v1/health",
        "/api/v1/capabilities",
        "/api/v1/chats",
        "/api/v1/models",
        "/api/v1/models/health",
        "/api/v1/system/shutdown",
    }:
        return True
    if path.startswith("/api/v1/chats/"):
        chat_id = path.removeprefix("/api/v1/chats/")
        return bool(chat_id) and "/" not in chat_id
    return False



def _headers(scope: AsgiScope) -> dict[str, str]:
    raw_headers = cast(list[tuple[bytes, bytes]], scope.get("headers", []))
    result: dict[str, str] = {}
    for raw_name, raw_value in raw_headers:
        name = raw_name.decode("latin-1").lower()
        value = raw_value.decode("latin-1")
        result[name] = value
    return result


def _bearer_token(value: str | None) -> str | None:
    if value is None:
        return None
    scheme, separator, token = value.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token:
        return None
    return token


def _positive_limit(scope: AsgiScope, *, default: int, maximum: int) -> int:
    raw_query = cast(bytes, scope.get("query_string", b""))
    if not raw_query:
        return default
    values = parse_qs(raw_query.decode("ascii"), keep_blank_values=True)
    raw_limit = values.get("limit")
    if raw_limit is None:
        return default
    if len(raw_limit) != 1:
        raise ValueError("Query parameter 'limit' must occur once.")
    try:
        limit = int(raw_limit[0])
    except ValueError as exc:
        raise ValueError("Query parameter 'limit' must be an integer.") from exc
    if not 1 <= limit <= maximum:
        raise ValueError(f"Query parameter 'limit' must be between 1 and {maximum}.")
    return limit


async def _consume_empty_body(receive: AsgiReceive) -> None:
    message = await receive()
    if message.get("type") != "http.request":
        raise ValueError("Invalid HTTP request body event.")
    body = cast(bytes, message.get("body", b""))
    if body:
        raise ValueError("This endpoint does not accept a request body.")
    if bool(message.get("more_body", False)):
        raise ValueError("This endpoint does not accept a streaming request body.")


async def _send_contract(
    send: AsgiSend,
    contract: ApiContract,
    *,
    status: int = 200,
    request_id: str,
) -> None:
    await _send_json(
        send,
        status=status,
        payload=contract.to_dict(),
        request_id=request_id,
    )


async def _send_problem(
    send: AsgiSend,
    *,
    status: int,
    code: str,
    message: str,
    request_id: str | None = None,
    retryable: bool = False,
    extra_headers: tuple[tuple[bytes, bytes], ...] = (),
) -> None:
    resolved_request_id = request_id or str(uuid.uuid4())
    await _send_json(
        send,
        status=status,
        payload={
            "code": code,
            "message": message,
            "request_id": resolved_request_id,
            "retryable": retryable,
            "details": None,
        },
        request_id=resolved_request_id,
        extra_headers=extra_headers,
    )


async def _send_json(
    send: AsgiSend,
    *,
    status: int,
    payload: dict[str, JsonValue],
    request_id: str,
    extra_headers: tuple[tuple[bytes, bytes], ...] = (),
) -> None:
    body = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    headers = _JSON_HEADERS + (
        (b"content-length", str(len(body)).encode("ascii")),
        (b"x-request-id", request_id.encode("ascii")),
    ) + extra_headers
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": list(headers),
        }
    )
    await send(
        {
            "type": "http.response.body",
            "body": body,
            "more_body": False,
        }
    )
