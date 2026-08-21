"""Minimal versioned ASGI transport for the local ATHENA Core API."""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, cast
from urllib.parse import parse_qs

from athena.api.contracts import ApiContract, JsonValue
from athena.api.ports import CoreApiSurface
from athena.api.runtime import LocalApiRuntime
from athena.api.service import (
    ChatMessageNotFoundError,
    ChatMessageRevisionMismatchError,
    KnowledgeReviewConflictError,
    KnowledgeReviewNotFoundError,
)
from athena.chat.repository import ChatNotFoundError
from athena.chat.send_identity import (
    SendOperationState,
    SendOperationStateError,
)
from athena.lifecycle.service import (
    LifecycleDeletionAlreadyDeletedError,
    LifecycleDeletionNotFoundError,
    LifecycleDeletionPreviewStaleError,
    LifecycleDeletionUnsupportedError,
)
from athena.model.adapters.lm_studio import ProviderOutputLimitError

AsgiMessage = dict[str, Any]
AsgiScope = dict[str, Any]
AsgiReceive = Callable[[], Awaitable[AsgiMessage]]
AsgiSend = Callable[[AsgiMessage], Awaitable[None]]

_JSON_HEADERS = ((b"content-type", b"application/json; charset=utf-8"),)
_MAX_JSON_BODY_BYTES = 64 * 1024


