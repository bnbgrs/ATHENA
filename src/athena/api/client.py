"""Local authenticated client used by the ATHENA desktop process."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from athena.api.contracts import (
    API_VERSION,
    CanonicalMergeReviewResponse,
    CapabilitiesResponse,
    ChatMessageResponse,
    ChatSummaryResponse,
    ChatThreadResponse,
    ClaimProposalResponse,
    DedupDecisionResponse,
    DeletionDependencyResponse,
    DeletionPreviewResponse,
    DeletionResultResponse,
    ExtractorMergeCandidateResponse,
    GroundedChatResponse,
    GroundedEvidenceResponse,
    GroundedMemoryResponse,
    GroundingResponse,
    HealthResponse,
    JsonValue,
    KnowledgeMergeReviewResponse,
    KnowledgeReviewResponse,
    KnowledgeUnitProposalResponse,
    MessageKnowledgeExtractionResponse,
    ModelResponse,
    ProviderHealthResponse,
    RelationProposalResponse,
    RememberedChatMessageResponse,
)
from athena.config.settings import AthenaSettings
from athena.storage.paths import RuntimePaths

_DISCOVERY_FILE = "core-api.json"
_TOKEN_FILE = "core-api.token"
_LOOPBACK_HOST = "127.0.0.1"
_DEFAULT_TIMEOUT_SECONDS = 5.0


class CoreApiClientError(RuntimeError):
    """Safe client-visible failure from discovery, transport, or API handling."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        code: str | None = None,
        request_id: str | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.request_id = request_id
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class _Bootstrap:
    host: str
    port: int
    token: str
    process_id: int

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"


