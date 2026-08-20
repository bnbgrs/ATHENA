"""Local authenticated client used by the ATHENA desktop process."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from athena.api.contracts import (
    API_VERSION,
    CapabilitiesResponse,
    ChatMessageResponse,
    ChatSummaryResponse,
    ChatThreadResponse,
    HealthResponse,
    JsonValue,
    ModelResponse,
    ProviderHealthResponse,
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

    def list_chats(self, *, limit: int = 50) -> tuple[ChatSummaryResponse, ...]:
        if not 1 <= limit <= 200:
            raise ValueError("Chat list limit must be between 1 and 200.")
        payload = self._get("/api/v1/chats", query={"limit": str(limit)})
        return tuple(_chat_summary(item) for item in _items(payload))

    def create_chat(self) -> ChatThreadResponse:
        return _chat_thread(self._request("POST", "/api/v1/chats", expected_status=201))

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
    ) -> ChatThreadResponse:
        if not chat_id or "/" in chat_id:
            raise ValueError("Chat ID must be a single non-empty path segment.")
        if not content.strip():
            raise ValueError(
                "Chat message content must contain non-whitespace text."
            )
        if model_id is not None and not model_id.strip():
            raise ValueError("Chat model_id must be non-empty when provided.")
        payload: dict[str, JsonValue] = {"content": content}
        if model_id is not None:
            payload["model_id"] = model_id
        return _chat_thread(
            self._request(
                "POST",
                f"/api/v1/chats/{chat_id}/messages",
                expected_status=200,
                json_body=payload,
                timeout_seconds=self.generation_timeout_seconds,
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