class CoreApiAsgiApp:
    """Small authenticated ASGI surface around :class:`CoreApiFacade`."""

    def __init__(
        self,
        *,
        facade: CoreApiSurface,
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
                limit = _positive_limit(
                    scope,
                    default=50,
                    maximum=200,
                )
                offset = _nonnegative_offset(
                    scope,
                    default=0,
                )
                await _send_json(
                    send,
                    status=200,
                    payload={
                        "items": [
                            item.to_dict()
                            for item in self._facade.list_chats(
                                limit=limit,
                                offset=offset,
                            )
                        ]
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

            if (
                method == "PUT"
                and path.startswith("/api/v1/chats/")
            ):
                chat_id = path.removeprefix(
                    "/api/v1/chats/"
                )

                if not chat_id or "/" in chat_id:
                    raise ValueError(
                        "Invalid chat creation resource path."
                    )

                await _consume_empty_body(
                    receive
                )

                await _send_contract(
                    send,
                    self._facade.create_chat(
                        chat_id
                    ),
                    status=201,
                    request_id=request_id,
                )
                return

            remember_resource = _message_action_resource(path, action="remember")
            if method == "POST" and remember_resource is not None:
                chat_id, message_id = remember_resource
                payload = await _read_json_object(receive)
                unknown = set(payload) - {"revision_id"}
                if unknown:
                    raise ValueError(
                        "Remember request contains unsupported fields."
                    )
                revision_id = payload.get("revision_id")
                if not isinstance(revision_id, str) or not revision_id.strip():
                    raise ValueError(
                        "Remember revision_id must be a non-empty string."
                    )
                await _send_contract(
                    send,
                    self._facade.remember_chat_message(
                        chat_id,
                        message_id,
                        revision_id=revision_id,
                    ),
                    status=201,
                    request_id=request_id,
                )
                return

            extraction_resource = _message_action_resource(
                path,
                action="knowledge-extraction",
            )
            if method == "POST" and extraction_resource is not None:
                chat_id, message_id = extraction_resource
                payload = await _read_json_object(receive)
                unknown = set(payload) - {
                    "revision_id",
                    "model_id",
                    "effective_context_limit",
                    "max_output_tokens",
                }
                if unknown:
                    raise ValueError(
                        "Knowledge extraction request contains unsupported fields."
                    )
                revision_id = payload.get("revision_id")
                if not isinstance(revision_id, str) or not revision_id.strip():
                    raise ValueError(
                        "Knowledge extraction revision_id must be a non-empty string."
                    )
                model_id = payload.get("model_id")
                if model_id is not None and (
                    not isinstance(model_id, str) or not model_id.strip()
                ):
                    raise ValueError(
                        "Knowledge extraction model_id must be a non-empty string or null."
                    )
                effective_context_limit = payload.get("effective_context_limit")
                if effective_context_limit is not None and (
                    isinstance(effective_context_limit, bool)
                    or not isinstance(effective_context_limit, int)
                    or effective_context_limit < 1
                ):
                    raise ValueError(
                        "Knowledge extraction effective_context_limit must be positive or null."
                    )
                max_output_tokens = payload.get("max_output_tokens")
                if max_output_tokens is not None and (
                    isinstance(max_output_tokens, bool)
                    or not isinstance(max_output_tokens, int)
                    or max_output_tokens < 1
                ):
                    raise ValueError(
                        "Knowledge extraction max_output_tokens must be positive or null."
                    )
                await _send_contract(
                    send,
                    self._facade.extract_chat_message_knowledge(
                        chat_id,
                        message_id,
                        revision_id=revision_id,
                        requested_model_id=model_id,
                        effective_context_limit=effective_context_limit,
                        max_output_tokens=max_output_tokens,
                    ),
                    status=201,
                    request_id=request_id,
                )
                return

            if (
                method == "POST"
                and path.startswith("/api/v1/chats/")
                and path.endswith("/messages/unified-local")
            ):
                chat_id = path.removeprefix(
                    "/api/v1/chats/"
                ).removesuffix(
                    "/messages/unified-local"
                )
                if not chat_id or "/" in chat_id:
                    raise ValueError(
                        "Invalid Unified Local chat message resource path."
                    )

                payload = await _read_json_object(receive)
                unknown = set(payload) - {
                    "content",
                    "model_id",
                    "embedding_model_id",
                    "effective_context_limit",
                    "max_output_tokens",
                    "temperature",
                    "thinking_enabled",
                }
                if unknown:
                    raise ValueError(
                        "Unified Local chat request contains unsupported fields."
                    )

                content = payload.get("content")
                if not isinstance(content, str) or not content.strip():
                    raise ValueError(
                        "Chat message content must contain non-whitespace text."
                    )

                model_id = payload.get("model_id")
                if model_id is not None and (
                    not isinstance(model_id, str)
                    or not model_id.strip()
                ):
                    raise ValueError(
                        "Chat model_id must be a non-empty string or null."
                    )

                embedding_model_id = payload.get(
                    "embedding_model_id"
                )
                if embedding_model_id is not None and (
                    not isinstance(embedding_model_id, str)
                    or not embedding_model_id.strip()
                ):
                    raise ValueError(
                        "Chat embedding_model_id must be a "
                        "non-empty string or null."
                    )

                effective_context_limit = payload.get(
                    "effective_context_limit"
                )
                if effective_context_limit is not None and (
                    isinstance(effective_context_limit, bool)
                    or not isinstance(effective_context_limit, int)
                    or effective_context_limit < 1
                ):
                    raise ValueError(
                        "Chat effective_context_limit must be a positive integer or null."
                    )

                max_output_tokens = payload.get("max_output_tokens")
                if max_output_tokens is not None and (
                    isinstance(max_output_tokens, bool)
                    or not isinstance(max_output_tokens, int)
                    or max_output_tokens < 1
                ):
                    raise ValueError(
                        "Chat max_output_tokens must be a positive integer or null."
                    )
                temperature_value = payload.get("temperature")
                if temperature_value is not None and (
                    isinstance(temperature_value, bool)
                    or not isinstance(temperature_value, (int, float))
                    or not 0.0 <= float(temperature_value) <= 2.0
                ):
                    raise ValueError(
                        "Chat temperature must be between 0.0 and 2.0 or null."
                    )
                temperature = (
                    None if temperature_value is None else float(temperature_value)
                )
                thinking_enabled = payload.get("thinking_enabled")
                if thinking_enabled is not None and not isinstance(
                    thinking_enabled, bool
                ):
                    raise ValueError(
                        "Chat thinking_enabled must be boolean or null."
                    )
                await _send_contract(
                    send,
                    self._facade.send_unified_local_chat_message(
                        chat_id,
                        content=content,
                        requested_model_id=model_id,
                        requested_embedding_model_id=(
                            embedding_model_id
                        ),
                        effective_context_limit=effective_context_limit,
                        max_output_tokens=max_output_tokens,
                        temperature=temperature,
                        thinking_enabled=thinking_enabled,
                    ),
                    request_id=request_id,
                )
                return

            if (
                method == "POST"
                and path.startswith("/api/v1/chats/")
                and path.endswith("/messages")
            ):
                chat_id = path.removeprefix("/api/v1/chats/").removesuffix(
                    "/messages"
                )
                if not chat_id or "/" in chat_id:
                    raise ValueError("Invalid chat message resource path.")
                payload = await _read_json_object(receive)
                unknown = set(payload) - {
                    "content",
                    "model_id",
                    "operation_id",
                    "effective_context_limit",
                    "max_output_tokens",
                    "temperature",
                    "thinking_enabled",
                }
                if unknown:
                    raise ValueError(
                        "Chat message request contains unsupported fields."
                    )
                content = payload.get("content")
                if not isinstance(content, str) or not content.strip():
                    raise ValueError(
                        "Chat message content must contain non-whitespace text."
                    )
                model_id = payload.get("model_id")
                if model_id is not None and (
                    not isinstance(model_id, str) or not model_id.strip()
                ):
                    raise ValueError(
                        "Chat model_id must be a non-empty string or null."
                    )
                operation_id = payload.get("operation_id")
                if operation_id is not None:
                    if (
                        not isinstance(operation_id, str)
                        or not operation_id.strip()
                    ):
                        raise ValueError(
                            "Chat operation_id must be a "
                            "non-empty UUID string or null."
                        )
                    try:
                        uuid.UUID(operation_id)
                    except ValueError as exc:
                        raise ValueError(
                            "Chat operation_id must be a "
                            "valid UUID string or null."
                        ) from exc

                effective_context_limit = payload.get(
                    "effective_context_limit"
                )
                if effective_context_limit is not None and (
                    isinstance(effective_context_limit, bool)
                    or not isinstance(effective_context_limit, int)
                    or effective_context_limit < 1
                ):
                    raise ValueError(
                        "Chat effective_context_limit must be a positive integer or null."
                    )
                max_output_tokens = payload.get("max_output_tokens")
                if max_output_tokens is not None and (
                    isinstance(max_output_tokens, bool)
                    or not isinstance(max_output_tokens, int)
                    or max_output_tokens < 1
                ):
                    raise ValueError(
                        "Chat max_output_tokens must be a positive integer or null."
                    )
                temperature_value = payload.get("temperature")
                if temperature_value is not None and (
                    isinstance(temperature_value, bool)
                    or not isinstance(temperature_value, (int, float))
                    or not 0.0 <= float(temperature_value) <= 2.0
                ):
                    raise ValueError(
                        "Chat temperature must be between 0.0 and 2.0 or null."
                    )
                temperature = (
                    None if temperature_value is None else float(temperature_value)
                )
                thinking_enabled = payload.get("thinking_enabled")
                if thinking_enabled is not None and not isinstance(
                    thinking_enabled, bool
                ):
                    raise ValueError(
                        "Chat thinking_enabled must be boolean or null."
                    )
                await _send_contract(
                    send,
                    self._facade.send_chat_message(
                        chat_id,
                        content=content,
                        requested_model_id=model_id,
                        operation_id=operation_id,
                        effective_context_limit=effective_context_limit,
                        max_output_tokens=max_output_tokens,
                        temperature=temperature,
                        thinking_enabled=thinking_enabled,
                    ),
                    request_id=request_id,
                )
                return

            if (
                method == "GET"
                and path.startswith("/api/v1/chats/")
                and path.endswith("/deletion-preview")
            ):
                chat_id = path.removeprefix(
                    "/api/v1/chats/"
                ).removesuffix("/deletion-preview")
                if not chat_id or "/" in chat_id:
                    raise ValueError("Invalid chat deletion-preview resource path.")
                await _send_contract(
                    send,
                    self._facade.preview_chat_deletion(chat_id),
                    request_id=request_id,
                )
                return

            if (
                method == "DELETE"
                and path.startswith("/api/v1/chats/")
            ):
                chat_id = path.removeprefix("/api/v1/chats/")
                if not chat_id or "/" in chat_id:
                    raise ValueError("Invalid chat deletion resource path.")
                payload = await _read_json_object(receive)
                unknown = set(payload) - {"preview_digest"}
                if unknown:
                    raise ValueError(
                        "Chat deletion request contains unsupported fields."
                    )
                preview_digest = payload.get("preview_digest")
                if (
                    not isinstance(preview_digest, str)
                    or len(preview_digest) != 64
                ):
                    raise ValueError(
                        "Chat deletion preview_digest must be a 64-character SHA-256 hex digest."
                    )
                try:
                    digest_bytes = bytes.fromhex(preview_digest)
                except ValueError as exc:
                    raise ValueError(
                        "Chat deletion preview_digest must be valid hexadecimal."
                    ) from exc
                if len(digest_bytes) != 32:
                    raise ValueError(
                        "Chat deletion preview_digest must be a SHA-256 digest."
                    )
                await _send_contract(
                    send,
                    self._facade.delete_chat(
                        chat_id,
                        preview_digest=preview_digest,
                    ),
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

            review_run_id = _single_resource_id(
                path,
                prefix="/api/v1/knowledge-extractions/",
                suffix="/review",
            )
            if method == "POST" and review_run_id is not None:
                await _consume_empty_body(receive)
                await _send_contract(
                    send,
                    self._facade.prepare_knowledge_review(review_run_id),
                    request_id=request_id,
                )
                return

            merge_decision_id = _single_resource_id(
                path,
                prefix="/api/v1/knowledge-merge-reviews/",
                suffix="/decision",
            )
            if method == "POST" and merge_decision_id is not None:
                payload = await _read_json_object(receive)
                unknown = set(payload) - {"decision"}
                if unknown:
                    raise ValueError(
                        "Knowledge merge decision contains unsupported fields."
                    )
                decision = payload.get("decision")
                if not isinstance(decision, str):
                    raise ValueError(
                        "Knowledge merge decision must be a string."
                    )
                await _send_contract(
                    send,
                    self._facade.resolve_knowledge_merge_review(
                        merge_decision_id,
                        decision=decision,
                    ),
                    request_id=request_id,
                )
                return

            merge_review_id = _single_resource_id(
                path,
                prefix="/api/v1/knowledge-merge-reviews/",
            )
            if method == "GET" and merge_review_id is not None:
                await _send_contract(
                    send,
                    self._facade.load_knowledge_merge_review(merge_review_id),
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
        except ChatMessageNotFoundError:
            await _send_problem(
                send,
                status=404,
                code="chat_message_not_found",
                message="The requested chat message does not exist in this chat.",
                request_id=request_id,
            )
            return
        except ChatMessageRevisionMismatchError:
            await _send_problem(
                send,
                status=409,
                code="chat_message_revision_stale",
                message="The requested chat message revision is stale.",
                request_id=request_id,
                retryable=False,
            )
            return
        except KnowledgeReviewNotFoundError:
            await _send_problem(
                send,
                status=404,
                code="knowledge_review_not_found",
                message="The requested Knowledge review resource does not exist.",
                request_id=request_id,
            )
            return
        except KnowledgeReviewConflictError:
            await _send_problem(
                send,
                status=409,
                code="knowledge_review_conflict",
                message="Knowledge review state changed or requires another decision.",
                request_id=request_id,
                retryable=False,
            )
            return
        except SendOperationStateError as exc:
            if exc.status.state is SendOperationState.INCOMPLETE:
                code = "send_operation_incomplete"
                message = (
                    "The send operation already has a persisted "
                    "user turn but no completed assistant turn. "
                    "Automatic re-execution is blocked."
                )
            elif exc.status.state is SendOperationState.CONFLICT:
                code = "send_operation_conflict"
                message = (
                    "The send operation identity conflicts with "
                    "the requested chat or content."
                )
            else:
                code = "send_operation_state_conflict"
                message = (
                    "The send operation cannot be executed from "
                    "its current durable state."
                )

            await _send_problem(
                send,
                status=409,
                code=code,
                message=message,
                request_id=request_id,
                retryable=False,
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
        except ProviderOutputLimitError:
            await _send_problem(
                send,
                status=409,
                code="output_limit_reached",
                message=(
                    "The model reached the configured maximum output tokens. "
                    "The incomplete assistant response was not persisted."
                ),
                request_id=request_id,
                retryable=False,
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
        except (
            LifecycleDeletionNotFoundError,
            LifecycleDeletionAlreadyDeletedError,
        ):
            await _send_problem(
                send,
                status=404,
                code="chat_not_found",
                message="The requested chat does not exist.",
                request_id=request_id,
            )
            return
        except LifecycleDeletionPreviewStaleError:
            await _send_problem(
                send,
                status=409,
                code="deletion_preview_stale",
                message="Chat dependencies changed; review deletion again.",
                request_id=request_id,
            )
            return
        except LifecycleDeletionUnsupportedError:
            await _send_problem(
                send,
                status=409,
                code="deletion_unsupported",
                message="This chat cannot be deleted through the current lifecycle path.",
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
    if (
        path.startswith("/api/v1/chats/")
        and path.endswith("/deletion-preview")
    ):
        chat_id = path.removeprefix(
            "/api/v1/chats/"
        ).removesuffix("/deletion-preview")
        return bool(chat_id) and "/" not in chat_id
    if (
        path.startswith("/api/v1/chats/")
        and path.endswith("/messages/unified-local")
    ):
        chat_id = path.removeprefix(
            "/api/v1/chats/"
        ).removesuffix(
            "/messages/unified-local"
        )
        return bool(chat_id) and "/" not in chat_id
    if _message_action_resource(path, action="remember") is not None:
        return True
    if _message_action_resource(path, action="knowledge-extraction") is not None:
        return True
    if path.startswith("/api/v1/chats/") and path.endswith("/messages"):
        chat_id = path.removeprefix("/api/v1/chats/").removesuffix(
            "/messages"
        )
        return bool(chat_id) and "/" not in chat_id
    if _single_resource_id(
        path,
        prefix="/api/v1/knowledge-extractions/",
        suffix="/review",
    ) is not None:
        return True
    if _single_resource_id(
        path,
        prefix="/api/v1/knowledge-merge-reviews/",
        suffix="/decision",
    ) is not None:
        return True
    if _single_resource_id(
        path,
        prefix="/api/v1/knowledge-merge-reviews/",
    ) is not None:
        return True
    if path.startswith("/api/v1/chats/"):
        chat_id = path.removeprefix("/api/v1/chats/")
        return bool(chat_id) and "/" not in chat_id
    return False



def _message_action_resource(
    path: str,
    *,
    action: str,
) -> tuple[str, str] | None:
    prefix = "/api/v1/chats/"
    suffix = f"/{action}"
    if not path.startswith(prefix) or not path.endswith(suffix):
        return None
    middle = path[len(prefix) : -len(suffix)]
    chat_id, separator, message_id = middle.partition("/messages/")
    if (
        separator != "/messages/"
        or not chat_id
        or not message_id
        or "/" in chat_id
        or "/" in message_id
    ):
        return None
    return chat_id, message_id


def _single_resource_id(
    path: str,
    *,
    prefix: str,
    suffix: str = "",
) -> str | None:
    if not path.startswith(prefix):
        return None
    if suffix and not path.endswith(suffix):
        return None
    end = -len(suffix) if suffix else None
    resource_id = path[len(prefix) : end]
    if not resource_id or "/" in resource_id:
        return None
    return resource_id


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


def _nonnegative_offset(
    scope: AsgiScope,
    *,
    default: int,
) -> int:
    raw_query = cast(
        bytes,
        scope.get("query_string", b""),
    )
    if not raw_query:
        return default

    values = parse_qs(
        raw_query.decode("ascii"),
        keep_blank_values=True,
    )
    raw_offset = values.get("offset")

    if raw_offset is None:
        return default

    if len(raw_offset) != 1:
        raise ValueError(
            "Query parameter 'offset' must occur once."
        )

    try:
        offset = int(raw_offset[0])
    except ValueError as exc:
        raise ValueError(
            "Query parameter 'offset' must be an integer."
        ) from exc

    if offset < 0:
        raise ValueError(
            "Query parameter 'offset' must be zero or greater."
        )

    return offset


async def _read_json_object(
    receive: AsgiReceive,
) -> dict[str, JsonValue]:
    raw = bytearray()
    while True:
        message = await receive()
        if message.get("type") != "http.request":
            raise ValueError("Invalid HTTP request body event.")
        chunk = cast(bytes, message.get("body", b""))
        if len(raw) + len(chunk) > _MAX_JSON_BODY_BYTES:
            raise ValueError("JSON request body is too large.")
        raw.extend(chunk)
        if not bool(message.get("more_body", False)):
            break
    if not raw:
        raise ValueError("This endpoint requires a JSON request body.")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Request body must contain valid UTF-8 JSON.") from exc
    if not isinstance(payload, dict) or not all(
        isinstance(key, str) for key in payload
    ):
        raise ValueError("JSON request body must be an object.")
    return cast(dict[str, JsonValue], payload)


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
