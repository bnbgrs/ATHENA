"""Loopback-only HTTP lifecycle for the local ATHENA Core API."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

from athena.api.asgi import AsgiMessage, AsgiScope, CoreApiAsgiApp
from athena.api.ports import CoreApiSurface
from athena.api.runtime import ApiDiscovery, LocalApiRuntime

logger = logging.getLogger(__name__)

_LOOPBACK_HOST = "127.0.0.1"
_MAX_REQUEST_BODY_BYTES = 1024 * 1024
_THREAD_JOIN_TIMEOUT_SECONDS = 5.0


class CoreApiServerError(RuntimeError):
    """Raised when the local Core API server cannot start or stop safely."""


class _AthenaHttpServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(
        self,
        server_address: tuple[str, int],
        app: CoreApiAsgiApp,
        shutdown_callback: Callable[[], None] | None,
    ) -> None:
        self.app = app
        self.shutdown_callback = shutdown_callback
        super().__init__(server_address, _AthenaRequestHandler)


class _AthenaRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "ATHENA"
    sys_version = ""

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract
        self._handle_request()

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
        self._handle_request()

    def do_PUT(self) -> None:  # noqa: N802 - stdlib handler contract
        self._handle_request()

    def do_PATCH(self) -> None:  # noqa: N802 - stdlib handler contract
        self._handle_request()

    def do_DELETE(self) -> None:  # noqa: N802 - stdlib handler contract
        self._handle_request()

    def do_OPTIONS(self) -> None:  # noqa: N802 - stdlib handler contract
        self._handle_request()

    def do_HEAD(self) -> None:  # noqa: N802 - stdlib handler contract
        self._handle_request()

    def log_message(self, format: str, *args: object) -> None:
        logger.debug("ATHENA Core API HTTP request: " + format, *args)

    def _handle_request(self) -> None:
        self.close_connection = True
        server = cast(_AthenaHttpServer, self.server)
        response_started = False

        try:
            parsed = urlsplit(self.path)
            if parsed.scheme or parsed.netloc:
                self._send_fallback_problem(
                    status=400,
                    code="invalid_request_target",
                    message="ATHENA Core API requires origin-form request targets.",
                )
                return

            try:
                query_string = parsed.query.encode("ascii")
                raw_path = parsed.path.encode("ascii")
            except UnicodeEncodeError:
                self._send_fallback_problem(
                    status=400,
                    code="invalid_request_target",
                    message="ATHENA Core API request target must be ASCII encoded.",
                )
                return

            headers = [
                (
                    name.lower().encode("latin-1"),
                    value.encode("latin-1"),
                )
                for name, value in self.headers.raw_items()
            ]
            scope: AsgiScope = {
                "type": "http",
                "asgi": {"version": "3.0", "spec_version": "2.5"},
                "http_version": self.request_version.removeprefix("HTTP/"),
                "method": self.command,
                "scheme": "http",
                "path": parsed.path,
                "raw_path": raw_path,
                "query_string": query_string,
                "headers": headers,
                "client": self.client_address,
                "server": self.server.server_address,
            }

            response_status: int | None = None
            response_headers: list[tuple[bytes, bytes]] | None = None
            response_body = bytearray()
            receive_called = False

            async def receive() -> AsgiMessage:
                nonlocal receive_called
                if receive_called:
                    return {"type": "http.disconnect"}
                receive_called = True
                return {
                    "type": "http.request",
                    "body": self._read_request_body(),
                    "more_body": False,
                }

            async def send(message: AsgiMessage) -> None:
                nonlocal response_status, response_headers
                message_type = message.get("type")
                if message_type == "http.response.start":
                    if response_status is not None:
                        raise CoreApiServerError("ASGI response started more than once.")
                    status = message.get("status")
                    headers_value = message.get("headers", [])
                    if not isinstance(status, int):
                        raise CoreApiServerError("ASGI response status is invalid.")
                    if not isinstance(headers_value, list):
                        raise CoreApiServerError("ASGI response headers are invalid.")
                    response_status = status
                    response_headers = cast(list[tuple[bytes, bytes]], headers_value)
                    return
                if message_type == "http.response.body":
                    body = message.get("body", b"")
                    if not isinstance(body, bytes):
                        raise CoreApiServerError("ASGI response body is invalid.")
                    response_body.extend(body)
                    return
                raise CoreApiServerError("ASGI response event is unsupported.")

            asyncio.run(server.app(scope, receive, send))

            if response_status is None or response_headers is None:
                raise CoreApiServerError("ASGI application returned no response start event.")

            response_started = True
            self.send_response_only(response_status)
            for raw_name, raw_value in response_headers:
                name = raw_name.decode("latin-1")
                value = raw_value.decode("latin-1")
                self.send_header(name, value)
            self.send_header("Connection", "close")
            self.end_headers()

            if self.command != "HEAD" and response_body:
                self.wfile.write(response_body)

            if (
                self.command == "POST"
                and parsed.path == "/api/v1/system/shutdown"
                and response_status == 202
                and server.shutdown_callback is not None
            ):
                self.wfile.flush()
                server.shutdown_callback()
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception:
            logger.exception("ATHENA Core API request handling failed")
            if response_started:
                return
            try:
                self._send_fallback_problem(
                    status=500,
                    code="internal_transport_error",
                    message="ATHENA could not complete the local API request.",
                )
            except OSError:
                return

    def _read_request_body(self) -> bytes:
        transfer_encoding = self.headers.get("Transfer-Encoding")
        if transfer_encoding is not None:
            raise ValueError("Chunked request bodies are not supported by this local API.")

        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            return b""
        try:
            content_length = int(raw_length)
        except ValueError as exc:
            raise ValueError("Content-Length must be an integer.") from exc
        if content_length < 0:
            raise ValueError("Content-Length must not be negative.")
        if content_length > _MAX_REQUEST_BODY_BYTES:
            raise ValueError("ATHENA Core API request body is too large.")
        if content_length == 0:
            return b""
        body = self.rfile.read(content_length)
        if len(body) != content_length:
            raise ValueError("ATHENA Core API request body ended unexpectedly.")
        return body

    def _send_fallback_problem(self, *, status: int, code: str, message: str) -> None:
        body = json.dumps(
            {
                "code": code,
                "message": message,
                "request_id": None,
                "retryable": False,
                "details": None,
            },
            separators=(",", ":"),
        ).encode("utf-8")
        self.send_response_only(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)


class CoreApiServer:
    """Own one authenticated loopback listener and its ephemeral discovery state."""

    def __init__(
        self,
        *,
        facade: CoreApiSurface,
        runtime_root: Path,
        host: str = _LOOPBACK_HOST,
        port: int = 0,
        shutdown_callback: Callable[[], None] | None = None,
    ) -> None:
        if host != _LOOPBACK_HOST:
            raise ValueError("ATHENA Core API may bind only to IPv4 loopback in v1.")
        if not 0 <= port <= 65535:
            raise ValueError("ATHENA Core API port must be between 0 and 65535.")
        self._host = host
        self._configured_port = port
        self.runtime = LocalApiRuntime(runtime_root)
        self._shutdown_callback = shutdown_callback
        self.app = CoreApiAsgiApp(
            facade=facade,
            runtime=self.runtime,
            allow_shutdown=shutdown_callback is not None,
        )
        self._server: _AthenaHttpServer | None = None
        self._thread: threading.Thread | None = None
        self._discovery: ApiDiscovery | None = None

    @property
    def name(self) -> str:
        return "core_api"

    @property
    def discovery(self) -> ApiDiscovery | None:
        return self._discovery

    @property
    def port(self) -> int | None:
        discovery = self._discovery
        return None if discovery is None else discovery.port

    @property
    def running(self) -> bool:
        thread = self._thread
        return self._server is not None and thread is not None and thread.is_alive()

    def start(self) -> None:
        if self._server is not None:
            return

        server = _AthenaHttpServer(
            (self._host, self._configured_port),
            self.app,
            self._shutdown_callback,
        )
        actual_port = int(server.server_address[1])
        thread = threading.Thread(
            target=server.serve_forever,
            kwargs={"poll_interval": 0.1},
            name="athena-core-api",
            daemon=True,
        )

        thread_started = False
        try:
            thread.start()
            thread_started = True
            discovery = self.runtime.publish(port=actual_port)
        except Exception:
            if thread_started:
                server.shutdown()
            server.server_close()
            if thread_started:
                thread.join(timeout=_THREAD_JOIN_TIMEOUT_SECONDS)
            try:
                self.runtime.clear()
            except Exception:
                logger.exception("Failed to clear ATHENA Core API runtime after startup error")
            raise

        self._server = server
        self._thread = thread
        self._discovery = discovery
        logger.info(
            "ATHENA Core API listening",
            extra={"event": "core_api.started", "host": self._host, "port": actual_port},
        )

    def stop(self) -> None:
        server = self._server
        thread = self._thread
        self._server = None
        self._thread = None
        self._discovery = None
        failures: list[Exception] = []

        try:
            self.runtime.clear()
        except Exception as exc:
            failures.append(exc)

        if server is not None:
            try:
                server.shutdown()
            except Exception as exc:
                failures.append(exc)
            try:
                server.server_close()
            except Exception as exc:
                failures.append(exc)

        if thread is not None:
            thread.join(timeout=_THREAD_JOIN_TIMEOUT_SECONDS)
            if thread.is_alive():
                failures.append(CoreApiServerError("ATHENA Core API thread did not stop."))

        if failures:
            raise CoreApiServerError("ATHENA Core API did not stop cleanly.") from failures[0]

        logger.info("ATHENA Core API stopped", extra={"event": "core_api.stopped"})