class CoreApiClient:
    """Read-only bootstrap plus authenticated local HTTP client.

    The desktop process depends on this boundary instead of importing
    ``AthenaApplication``, repositories, or storage internals.
    """

    def __init__(
        self,
        runtime_root: Path,
        *,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        generation_timeout_seconds: float | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("ATHENA API client timeout must be positive.")
        resolved_generation_timeout = (
            timeout_seconds
            if generation_timeout_seconds is None
            else generation_timeout_seconds
        )
        if resolved_generation_timeout <= 0:
            raise ValueError(
                "ATHENA API generation timeout must be positive."
            )
        self.runtime_root = Path(runtime_root)
        self.discovery_path = self.runtime_root / _DISCOVERY_FILE
        self.timeout_seconds = timeout_seconds
        self.generation_timeout_seconds = resolved_generation_timeout

    @classmethod
    def from_environment(
        cls,
        *,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> CoreApiClient:
        """Create the desktop client from ATHENA's normal local runtime root."""
        settings = AthenaSettings.from_environment()
        paths = RuntimePaths.from_settings(settings)
        return cls(
            paths.temp_root / "core-api",
            timeout_seconds=timeout_seconds,
            generation_timeout_seconds=max(
                timeout_seconds,
                float(settings.model_generation_timeout_seconds) + 30.0,
            ),
        )

    def health(self) -> HealthResponse:
        return _health(self._get("/api/v1/health"))

    def capabilities(self) -> CapabilitiesResponse:
        return _capabilities(self._get("/api/v1/capabilities"))

    def list_chats(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[ChatSummaryResponse, ...]:
        if not 1 <= limit <= 200:
            raise ValueError("Chat list limit must be between 1 and 200.")
        if offset < 0:
            raise ValueError("Chat list offset must be zero or greater.")

        query = {"limit": str(limit)}
        if offset:
            query["offset"] = str(offset)

        payload = self._get(
            "/api/v1/chats",
            query=query,
        )
        return tuple(
            _chat_summary(item)
            for item in _items(payload)
        )

    def create_chat(
        self,
        chat_id: str | None = None,
    ) -> ChatThreadResponse:
        if chat_id is None:
            return _chat_thread(
                self._request(
                    "POST",
                    "/api/v1/chats",
                    expected_status=201,
                )
            )

        if not chat_id or "/" in chat_id:
            raise ValueError(
                "Chat ID must be a single non-empty path segment."
            )

        try:
            canonical_chat_id = str(
                uuid.UUID(
                    chat_id
                )
            )
        except ValueError as exc:
            raise ValueError(
                "Chat ID must be a valid UUID."
            ) from exc

        return _chat_thread(
            self._request(
                "PUT",
                (
                    "/api/v1/chats/"
                    + canonical_chat_id
                ),
                expected_status=201,
            )
        )

    def load_chat(self, chat_id: str) -> ChatThreadResponse:
        if not chat_id or "/" in chat_id:
            raise ValueError("Chat ID must be a single non-empty path segment.")
        return _chat_thread(self._get(f"/api/v1/chats/{chat_id}"))

    def send_chat_message(
        self,
        chat_id: str,
        *,
        content: str,
        model_id: str | None = None,
        operation_id: str | None = None,
        effective_context_limit: int | None = None,
        max_output_tokens: int | None = None,
        temperature: float | None = None,
        thinking_enabled: bool | None = None,
    ) -> ChatThreadResponse:
        if not chat_id or "/" in chat_id:
            raise ValueError(
                "Chat ID must be a single non-empty path segment."
            )

        if not content.strip():
            raise ValueError(
                "Chat message content must contain "
                "non-whitespace text."
            )

        if (
            model_id is not None
            and not model_id.strip()
        ):
            raise ValueError(
                "Chat model_id must be non-empty when provided."
            )

        canonical_operation_id: str | None = None

        if operation_id is not None:
            if not operation_id.strip():
                raise ValueError(
                    "Chat operation_id must be non-empty "
                    "when provided."
                )

            try:
                canonical_operation_id = str(
                    uuid.UUID(operation_id)
                )
            except ValueError as exc:
                raise ValueError(
                    "Chat operation_id must be a valid UUID."
                ) from exc

        if effective_context_limit is not None and (
            isinstance(effective_context_limit, bool)
            or not isinstance(effective_context_limit, int)
            or effective_context_limit < 1
        ):
            raise ValueError(
                "Chat effective_context_limit must be "
                "positive when provided."
            )

        if max_output_tokens is not None and (
            isinstance(max_output_tokens, bool)
            or not isinstance(max_output_tokens, int)
            or max_output_tokens < 1
        ):
            raise ValueError(
                "Chat max_output_tokens must be positive "
                "when provided."
            )

        if temperature is not None and (
            isinstance(temperature, bool)
            or not isinstance(temperature, (int, float))
            or not 0.0 <= float(temperature) <= 2.0
        ):
            raise ValueError(
                "Chat temperature must be between 0.0 and 2.0."
            )

        if (
            thinking_enabled is not None
            and not isinstance(thinking_enabled, bool)
        ):
            raise ValueError(
                "Chat thinking_enabled must be boolean "
                "when provided."
            )

        payload: dict[str, JsonValue] = {
            "content": content
        }

        if model_id is not None:
            payload["model_id"] = model_id

        if canonical_operation_id is not None:
            payload[
                "operation_id"
            ] = canonical_operation_id

        if effective_context_limit is not None:
            payload[
                "effective_context_limit"
            ] = effective_context_limit

        if max_output_tokens is not None:
            payload[
                "max_output_tokens"
            ] = max_output_tokens

        if temperature is not None:
            payload[
                "temperature"
            ] = float(temperature)

        if thinking_enabled is not None:
            payload[
                "thinking_enabled"
            ] = thinking_enabled

        return _chat_thread(
            self._request(
                "POST",
                f"/api/v1/chats/{chat_id}/messages",
                expected_status=200,
                json_body=payload,
                timeout_seconds=(
                    self.generation_timeout_seconds
                ),
            )
        )

    def send_unified_local_chat_message(
        self,
        chat_id: str,
        *,
        content: str,
        model_id: str | None = None,
        embedding_model_id: str | None = None,
        effective_context_limit: int | None = None,
        max_output_tokens: int | None = None,
        temperature: float | None = None,
        thinking_enabled: bool | None = None,
    ) -> GroundedChatResponse:
        if not chat_id or "/" in chat_id:
            raise ValueError(
                "Chat ID must be a single non-empty path segment."
            )
        if not content.strip():
            raise ValueError(
                "Chat message content must contain non-whitespace text."
            )
        if model_id is not None and not model_id.strip():
            raise ValueError(
                "Chat model_id must be non-empty when provided."
            )
        if (
            embedding_model_id is not None
            and not embedding_model_id.strip()
        ):
            raise ValueError(
                "Chat embedding_model_id must be non-empty when provided."
            )
        if effective_context_limit is not None and (
            isinstance(effective_context_limit, bool)
            or not isinstance(effective_context_limit, int)
            or effective_context_limit < 1
        ):
            raise ValueError(
                "Chat effective_context_limit must be positive when provided."
            )
        if max_output_tokens is not None and (
            isinstance(max_output_tokens, bool)
            or not isinstance(max_output_tokens, int)
            or max_output_tokens < 1
        ):
            raise ValueError("Chat max_output_tokens must be positive when provided.")
        if temperature is not None and (
            isinstance(temperature, bool)
            or not isinstance(temperature, (int, float))
            or not 0.0 <= float(temperature) <= 2.0
        ):
            raise ValueError("Chat temperature must be between 0.0 and 2.0.")
        if thinking_enabled is not None and not isinstance(thinking_enabled, bool):
            raise ValueError("Chat thinking_enabled must be boolean when provided.")

        payload: dict[str, JsonValue] = {"content": content}
        if model_id is not None:
            payload["model_id"] = model_id
        if embedding_model_id is not None:
            payload["embedding_model_id"] = embedding_model_id
        if effective_context_limit is not None:
            payload["effective_context_limit"] = effective_context_limit
        if max_output_tokens is not None:
            payload["max_output_tokens"] = max_output_tokens
        if temperature is not None:
            payload["temperature"] = float(temperature)
        if thinking_enabled is not None:
            payload["thinking_enabled"] = thinking_enabled

        return _grounded_chat(
            self._request(
                "POST",
                f"/api/v1/chats/{chat_id}/messages/unified-local",
                expected_status=200,
                json_body=payload,
                timeout_seconds=self.generation_timeout_seconds,
            )
        )

    def remember_chat_message(
        self,
        chat_id: str,
        message_id: str,
        *,
        revision_id: str,
    ) -> RememberedChatMessageResponse:
        if not chat_id or "/" in chat_id:
            raise ValueError("Chat ID must be a single non-empty path segment.")
        if not message_id or "/" in message_id:
            raise ValueError("Message ID must be a single non-empty path segment.")
        if not revision_id.strip():
            raise ValueError("Message revision_id must be non-empty.")
        result = _remembered_chat_message(
            self._request(
                "POST",
                f"/api/v1/chats/{chat_id}/messages/{message_id}/remember",
                expected_status=201,
                json_body={"revision_id": revision_id},
            )
        )
        if (
            result.chat_id != chat_id
            or result.message_id != message_id
            or result.message_revision_id != revision_id
        ):
            raise CoreApiClientError(
                "ATHENA Core returned Remember data for another message revision.",
                code="invalid_response",
            )
        return result

    def extract_chat_message_knowledge(
        self,
        chat_id: str,
        message_id: str,
        *,
        revision_id: str,
        model_id: str | None = None,
        effective_context_limit: int | None = None,
        max_output_tokens: int | None = None,
    ) -> MessageKnowledgeExtractionResponse:
        if not chat_id or "/" in chat_id:
            raise ValueError("Chat ID must be a single non-empty path segment.")
        if not message_id or "/" in message_id:
            raise ValueError("Message ID must be a single non-empty path segment.")
        if not revision_id.strip():
            raise ValueError("Message revision_id must be non-empty.")
        if model_id is not None and not model_id.strip():
            raise ValueError(
                "Knowledge extraction model_id must be non-empty when provided."
            )
        if effective_context_limit is not None and (
            isinstance(effective_context_limit, bool)
            or not isinstance(effective_context_limit, int)
            or effective_context_limit < 1
        ):
            raise ValueError(
                "Knowledge extraction effective_context_limit must be positive when provided."
            )
        if max_output_tokens is not None and (
            isinstance(max_output_tokens, bool)
            or not isinstance(max_output_tokens, int)
            or max_output_tokens < 1
        ):
            raise ValueError(
                "Knowledge extraction max_output_tokens must be positive when provided."
            )
        payload: dict[str, JsonValue] = {"revision_id": revision_id}
        if model_id is not None:
            payload["model_id"] = model_id
        if effective_context_limit is not None:
            payload["effective_context_limit"] = effective_context_limit
        if max_output_tokens is not None:
            payload["max_output_tokens"] = max_output_tokens
        result = _message_knowledge_extraction(
            self._request(
                "POST",
                f"/api/v1/chats/{chat_id}/messages/{message_id}/knowledge-extraction",
                expected_status=201,
                json_body=payload,
                timeout_seconds=self.generation_timeout_seconds,
            )
        )
        if (
            result.chat_id != chat_id
            or result.message_id != message_id
            or result.message_revision_id != revision_id
        ):
            raise CoreApiClientError(
                "ATHENA Core returned extraction data for another message revision.",
                code="invalid_response",
            )
        return result

    def prepare_knowledge_review(
        self,
        processing_run_id: str,
    ) -> KnowledgeReviewResponse:
        _require_path_segment(processing_run_id, label="ProcessingRun ID")
        return _knowledge_review(
            self._request(
                "POST",
                f"/api/v1/knowledge-extractions/{processing_run_id}/review",
                expected_status=200,
            )
        )

    def load_knowledge_merge_review(
        self,
        review_id: str,
    ) -> KnowledgeMergeReviewResponse:
        _require_path_segment(review_id, label="Knowledge review ID")
        return _knowledge_merge_review(
            self._get(f"/api/v1/knowledge-merge-reviews/{review_id}")
        )

    def resolve_knowledge_merge_review(
        self,
        review_id: str,
        *,
        decision: str,
    ) -> KnowledgeMergeReviewResponse:
        _require_path_segment(review_id, label="Knowledge review ID")
        if decision not in {"merge", "keep_separate"}:
            raise ValueError(
                "Knowledge merge decision must be 'merge' or 'keep_separate'."
            )
        result = _knowledge_merge_review(
            self._request(
                "POST",
                f"/api/v1/knowledge-merge-reviews/{review_id}/decision",
                expected_status=200,
                json_body={"decision": decision},
            )
        )
        if result.review_id != review_id or result.decision != decision:
            raise CoreApiClientError(
                "ATHENA Core returned another Knowledge merge-review decision.",
                code="invalid_response",
            )
        return result

    def preview_chat_deletion(self, chat_id: str) -> DeletionPreviewResponse:
        if not chat_id or "/" in chat_id:
            raise ValueError("Chat ID must be a single non-empty path segment.")
        return _deletion_preview(
            self._get(f"/api/v1/chats/{chat_id}/deletion-preview")
        )

    def delete_chat(
        self,
        chat_id: str,
        *,
        preview_digest: str,
    ) -> DeletionResultResponse:
        if not chat_id or "/" in chat_id:
            raise ValueError("Chat ID must be a single non-empty path segment.")
        try:
            digest = bytes.fromhex(preview_digest)
        except ValueError as exc:
            raise ValueError("preview_digest must be valid SHA-256 hexadecimal.") from exc
        if len(digest) != 32 or len(preview_digest) != 64:
            raise ValueError("preview_digest must be a SHA-256 hexadecimal digest.")
        return _deletion_result(
            self._request(
                "DELETE",
                f"/api/v1/chats/{chat_id}",
                expected_status=200,
                json_body={"preview_digest": preview_digest},
            )
        )

    def provider_health(self) -> ProviderHealthResponse:
        return _provider_health(self._get("/api/v1/models/health"))

    def list_models(self) -> tuple[ModelResponse, ...]:
        payload = self._get("/api/v1/models")
        return tuple(_model(item) for item in _items(payload))

    def discovery_process_id(self) -> int:
        """Return the PID that published the currently trusted discovery state."""
        return self._load_bootstrap().process_id

    def request_shutdown(self) -> None:
        """Request graceful shutdown without retrying the mutating command."""
        self._request(
            "POST",
            "/api/v1/system/shutdown",
            expected_status=202,
        )

    def _get(
        self,
        path: str,
        *,
        query: dict[str, str] | None = None,
    ) -> dict[str, JsonValue]:
        return self._request("GET", path, query=query, expected_status=200)

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, str] | None = None,
        expected_status: int,
        json_body: dict[str, JsonValue] | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, JsonValue]:
        attempts = 2 if method == "GET" else 1
        last_transport_error: CoreApiClientError | None = None

        for attempt in range(attempts):
            bootstrap = self._load_bootstrap()
            try:
                return self._request_once(
                    bootstrap,
                    method=method,
                    path=path,
                    query=query,
                    expected_status=expected_status,
                    json_body=json_body,
                    timeout_seconds=timeout_seconds,
                )
            except CoreApiClientError as exc:
                if exc.status == 401 and attempt == 0:
                    # Authentication failure cannot have performed the requested
                    # domain action, so one bootstrap refresh is safe for GETs.
                    last_transport_error = exc
                    continue
                if exc.status is None and method == "GET" and attempt == 0:
                    # Reads are safe to retry once after a Core restart/port move.
                    last_transport_error = exc
                    continue
                raise

        if last_transport_error is not None:
            raise last_transport_error
        raise CoreApiClientError("ATHENA Core API request failed.")

    def _request_once(
        self,
        bootstrap: _Bootstrap,
        *,
        method: str,
        path: str,
        query: dict[str, str] | None,
        expected_status: int,
        json_body: dict[str, JsonValue] | None,
        timeout_seconds: float | None,
    ) -> dict[str, JsonValue]:
        suffix = ""
        if query:
            suffix = "?" + urlencode(query)
        url = bootstrap.base_url + path + suffix
        data = b"" if method == "POST" else None
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {bootstrap.token}",
        }
        if json_body is not None:
            data = json.dumps(
                json_body,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(
            url,
            data=data,
            method=method,
            headers=headers,
        )
        resolved_timeout = (
            self.timeout_seconds if timeout_seconds is None else timeout_seconds
        )

        try:
            with urlopen(request, timeout=resolved_timeout) as response:
                status = int(response.status)
                raw = response.read()
        except HTTPError as exc:
            raw = exc.read()
            raise _problem_from_http_error(exc.code, raw) from None
        except (URLError, TimeoutError, OSError) as exc:
            raise CoreApiClientError(
                "ATHENA Core is unavailable.",
                code="core_unavailable",
                retryable=True,
            ) from exc

        if status != expected_status:
            raise CoreApiClientError(
                f"ATHENA Core returned unexpected HTTP status {status}.",
                status=status,
                code="unexpected_status",
            )
        return _json_object(raw)

    def _load_bootstrap(self) -> _Bootstrap:
        root = self.runtime_root
        if root.is_symlink():
            raise CoreApiClientError(
                "ATHENA API runtime directory is not trusted.",
                code="invalid_discovery",
            )
        if self.discovery_path.is_symlink():
            raise CoreApiClientError(
                "ATHENA API discovery file is not trusted.",
                code="invalid_discovery",
            )

        try:
            payload = json.loads(self.discovery_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise CoreApiClientError(
                "ATHENA Core discovery metadata is unavailable.",
                code="discovery_unavailable",
                retryable=True,
            ) from exc

        if not isinstance(payload, dict):
            raise CoreApiClientError(
                "ATHENA Core discovery metadata is invalid.",
                code="invalid_discovery",
            )

        version = payload.get("api_version")
        host = payload.get("host")
        port = payload.get("port")
        token_path_raw = payload.get("token_path")
        process_id = payload.get("process_id")

        if version != API_VERSION:
            raise CoreApiClientError(
                "ATHENA Core API version is incompatible with this desktop client.",
                code="incompatible_api",
            )
        if host != _LOOPBACK_HOST:
            raise CoreApiClientError(
                "ATHENA Core discovery attempted a non-loopback endpoint.",
                code="invalid_discovery",
            )
        if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
            raise CoreApiClientError(
                "ATHENA Core discovery contains an invalid port.",
                code="invalid_discovery",
            )
        if not isinstance(process_id, int) or isinstance(process_id, bool) or process_id <= 0:
            raise CoreApiClientError(
                "ATHENA Core discovery contains an invalid process ID.",
                code="invalid_discovery",
            )
        if not isinstance(token_path_raw, str) or not token_path_raw:
            raise CoreApiClientError(
                "ATHENA Core discovery contains an invalid token path.",
                code="invalid_discovery",
            )

        token_path = Path(token_path_raw)
        expected_token_path = root / _TOKEN_FILE
        try:
            resolved_token = token_path.resolve(strict=False)
            resolved_expected = expected_token_path.resolve(strict=False)
        except OSError as exc:
            raise CoreApiClientError(
                "ATHENA Core token path cannot be validated.",
                code="invalid_discovery",
            ) from exc
        if resolved_token != resolved_expected or token_path.is_symlink():
            raise CoreApiClientError(
                "ATHENA Core discovery attempted an unexpected token path.",
                code="invalid_discovery",
            )

        try:
            token = token_path.read_text(encoding="ascii").strip()
        except (OSError, UnicodeError) as exc:
            raise CoreApiClientError(
                "ATHENA Core session token is unavailable.",
                code="discovery_unavailable",
                retryable=True,
            ) from exc
        if not token or any(character.isspace() for character in token):
            raise CoreApiClientError(
                "ATHENA Core session token is invalid.",
                code="invalid_discovery",
            )
        return _Bootstrap(
            host=host,
            port=port,
            token=token,
            process_id=process_id,
        )


def _require_path_segment(value: str, *, label: str) -> None:
    if not value or "/" in value:
        raise ValueError(f"{label} must be a single non-empty path segment.")


def _problem_from_http_error(status: int, raw: bytes) -> CoreApiClientError:
    try:
        payload = _json_object(raw)
    except CoreApiClientError:
        return CoreApiClientError(
            f"ATHENA Core returned HTTP {status}.",
            status=status,
            code="http_error",
        )

    code = payload.get("code")
    message = payload.get("message")
    request_id = payload.get("request_id")
    retryable = payload.get("retryable", False)
    return CoreApiClientError(
        message if isinstance(message, str) else f"ATHENA Core returned HTTP {status}.",
        status=status,
        code=code if isinstance(code, str) else "http_error",
        request_id=request_id if isinstance(request_id, str) else None,
        retryable=retryable if isinstance(retryable, bool) else False,
    )


def _json_object(raw: bytes) -> dict[str, JsonValue]:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CoreApiClientError(
            "ATHENA Core returned invalid JSON.",
            code="invalid_response",
        ) from exc
    if not isinstance(payload, dict) or not all(isinstance(key, str) for key in payload):
        raise CoreApiClientError(
            "ATHENA Core returned an invalid response object.",
            code="invalid_response",
        )
    return cast(dict[str, JsonValue], payload)


def _items(payload: dict[str, JsonValue]) -> tuple[dict[str, JsonValue], ...]:
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise CoreApiClientError("ATHENA Core response is missing items.", code="invalid_response")
    result: list[dict[str, JsonValue]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            raise CoreApiClientError("ATHENA Core returned an invalid item.", code="invalid_response")
        result.append(item)
    return tuple(result)


def _required_str(payload: dict[str, JsonValue], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise CoreApiClientError(f"ATHENA Core response field {key!r} is invalid.", code="invalid_response")
    return value


def _required_int(payload: dict[str, JsonValue], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise CoreApiClientError(f"ATHENA Core response field {key!r} is invalid.", code="invalid_response")
    return value


def _required_float(payload: dict[str, JsonValue], key: str) -> float:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CoreApiClientError(
            f"ATHENA Core response field {key!r} is invalid.",
            code="invalid_response",
        )
    return float(value)


def _optional_int(payload: dict[str, JsonValue], key: str) -> int | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise CoreApiClientError(f"ATHENA Core response field {key!r} is invalid.", code="invalid_response")
    return value


def _optional_str(payload: dict[str, JsonValue], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise CoreApiClientError(f"ATHENA Core response field {key!r} is invalid.", code="invalid_response")
    return value


def _required_bool(payload: dict[str, JsonValue], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise CoreApiClientError(f"ATHENA Core response field {key!r} is invalid.", code="invalid_response")
    return value


def _optional_bool(payload: dict[str, JsonValue], key: str) -> bool | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise CoreApiClientError(f"ATHENA Core response field {key!r} is invalid.", code="invalid_response")
    return value


def _health(payload: dict[str, JsonValue]) -> HealthResponse:
    return HealthResponse(
        api_version=_required_str(payload, "api_version"),
        core_status=_required_str(payload, "core_status"),
        detail=_optional_str(payload, "detail"),
    )


def _capabilities(payload: dict[str, JsonValue]) -> CapabilitiesResponse:
    raw_features = payload.get("features")
    if not isinstance(raw_features, list) or not all(isinstance(item, str) for item in raw_features):
        raise CoreApiClientError("ATHENA Core capabilities are invalid.", code="invalid_response")
    return CapabilitiesResponse(
        api_version=_required_str(payload, "api_version"),
        features=tuple(cast(list[str], raw_features)),
    )


def _chat_summary(payload: dict[str, JsonValue]) -> ChatSummaryResponse:
    return ChatSummaryResponse(
        chat_id=_required_str(payload, "chat_id"),
        started_at_us=_required_int(payload, "started_at_us"),
        ended_at_us=_optional_int(payload, "ended_at_us"),
        archive_mode=_required_str(payload, "archive_mode"),
        lifecycle_state=_required_str(payload, "lifecycle_state"),
        message_count=_required_int(payload, "message_count"),
    )



def _remembered_chat_message(
    payload: dict[str, JsonValue],
) -> RememberedChatMessageResponse:
    return RememberedChatMessageResponse(
        chat_id=_required_str(payload, "chat_id"),
        message_id=_required_str(payload, "message_id"),
        message_revision_id=_required_str(payload, "message_revision_id"),
        memory_id=_required_str(payload, "memory_id"),
        memory_revision_id=_required_str(payload, "memory_revision_id"),
        content=_required_str(payload, "content"),
    )


def _object_items(
    payload: dict[str, JsonValue],
    key: str,
) -> tuple[dict[str, JsonValue], ...]:
    raw_items = payload.get(key)
    if not isinstance(raw_items, list):
        raise CoreApiClientError(
            f"ATHENA Core response field {key!r} is invalid.",
            code="invalid_response",
        )
    items: list[dict[str, JsonValue]] = []
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            raise CoreApiClientError(
                f"ATHENA Core response field {key!r} contains an invalid item.",
                code="invalid_response",
            )
        items.append(raw_item)
    return tuple(items)


def _knowledge_unit_proposal(
    payload: dict[str, JsonValue],
) -> KnowledgeUnitProposalResponse:
    return KnowledgeUnitProposalResponse(
        proposal_index=_required_int(payload, "proposal_index"),
        source_sequence_no=_required_int(payload, "source_sequence_no"),
        source_quote=_required_str(payload, "source_quote"),
        knowledge_kind=_required_str(payload, "knowledge_kind"),
        title=_optional_str(payload, "title"),
        body=_required_str(payload, "body"),
        epistemic_status=_required_str(payload, "epistemic_status"),
        confidence=_required_float(payload, "confidence"),
    )


def _claim_proposal(payload: dict[str, JsonValue]) -> ClaimProposalResponse:
    return ClaimProposalResponse(
        proposal_index=_required_int(payload, "proposal_index"),
        source_sequence_no=_required_int(payload, "source_sequence_no"),
        source_quote=_required_str(payload, "source_quote"),
        claim_kind=_required_str(payload, "claim_kind"),
        statement=_required_str(payload, "statement"),
        epistemic_status=_required_str(payload, "epistemic_status"),
        confidence=_required_float(payload, "confidence"),
    )


def _relation_proposal(payload: dict[str, JsonValue]) -> RelationProposalResponse:
    return RelationProposalResponse(
        relation_index=_required_int(payload, "relation_index"),
        left_type=_required_str(payload, "left_type"),
        left_index=_required_int(payload, "left_index"),
        relation_type=_required_str(payload, "relation_type"),
        right_type=_required_str(payload, "right_type"),
        right_index=_required_int(payload, "right_index"),
        confidence=_required_float(payload, "confidence"),
    )


def _extractor_merge_candidate(
    payload: dict[str, JsonValue],
) -> ExtractorMergeCandidateResponse:
    return ExtractorMergeCandidateResponse(
        candidate_index=_required_int(payload, "candidate_index"),
        proposal_type=_required_str(payload, "proposal_type"),
        proposal_index=_required_int(payload, "proposal_index"),
        reason=_required_str(payload, "reason"),
        confidence=_required_float(payload, "confidence"),
    )


def _message_knowledge_extraction(
    payload: dict[str, JsonValue],
) -> MessageKnowledgeExtractionResponse:
    result = MessageKnowledgeExtractionResponse(
        chat_id=_required_str(payload, "chat_id"),
        message_id=_required_str(payload, "message_id"),
        message_revision_id=_required_str(payload, "message_revision_id"),
        processing_run_id=_required_str(payload, "processing_run_id"),
        model_id=_required_str(payload, "model_id"),
        model_signature_id=_required_str(payload, "model_signature_id"),
        knowledge_units=tuple(
            _knowledge_unit_proposal(item)
            for item in _object_items(payload, "knowledge_units")
        ),
        claims=tuple(
            _claim_proposal(item) for item in _object_items(payload, "claims")
        ),
        relations=tuple(
            _relation_proposal(item) for item in _object_items(payload, "relations")
        ),
        extractor_merge_candidates=tuple(
            _extractor_merge_candidate(item)
            for item in _object_items(payload, "extractor_merge_candidates")
        ),
    )
    if tuple(item.proposal_index for item in result.knowledge_units) != tuple(
        range(len(result.knowledge_units))
    ):
        raise CoreApiClientError(
            "ATHENA Core returned non-contiguous Knowledge proposal indexes.",
            code="invalid_response",
        )
    if tuple(item.proposal_index for item in result.claims) != tuple(
        range(len(result.claims))
    ):
        raise CoreApiClientError(
            "ATHENA Core returned non-contiguous Claim proposal indexes.",
            code="invalid_response",
        )
    if tuple(item.relation_index for item in result.relations) != tuple(
        range(len(result.relations))
    ):
        raise CoreApiClientError(
            "ATHENA Core returned non-contiguous relation indexes.",
            code="invalid_response",
        )
    if tuple(
        item.candidate_index for item in result.extractor_merge_candidates
    ) != tuple(range(len(result.extractor_merge_candidates))):
        raise CoreApiClientError(
            "ATHENA Core returned non-contiguous merge-candidate indexes.",
            code="invalid_response",
        )
    proposal_counts = {
        "knowledge": len(result.knowledge_units),
        "claim": len(result.claims),
    }
    for relation in result.relations:
        left_count = proposal_counts.get(relation.left_type)
        right_count = proposal_counts.get(relation.right_type)
        if (
            left_count is None
            or right_count is None
            or not 0 <= relation.left_index < left_count
            or not 0 <= relation.right_index < right_count
        ):
            raise CoreApiClientError(
                "ATHENA Core returned an invalid proposal relation reference.",
                code="invalid_response",
            )
    for candidate in result.extractor_merge_candidates:
        proposal_count = proposal_counts.get(candidate.proposal_type)
        if proposal_count is None or not 0 <= candidate.proposal_index < proposal_count:
            raise CoreApiClientError(
                "ATHENA Core returned an invalid extractor merge-candidate reference.",
                code="invalid_response",
            )
    return result


def _dedup_decision(
    payload: dict[str, JsonValue],
) -> DedupDecisionResponse:
    proposal_type = _required_str(payload, "proposal_type")
    proposal_index = _required_int(payload, "proposal_index")
    action = _required_str(payload, "action")
    existing_entity_id = _optional_str(payload, "existing_entity_id")
    existing_revision_id = _optional_str(payload, "existing_revision_id")
    duplicate_of = _optional_int(payload, "duplicate_of_proposal_index")
    if proposal_type not in {"knowledge", "claim"} or proposal_index < 0:
        raise CoreApiClientError(
            "ATHENA Core returned an invalid deduplication proposal reference.",
            code="invalid_response",
        )
    if action == "create":
        valid = (
            existing_entity_id is None
            and existing_revision_id is None
            and duplicate_of is None
        )
    elif action == "reuse_canonical":
        valid = (
            existing_entity_id is not None
            and existing_revision_id is not None
            and duplicate_of is None
        )
    elif action == "reuse_proposal":
        valid = (
            existing_entity_id is None
            and existing_revision_id is None
            and duplicate_of is not None
            and 0 <= duplicate_of < proposal_index
        )
    else:
        valid = False
    if not valid:
        raise CoreApiClientError(
            "ATHENA Core returned an invalid deduplication decision.",
            code="invalid_response",
        )
    return DedupDecisionResponse(
        proposal_type=proposal_type,
        proposal_index=proposal_index,
        action=action,
        existing_entity_id=existing_entity_id,
        existing_revision_id=existing_revision_id,
        duplicate_of_proposal_index=duplicate_of,
    )


def _canonical_merge_review(
    payload: dict[str, JsonValue],
) -> CanonicalMergeReviewResponse:
    candidate_index = _required_int(payload, "candidate_index")
    proposal_type = _required_str(payload, "proposal_type")
    proposal_index = _required_int(payload, "proposal_index")
    similarity = _required_float(payload, "similarity")
    if (
        candidate_index < 0
        or proposal_type not in {"knowledge", "claim"}
        or proposal_index < 0
        or not 0.0 <= similarity <= 1.0
    ):
        raise CoreApiClientError(
            "ATHENA Core returned an invalid canonical merge candidate.",
            code="invalid_response",
        )
    return CanonicalMergeReviewResponse(
        candidate_index=candidate_index,
        review_id=_required_str(payload, "review_id"),
        proposal_type=proposal_type,
        proposal_index=proposal_index,
        existing_entity_id=_required_str(payload, "existing_entity_id"),
        existing_revision_id=_required_str(payload, "existing_revision_id"),
        similarity=similarity,
        reason=_required_str(payload, "reason"),
    )


def _knowledge_review(
    payload: dict[str, JsonValue],
) -> KnowledgeReviewResponse:
    raw_ready = payload.get("ready_to_accept")
    if not isinstance(raw_ready, bool):
        raise CoreApiClientError(
            "ATHENA Core response field 'ready_to_accept' is invalid.",
            code="invalid_response",
        )
    result = KnowledgeReviewResponse(
        processing_run_id=_required_str(payload, "processing_run_id"),
        model_signature_id=_required_str(payload, "model_signature_id"),
        ready_to_accept=raw_ready,
        blocked_reason=_optional_str(payload, "blocked_reason"),
        preflight_digest=_optional_str(payload, "preflight_digest"),
        knowledge_decisions=tuple(
            _dedup_decision(item)
            for item in _object_items(payload, "knowledge_decisions")
        ),
        claim_decisions=tuple(
            _dedup_decision(item)
            for item in _object_items(payload, "claim_decisions")
        ),
        canonical_merge_candidates=tuple(
            _canonical_merge_review(item)
            for item in _object_items(payload, "canonical_merge_candidates")
        ),
    )
    allowed_blockers = {
        "extractor_merge_candidates",
        "canonical_merge_candidates",
    }
    if result.ready_to_accept:
        if (
            result.blocked_reason is not None
            or result.canonical_merge_candidates
        ):
            raise CoreApiClientError(
                "ATHENA Core returned an inconsistent Knowledge review state.",
                code="invalid_response",
            )
        digest = result.preflight_digest
        if digest is None or len(digest) != 64:
            raise CoreApiClientError(
                "ATHENA Core returned an invalid Knowledge preflight digest.",
                code="invalid_response",
            )
        try:
            digest_bytes = bytes.fromhex(digest)
        except ValueError as exc:
            raise CoreApiClientError(
                "ATHENA Core returned an invalid Knowledge preflight digest.",
                code="invalid_response",
            ) from exc
        if len(digest_bytes) != 32:
            raise CoreApiClientError(
                "ATHENA Core returned an invalid Knowledge preflight digest.",
                code="invalid_response",
            )
    else:
        if (
            result.blocked_reason not in allowed_blockers
            or result.preflight_digest is not None
        ):
            raise CoreApiClientError(
                "ATHENA Core returned an inconsistent blocked Knowledge review.",
                code="invalid_response",
            )
        if result.blocked_reason == "extractor_merge_candidates" and (
            result.knowledge_decisions
            or result.claim_decisions
            or result.canonical_merge_candidates
        ):
            raise CoreApiClientError(
                "Extractor-blocked Knowledge review exposed canonical decisions.",
                code="invalid_response",
            )
        if (
            result.blocked_reason == "canonical_merge_candidates"
            and not result.canonical_merge_candidates
        ):
            raise CoreApiClientError(
                "Canonical-merge blocker is missing merge-review candidates.",
                code="invalid_response",
            )

    if tuple(item.proposal_index for item in result.knowledge_decisions) != tuple(
        range(len(result.knowledge_decisions))
    ) or any(
        item.proposal_type != "knowledge" for item in result.knowledge_decisions
    ):
        raise CoreApiClientError(
            "ATHENA Core returned invalid Knowledge deduplication indexes.",
            code="invalid_response",
        )
    if tuple(item.proposal_index for item in result.claim_decisions) != tuple(
        range(len(result.claim_decisions))
    ) or any(
        item.proposal_type != "claim" for item in result.claim_decisions
    ):
        raise CoreApiClientError(
            "ATHENA Core returned invalid Claim deduplication indexes.",
            code="invalid_response",
        )
    if tuple(
        item.candidate_index for item in result.canonical_merge_candidates
    ) != tuple(range(len(result.canonical_merge_candidates))):
        raise CoreApiClientError(
            "ATHENA Core returned non-contiguous canonical merge indexes.",
            code="invalid_response",
        )
    if len(
        {item.review_id for item in result.canonical_merge_candidates}
    ) != len(result.canonical_merge_candidates):
        raise CoreApiClientError(
            "ATHENA Core returned duplicate canonical merge-review IDs.",
            code="invalid_response",
        )
    proposal_counts = {
        "knowledge": len(result.knowledge_decisions),
        "claim": len(result.claim_decisions),
    }
    for candidate in result.canonical_merge_candidates:
        proposal_count = proposal_counts[candidate.proposal_type]
        if not 0 <= candidate.proposal_index < proposal_count:
            raise CoreApiClientError(
                "ATHENA Core returned an invalid canonical merge proposal reference.",
                code="invalid_response",
            )
    return result


def _knowledge_merge_review(
    payload: dict[str, JsonValue],
) -> KnowledgeMergeReviewResponse:
    similarity = _required_float(payload, "similarity")
    proposal_type = _required_str(payload, "proposal_type")
    proposal_index = _required_int(payload, "proposal_index")
    status = _required_str(payload, "status")
    decision = _optional_str(payload, "decision")
    if (
        not 0.0 <= similarity <= 1.0
        or proposal_type not in {"knowledge", "claim"}
        or proposal_index < 0
        or status not in {"pending", "accepted", "rejected", "superseded"}
    ):
        raise CoreApiClientError(
            "ATHENA Core returned an invalid Knowledge merge review.",
            code="invalid_response",
        )
    if status == "pending" and decision is not None:
        raise CoreApiClientError(
            "Pending Knowledge merge review cannot have a decision.",
            code="invalid_response",
        )
    if status == "accepted" and decision not in {
        "merge",
        "keep_separate",
    }:
        raise CoreApiClientError(
            "Resolved Knowledge merge review has an invalid decision.",
            code="invalid_response",
        )
    if status in {"rejected", "superseded"} and decision is not None:
        raise CoreApiClientError(
            "Non-accepted Knowledge merge review cannot have a merge decision.",
            code="invalid_response",
        )
    return KnowledgeMergeReviewResponse(
        review_id=_required_str(payload, "review_id"),
        status=status,
        proposal_type=proposal_type,
        proposal_index=proposal_index,
        source_entity_id=_required_str(payload, "source_entity_id"),
        source_revision_id=_required_str(payload, "source_revision_id"),
        proposal_text=_required_str(payload, "proposal_text"),
        proposal_kind=_required_str(payload, "proposal_kind"),
        proposal_epistemic_status=_required_str(
            payload,
            "proposal_epistemic_status",
        ),
        similarity=similarity,
        decision=decision,
        existing_entity_id=_required_str(payload, "existing_entity_id"),
        existing_revision_id=_required_str(payload, "existing_revision_id"),
    )


def _deletion_dependency(
    payload: dict[str, JsonValue],
) -> DeletionDependencyResponse:
    return DeletionDependencyResponse(
        relation=_required_str(payload, "relation"),
        count=_required_int(payload, "count"),
        dependent_entity_id=_optional_str(payload, "dependent_entity_id"),
        dependent_entity_type=_optional_str(payload, "dependent_entity_type"),
    )


def _deletion_preview(payload: dict[str, JsonValue]) -> DeletionPreviewResponse:
    raw_dependencies = payload.get("dependencies")
    if not isinstance(raw_dependencies, list):
        raise CoreApiClientError(
            "ATHENA Core deletion dependencies are invalid.",
            code="invalid_response",
        )
    dependencies_list: list[DeletionDependencyResponse] = []
    for raw_dependency in raw_dependencies:
        if not isinstance(raw_dependency, dict):
            raise CoreApiClientError(
                "ATHENA Core deletion dependency is invalid.",
                code="invalid_response",
            )
        dependencies_list.append(
            _deletion_dependency(raw_dependency)
        )
    dependencies = tuple(dependencies_list)
    preview = DeletionPreviewResponse(
        entity_id=_required_str(payload, "entity_id"),
        entity_type=_required_str(payload, "entity_type"),
        lifecycle_state=_required_str(payload, "lifecycle_state"),
        dependencies=dependencies,
        preview_digest=_required_str(payload, "preview_digest"),
    )
    if preview.entity_type != "chat" or len(preview.preview_digest) != 64:
        raise CoreApiClientError(
            "ATHENA Core returned an invalid chat deletion preview.",
            code="invalid_response",
        )
    return preview


def _deletion_result(payload: dict[str, JsonValue]) -> DeletionResultResponse:
    raw_deleted = payload.get("deleted_entity_ids")
    if not isinstance(raw_deleted, list) or not all(
        isinstance(item, str) and item for item in raw_deleted
    ):
        raise CoreApiClientError(
            "ATHENA Core deletion result is invalid.",
            code="invalid_response",
        )
    deleted_ids = tuple(cast(str, item) for item in raw_deleted)
    result = DeletionResultResponse(
        entity_id=_required_str(payload, "entity_id"),
        entity_type=_required_str(payload, "entity_type"),
        commit_id=_required_str(payload, "commit_id"),
        deleted_entity_ids=deleted_ids,
        preview_digest=_required_str(payload, "preview_digest"),
    )
    if result.entity_type != "chat" or result.entity_id not in result.deleted_entity_ids:
        raise CoreApiClientError(
            "ATHENA Core returned an inconsistent chat deletion result.",
            code="invalid_response",
        )
    return result


def _chat_message(payload: dict[str, JsonValue]) -> ChatMessageResponse:
    return ChatMessageResponse(
        message_id=_required_str(payload, "message_id"),
        chat_id=_required_str(payload, "chat_id"),
        sequence_no=_required_int(payload, "sequence_no"),
        message_type=_required_str(payload, "message_type"),
        actor_id=_optional_str(payload, "actor_id"),
        created_at_us=_required_int(payload, "created_at_us"),
        revision_id=_required_str(payload, "revision_id"),
        content=_optional_str(payload, "content"),
        content_format=_optional_str(payload, "content_format"),
    )


def _chat_thread(payload: dict[str, JsonValue]) -> ChatThreadResponse:
    raw_messages = payload.get("messages")
    if not isinstance(raw_messages, list):
        raise CoreApiClientError("ATHENA Core chat messages are invalid.", code="invalid_response")
    messages: list[ChatMessageResponse] = []
    for raw_message in raw_messages:
        if not isinstance(raw_message, dict):
            raise CoreApiClientError("ATHENA Core chat message is invalid.", code="invalid_response")
        messages.append(_chat_message(raw_message))
    return ChatThreadResponse(
        chat_id=_required_str(payload, "chat_id"),
        started_at_us=_required_int(payload, "started_at_us"),
        ended_at_us=_optional_int(payload, "ended_at_us"),
        archive_mode=_required_str(payload, "archive_mode"),
        lifecycle_state=_required_str(payload, "lifecycle_state"),
        messages=tuple(messages),
    )


def _required_object(
    payload: dict[str, JsonValue],
    key: str,
) -> dict[str, JsonValue]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise CoreApiClientError(
            f"ATHENA Core response field {key!r} is invalid.",
            code="invalid_response",
        )
    return value


def _required_str_tuple(
    payload: dict[str, JsonValue],
    key: str,
) -> tuple[str, ...]:
    value = payload.get(key)
    if (
        not isinstance(value, list)
        or not all(isinstance(item, str) for item in value)
    ):
        raise CoreApiClientError(
            f"ATHENA Core response field {key!r} is invalid.",
            code="invalid_response",
        )
    return tuple(cast(list[str], value))


def _grounded_evidence(
    payload: dict[str, JsonValue],
) -> GroundedEvidenceResponse:
    if "epistemic_status" not in payload:
        raise CoreApiClientError(
            "ATHENA Core response field 'epistemic_status' is missing.",
            code="invalid_response",
        )
    item = GroundedEvidenceResponse(
        context_id=_required_str(payload, "context_id"),
        evidence_class=_required_str(payload, "evidence_class"),
        entity_type=_required_str(payload, "entity_type"),
        entity_id=_required_str(payload, "entity_id"),
        revision_id=_optional_str(payload, "revision_id"),
        title=_optional_str(payload, "title"),
        text=_required_str(payload, "text"),
        cited=_required_bool(payload, "cited"),
        epistemic_status=_optional_str(
            payload,
            "epistemic_status",
        ),
        source_id=_optional_str(payload, "source_id"),
        representation_id=_optional_str(
            payload,
            "representation_id",
        ),
        source_name=_optional_str(payload, "source_name"),
        source_uri=_optional_str(payload, "source_uri"),
        start_offset=_optional_int(payload, "start_offset"),
        end_offset=_optional_int(payload, "end_offset"),
        page_start=_optional_int(payload, "page_start"),
        page_end=_optional_int(payload, "page_end"),
        quoted_sha256=_optional_str(payload, "quoted_sha256"),
        truncated=_required_bool(payload, "truncated"),
    )

    source_metadata = (
        item.source_id,
        item.representation_id,
        item.start_offset,
        item.end_offset,
        item.quoted_sha256,
    )
    allowed_epistemic_statuses = {
        "asserted",
        "supported",
        "disputed",
        "contradicted",
        "retracted",
        "superseded",
        "uncertain",
        "unknown",
    }
    if item.evidence_class == "canonical":
        if (
            item.epistemic_status
            not in allowed_epistemic_statuses
        ):
            raise CoreApiClientError(
                "ATHENA Core returned canonical evidence without a valid epistemic status.",
                code="invalid_response",
            )
    elif item.epistemic_status is not None:
        raise CoreApiClientError(
            "ATHENA Core mixed canonical epistemic status into non-canonical evidence.",
            code="invalid_response",
        )

    if item.evidence_class == "source":
        if (
            item.entity_type != "source_anchor"
            or item.revision_id is not None
            or any(value is None for value in source_metadata)
        ):
            raise CoreApiClientError(
                "ATHENA Core returned incomplete source evidence.",
                code="invalid_response",
            )
        assert item.start_offset is not None
        assert item.end_offset is not None
        assert item.quoted_sha256 is not None
        if not 0 <= item.start_offset < item.end_offset:
            raise CoreApiClientError(
                "ATHENA Core returned an invalid source range.",
                code="invalid_response",
            )
        try:
            digest = bytes.fromhex(item.quoted_sha256)
        except ValueError as exc:
            raise CoreApiClientError(
                "ATHENA Core returned an invalid source hash.",
                code="invalid_response",
            ) from exc
        if len(digest) != 32:
            raise CoreApiClientError(
                "ATHENA Core returned an invalid source hash.",
                code="invalid_response",
            )
    else:
        if item.revision_id is None:
            raise CoreApiClientError(
                "ATHENA Core returned evidence without a revision.",
                code="invalid_response",
            )
        if any(value is not None for value in source_metadata):
            raise CoreApiClientError(
                "ATHENA Core mixed source metadata into non-source evidence.",
                code="invalid_response",
            )

    return item


def _grounded_memory(
    payload: dict[str, JsonValue],
) -> GroundedMemoryResponse:
    return GroundedMemoryResponse(
        context_id=_required_str(payload, "context_id"),
        memory_id=_required_str(payload, "memory_id"),
        revision_id=_required_str(payload, "revision_id"),
        memory_kind=_required_str(payload, "memory_kind"),
        scope_kind=_required_str(payload, "scope_kind"),
        scope_entity_id=_optional_str(
            payload,
            "scope_entity_id",
        ),
        content=_required_str(payload, "content"),
    )


def _grounding(
    payload: dict[str, JsonValue],
) -> GroundingResponse:
    return GroundingResponse(
        cited_context_ids=_required_str_tuple(
            payload,
            "cited_context_ids",
        ),
        canonical_context_ids=_required_str_tuple(
            payload,
            "canonical_context_ids",
        ),
        user_statement_context_ids=_required_str_tuple(
            payload,
            "user_statement_context_ids",
        ),
        conversation_context_ids=_required_str_tuple(
            payload,
            "conversation_context_ids",
        ),
        source_context_ids=_required_str_tuple(
            payload,
            "source_context_ids",
        ),
        research_context_ids=_required_str_tuple(
            payload,
            "research_context_ids",
        ),
        news_context_ids=_required_str_tuple(
            payload,
            "news_context_ids",
        ),
        invalid_context_ids=_required_str_tuple(
            payload,
            "invalid_context_ids",
        ),
        uses_inference=_required_bool(
            payload,
            "uses_inference",
        ),
        uses_model_prior=_required_bool(
            payload,
            "uses_model_prior",
        ),
        uses_unknown=_required_bool(
            payload,
            "uses_unknown",
        ),
        has_provenance_marker=_required_bool(
            payload,
            "has_provenance_marker",
        ),
    )


def _grounded_chat(
    payload: dict[str, JsonValue],
) -> GroundedChatResponse:
    raw_evidence = payload.get("evidence")
    if not isinstance(raw_evidence, list):
        raise CoreApiClientError(
            "ATHENA Core grounded evidence is invalid.",
            code="invalid_response",
        )
    evidence = tuple(
        _grounded_evidence(
            item
        )
        for item in raw_evidence
        if isinstance(item, dict)
    )
    if len(evidence) != len(raw_evidence):
        raise CoreApiClientError(
            "ATHENA Core grounded evidence item is invalid.",
            code="invalid_response",
        )

    raw_memory = payload.get("personal_memory")
    if not isinstance(raw_memory, list):
        raise CoreApiClientError(
            "ATHENA Core grounded Personal Memory is invalid.",
            code="invalid_response",
        )
    personal_memory = tuple(
        _grounded_memory(
            item
        )
        for item in raw_memory
        if isinstance(item, dict)
    )
    if len(personal_memory) != len(raw_memory):
        raise CoreApiClientError(
            "ATHENA Core grounded Personal Memory item is invalid.",
            code="invalid_response",
        )

    grounding = _grounding(
        _required_object(payload, "grounding")
    )
    evidence_ids = tuple(item.context_id for item in evidence)
    if len(set(evidence_ids)) != len(evidence_ids):
        raise CoreApiClientError(
            "ATHENA Core returned duplicate evidence context IDs.",
            code="invalid_response",
        )
    cited = set(grounding.cited_context_ids)
    if not cited.issubset(evidence_ids):
        raise CoreApiClientError(
            "ATHENA Core grounding cites missing evidence.",
            code="invalid_response",
        )
    for item in evidence:
        if item.cited != (item.context_id in cited):
            raise CoreApiClientError(
                "ATHENA Core evidence citation state is inconsistent.",
                code="invalid_response",
            )
    if grounding.invalid_context_ids:
        raise CoreApiClientError(
            "ATHENA Core returned invalid grounding references.",
            code="invalid_response",
        )

    assistant_text = _required_str(
        payload,
        "assistant_text",
    ).strip()
    if not assistant_text:
        raise CoreApiClientError(
            "ATHENA Core grounded assistant text is blank.",
            code="invalid_response",
        )

    return GroundedChatResponse(
        thread=_chat_thread(
            _required_object(payload, "thread")
        ),
        assistant_text=assistant_text,
        evidence=evidence,
        personal_memory=personal_memory,
        grounding=grounding,
        processing_run_id=_required_str(
            payload,
            "processing_run_id",
        ),
        model_id=_required_str(payload, "model_id"),
        embedding_model_id=_optional_str(
            payload,
            "embedding_model_id",
        ),
    )


def _provider_health(payload: dict[str, JsonValue]) -> ProviderHealthResponse:
    return ProviderHealthResponse(
        provider=_required_str(payload, "provider"),
        status=_required_str(payload, "status"),
        detail=_optional_str(payload, "detail"),
    )


def _model(payload: dict[str, JsonValue]) -> ModelResponse:
    return ModelResponse(
        provider=_required_str(payload, "provider"),
        backend_model_id=_required_str(payload, "backend_model_id"),
        display_name=_required_str(payload, "display_name"),
        model_type=_required_str(payload, "model_type"),
        context_capacity=_optional_int(payload, "context_capacity"),
        quantization=_optional_str(payload, "quantization"),
        loaded=_required_bool(payload, "loaded"),
        vision=_optional_bool(payload, "vision"),
        trained_for_tool_use=_optional_bool(payload, "trained_for_tool_use"),
        loaded_context_length=_optional_int(payload, "loaded_context_length"),
    )
