"""Fail-closed external access authorization, transport, audit, and Source capture."""

from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import os
import secrets
import socket
import sqlite3
import ssl
import struct
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlsplit, urlunsplit

from athena.chat.service import ChatService
from athena.common.ids import new_uuid7, uuid_from_blob, uuid_to_blob
from athena.common.time import utc_now_us
from athena.jobs.models import JobRecord
from athena.research.service import ResearchService
from athena.source.models import SourceCaptureResult
from athena.source.service import SourceCaptureService
from athena.storage.database import SQLiteDatabase
from athena.storage.paths import RuntimePaths


class ExternalAccessError(RuntimeError):
    """Base error for fail-closed external access."""


class ExternalAuthorizationError(ExternalAccessError):
    """Raised when an external request is not authorized."""


class ExternalDestinationError(ExternalAccessError):
    """Raised when an external destination violates network policy."""


class ExternalTransportError(ExternalAccessError):
    """Raised when an authorized transport cannot complete safely."""


class ExternalResponsePolicyError(ExternalTransportError):
    """Raised when fetched bytes violate response policy; direct fallback cannot fix it."""


class ExternalDirectApprovalRequired(ExternalAccessError):
    """Raised when Tor Preferred cannot fetch and explicit direct approval is needed."""

    def __init__(self, *, url: str, reason_code: str) -> None:
        self.url = url
        self.reason_code = reason_code
        super().__init__(
            "Tor Preferred could not fetch this source safely; explicit direct "
            "authorization is required before ATHENA may expose the normal IP. "
            f"reason={reason_code} url={_provenance_url(url)}"
        )


@dataclass(frozen=True, slots=True)
class ExternalAccessAuthorizationRecord:
    authorization_id: uuid.UUID
    actor_id: uuid.UUID
    purpose: str
    allowed_hosts_json: str
    privacy_route: str
    origin: str
    expires_at_us: int
    revoked_at_us: int | None
    created_at_us: int


@dataclass(frozen=True, slots=True)
class ExternalResponse:
    final_url: str
    status: int
    headers: Mapping[str, str]
    body: bytes


class ExternalTransport(Protocol):
    def fetch(self, url: str, *, max_bytes: int, timeout_seconds: float) -> ExternalResponse:
        """Fetch one already-policy-validated URL."""
        ...


class DirectExplicitTransport:
    """Explicit direct route. Never used as fallback from another privacy route."""

    def fetch(self, url: str, *, max_bytes: int, timeout_seconds: float) -> ExternalResponse:
        parsed = urlsplit(url)
        host = parsed.hostname
        if host is None:
            raise ExternalDestinationError("External URL has no host.")
        host = _normalize_host(host)
        port = parsed.port or _default_port(parsed.scheme)
        sock = _connect_direct_validated(
            host,
            port,
            timeout_seconds=timeout_seconds,
        )
        try:
            return _http_over_socket(
                sock,
                url=url,
                max_bytes=max_bytes,
                timeout_seconds=timeout_seconds,
            )
        finally:
            sock.close()


class TorSocksTransport:
    """SOCKS5 transport using proxy-side domain resolution to avoid local DNS leaks."""

    def __init__(
        self,
        *,
        proxy_host: str = "127.0.0.1",
        proxy_ports: Sequence[int] | None = None,
    ) -> None:
        proxy_ip = ipaddress.ip_address(proxy_host)
        if not proxy_ip.is_loopback:
            raise ValueError("Tor SOCKS proxy must be loopback for ATHENA v1.")
        env_port = os.getenv("ATHENA_TOR_SOCKS_PORT", "").strip()
        if proxy_ports is not None and env_port:
            raise ValueError(
                "Specify Tor SOCKS ports either explicitly or through ATHENA_TOR_SOCKS_PORT."
            )
        selected_ports: tuple[int, ...]
        if env_port:
            try:
                selected_ports = (int(env_port),)
            except ValueError as exc:
                raise ValueError("ATHENA_TOR_SOCKS_PORT must be an integer.") from exc
        else:
            selected_ports = tuple(proxy_ports or (9050, 9150))
        if not selected_ports or any(not 1 <= port <= 65535 for port in selected_ports):
            raise ValueError("Tor SOCKS proxy port is invalid.")
        self.proxy_host = proxy_host
        self.proxy_ports = selected_ports

    def fetch(self, url: str, *, max_bytes: int, timeout_seconds: float) -> ExternalResponse:
        parsed = urlsplit(url)
        host = parsed.hostname
        if host is None:
            raise ExternalDestinationError("External URL has no host.")
        host = _normalize_host(host)
        host_bytes = host.encode("ascii")
        if len(host_bytes) > 255:
            raise ExternalDestinationError("Destination hostname is too long for SOCKS5.")
        port = parsed.port or _default_port(parsed.scheme)

        failures: list[str] = []
        for proxy_port in self.proxy_ports:
            try:
                sock = socket.create_connection(
                    (self.proxy_host, proxy_port),
                    timeout=timeout_seconds,
                )
                try:
                    sock.settimeout(timeout_seconds)
                    # Tor supports SOCKS5 auth values as stream-isolation keys.
                    # Use the current <torS0X>0 extension form and a fresh
                    # password isolation value per fetch, without resolving
                    # the destination locally.
                    username = b"<torS0X>0"
                    password = secrets.token_hex(16).encode("ascii")
                    sock.sendall(b"\x05\x01\x02")
                    if _recv_exact(sock, 2) != b"\x05\x02":
                        raise ExternalTransportError(
                            "Tor SOCKS5 proxy rejected isolated-auth negotiation."
                        )
                    auth = (
                        b"\x01"
                        + bytes((len(username),))
                        + username
                        + bytes((len(password),))
                        + password
                    )
                    sock.sendall(auth)
                    if _recv_exact(sock, 2) != b"\x01\x00":
                        raise ExternalTransportError(
                            "Tor SOCKS5 proxy rejected stream-isolation credentials."
                        )
                    request = (
                        b"\x05\x01\x00\x03"
                        + bytes((len(host_bytes),))
                        + host_bytes
                        + struct.pack("!H", port)
                    )
                    sock.sendall(request)
                    reply = _recv_exact(sock, 4)
                    if len(reply) != 4 or reply[0] != 5 or reply[1] != 0:
                        raise ExternalTransportError(
                            "Tor SOCKS5 proxy refused destination connection."
                        )
                    atyp = reply[3]
                    if atyp == 1:
                        _recv_exact(sock, 4)
                    elif atyp == 3:
                        length = _recv_exact(sock, 1)[0]
                        _recv_exact(sock, length)
                    elif atyp == 4:
                        _recv_exact(sock, 16)
                    else:
                        raise ExternalTransportError(
                            "Tor SOCKS5 proxy returned invalid address type."
                        )
                    _recv_exact(sock, 2)
                    return _http_over_socket(
                        sock,
                        url=url,
                        max_bytes=max_bytes,
                        timeout_seconds=timeout_seconds,
                    )
                finally:
                    sock.close()
            except ExternalResponsePolicyError:
                raise
            except (OSError, ExternalTransportError) as exc:
                failures.append(f"{proxy_port}:{type(exc).__name__}")
        detail = ",".join(failures) or "no_tor_ports"
        raise ExternalTransportError(
            f"No configured local Tor SOCKS endpoint completed the request ({detail})."
        )


class ExternalAccessGateway:
    """Authorize, fetch, audit, and capture external bytes before semantic use."""

    _MAX_REDIRECTS = 5

    def __init__(
        self,
        *,
        database: SQLiteDatabase,
        chat: ChatService,
        sources: SourceCaptureService,
        paths: RuntimePaths,
        transports: Mapping[str, ExternalTransport] | None = None,
    ) -> None:
        self.database = database
        self.chat = chat
        self.sources = sources
        self.paths = paths
        self.transports: dict[str, ExternalTransport] = dict(
            transports
            or {
                "tor": TorSocksTransport(),
                "direct_explicit": DirectExplicitTransport(),
            }
        )

    def authorize_explicit(
        self,
        *,
        purpose: str,
        allowed_hosts: Sequence[str],
        privacy_route: str = "tor_preferred",
        ttl_seconds: int = 1800,
    ) -> ExternalAccessAuthorizationRecord:
        normalized_purpose = purpose.strip()
        if not normalized_purpose:
            raise ExternalAuthorizationError("External access purpose must not be empty.")
        valid_routes = {"tor_preferred", "tor", "direct_explicit"}
        if privacy_route not in valid_routes:
            raise ExternalAuthorizationError(
                f"Privacy route {privacy_route!r} is unsupported."
            )
        transport_route = "tor" if privacy_route == "tor_preferred" else privacy_route
        if transport_route not in self.transports:
            raise ExternalAuthorizationError(
                f"Privacy route {privacy_route!r} is unavailable; refusing fallback."
            )
        if ttl_seconds < 1 or ttl_seconds > 86_400:
            raise ExternalAuthorizationError(
                "Explicit external authorization TTL must be between 1 and 86400 seconds."
            )
        hosts = tuple(sorted({_normalize_host(item) for item in allowed_hosts}))
        if not hosts:
            raise ExternalAuthorizationError("At least one allowed external host is required.")
        for host in hosts:
            _reject_unsafe_literal_or_name(host)

        actor_id = self.chat.ensure_local_user()
        authorization_id = new_uuid7()
        created_at_us = utc_now_us()
        expires_at_us = created_at_us + ttl_seconds * 1_000_000
        with self.database.write_transaction() as connection:
            connection.execute(
                """
                INSERT INTO external_access_authorizations (
                    authorization_id, actor_id, purpose, allowed_hosts_json,
                    privacy_route, origin, expires_at_us, revoked_at_us, created_at_us
                ) VALUES (?, ?, ?, ?, ?, 'explicit_user', ?, NULL, ?)
                """,
                (
                    uuid_to_blob(authorization_id),
                    uuid_to_blob(actor_id),
                    normalized_purpose,
                    _canonical_json(list(hosts)),
                    privacy_route,
                    expires_at_us,
                    created_at_us,
                ),
            )
        return self.get_authorization(authorization_id)

    def authorize_direct_fallback(
        self,
        authorization_id: uuid.UUID,
        *,
        host: str,
        ttl_seconds: int = 900,
    ) -> ExternalAccessAuthorizationRecord:
        """Create a separate explicit Direct authorization from an active Tor-Preferred grant."""
        source = self.get_authorization(authorization_id)
        actor_id = self.chat.ensure_local_user()
        now_us = utc_now_us()
        if source.actor_id != actor_id:
            raise ExternalAuthorizationError(
                "Direct fallback authorization belongs to another actor."
            )
        if source.privacy_route != "tor_preferred":
            raise ExternalAuthorizationError(
                "Direct fallback approval can only originate from Tor Preferred."
            )
        if source.revoked_at_us is not None or source.expires_at_us <= now_us:
            raise ExternalAuthorizationError(
                "The Tor Preferred authorization is no longer active."
            )
        normalized_host = _normalize_host(host)
        allowed_hosts = set(_string_array(source.allowed_hosts_json))
        if normalized_host not in allowed_hosts:
            raise ExternalAuthorizationError(
                "Direct fallback host is outside the original Tor authorization."
            )
        _reject_unsafe_literal_or_name(normalized_host)
        remaining_seconds = (source.expires_at_us - now_us) // 1_000_000
        effective_ttl = min(ttl_seconds, int(remaining_seconds), 900)
        if effective_ttl < 1:
            raise ExternalAuthorizationError(
                "Direct fallback authorization would already be expired."
            )
        return self.authorize_explicit(
            purpose=source.purpose + " [explicit direct fallback]",
            allowed_hosts=(normalized_host,),
            privacy_route="direct_explicit",
            ttl_seconds=effective_ttl,
        )

    def revoke(self, authorization_id: uuid.UUID) -> ExternalAccessAuthorizationRecord:
        now_us = utc_now_us()
        with self.database.write_transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE external_access_authorizations
                SET revoked_at_us = COALESCE(revoked_at_us, ?)
                WHERE authorization_id = ?
                """,
                (now_us, uuid_to_blob(authorization_id)),
            )
            if cursor.rowcount != 1:
                raise ExternalAuthorizationError(
                    f"External authorization {authorization_id} not found."
                )
        return self.get_authorization(authorization_id)

    def get_authorization(
        self,
        authorization_id: uuid.UUID,
    ) -> ExternalAccessAuthorizationRecord:
        row = self.database.connection.execute(
            "SELECT * FROM external_access_authorizations WHERE authorization_id = ?",
            (uuid_to_blob(authorization_id),),
        ).fetchone()
        if row is None:
            raise ExternalAuthorizationError(
                f"External authorization {authorization_id} not found."
            )
        return ExternalAccessAuthorizationRecord(
            authorization_id=uuid_from_blob(bytes(row["authorization_id"])),
            actor_id=uuid_from_blob(bytes(row["actor_id"])),
            purpose=str(row["purpose"]),
            allowed_hosts_json=str(row["allowed_hosts_json"]),
            privacy_route=str(row["privacy_route"]),
            origin=str(row["origin"]),
            expires_at_us=int(row["expires_at_us"]),
            revoked_at_us=(
                int(row["revoked_at_us"]) if row["revoked_at_us"] is not None else None
            ),
            created_at_us=int(row["created_at_us"]),
        )

    def capture_url(
        self,
        authorization_id: uuid.UUID,
        url: str,
        *,
        max_bytes: int = 8 * 1024 * 1024,
        timeout_seconds: float = 30.0,
    ) -> SourceCaptureResult:
        if max_bytes < 1 or max_bytes > 128 * 1024 * 1024:
            raise ValueError("External response max_bytes is outside the safe v1 range.")
        if timeout_seconds <= 0 or timeout_seconds > 300:
            raise ValueError("External timeout must be in (0, 300] seconds.")

        authorization = self._authorized_or_audit(
            authorization_id,
            url=url,
        )
        transport_route = (
            "tor" if authorization.privacy_route == "tor_preferred"
            else authorization.privacy_route
        )
        transport = self.transports.get(transport_route)
        if transport is None:
            self._audit(
                authorization,
                url=url,
                outcome="denied",
                reason_code="privacy_route_unavailable",
                response_bytes=None,
                source_id=None,
            )
            raise ExternalAuthorizationError(
                "Configured privacy route is unavailable; no direct fallback is permitted."
            )

        current_url = url
        for redirect_count in range(self._MAX_REDIRECTS + 1):
            authorization = self._authorized_or_audit(
                authorization_id,
                url=current_url,
            )
            response = self._fetch_authorized_url(
                authorization,
                transport=transport,
                url=current_url,
                max_bytes=max_bytes,
                timeout_seconds=timeout_seconds,
            )
            if response.status in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if not location:
                    self._audit(
                        authorization,
                        url=current_url,
                        outcome="failed",
                        reason_code="redirect_without_location",
                        response_bytes=len(response.body),
                        source_id=None,
                    )
                    raise ExternalTransportError("Redirect response has no Location header.")
                if redirect_count >= self._MAX_REDIRECTS:
                    raise ExternalTransportError("External redirect limit exceeded.")
                current_url = urljoin(current_url, location)
                continue
            if response.status < 200 or response.status >= 300:
                reason_code = f"http_{response.status}"
                self._audit(
                    authorization,
                    url=current_url,
                    outcome="failed",
                    reason_code=reason_code,
                    response_bytes=len(response.body),
                    source_id=None,
                )
                raise ExternalTransportError(
                    f"External server returned HTTP {response.status}."
                )
            if len(response.body) > max_bytes:
                self._audit(
                    authorization,
                    url=current_url,
                    outcome="failed",
                    reason_code="response_too_large",
                    response_bytes=len(response.body),
                    source_id=None,
                )
                raise ExternalResponsePolicyError(
                    "External response exceeded configured body limit."
                )
            self._require_authorized(authorization_id, url=response.final_url)
            break
        else:
            raise ExternalTransportError("External redirect processing failed.")

        extension = _extension_for_content_type(response.headers.get("content-type"))
        temp_dir = self.paths.temp_root / "external-capture"
        temp_dir.mkdir(parents=True, exist_ok=True)
        staging = temp_dir / f"{new_uuid7()}{extension}"
        try:
            with staging.open("xb") as handle:
                handle.write(response.body)
                handle.flush()
                os.fsync(handle.fileno())
            source_uri = _provenance_url(response.final_url)

            def finalize_external_capture(
                connection: sqlite3.Connection,
                source_id: uuid.UUID,
            ) -> None:
                event_id = self._insert_audit_event(
                    connection,
                    authorization,
                    url=response.final_url,
                    outcome="captured",
                    reason_code=None,
                    response_bytes=len(response.body),
                    source_id=source_id,
                )
                self._insert_external_source_capture(
                    connection,
                    source_id=source_id,
                    authorization_id=authorization.authorization_id,
                    access_event_id=event_id,
                    provenance_url=source_uri,
                    captured_at_us=utc_now_us(),
                )

            result = self.sources.capture_external_snapshot(
                staging,
                source_uri=source_uri,
                original_name=_external_name(
                    response.final_url,
                    extension,
                ),
                transactional_finalize=finalize_external_capture,
            )
        finally:
            staging.unlink(missing_ok=True)

        return result

    def _fetch_authorized_url(
        self,
        authorization: ExternalAccessAuthorizationRecord,
        *,
        transport: ExternalTransport,
        url: str,
        max_bytes: int,
        timeout_seconds: float,
    ) -> ExternalResponse:
        attempts = 2 if authorization.privacy_route == "tor_preferred" else 1
        last_transport_error: BaseException | None = None
        for attempt in range(attempts):
            try:
                response = transport.fetch(
                    url,
                    max_bytes=max_bytes,
                    timeout_seconds=timeout_seconds,
                )
            except ExternalDestinationError as exc:
                self._audit(
                    authorization,
                    url=url,
                    outcome="denied",
                    reason_code=type(exc).__name__,
                    response_bytes=None,
                    source_id=None,
                )
                raise
            except ExternalResponsePolicyError:
                # Size/content/encoding policy failures are not evidence that
                # Tor is blocked and must never expose the normal IP.
                self._audit(
                    authorization,
                    url=url,
                    outcome="failed",
                    reason_code="response_policy_failed",
                    response_bytes=None,
                    source_id=None,
                )
                raise
            except (ExternalTransportError, OSError) as exc:
                last_transport_error = exc
                if authorization.privacy_route == "tor_preferred" and attempt + 1 < attempts:
                    self._audit(
                        authorization,
                        url=url,
                        outcome="failed",
                        reason_code=f"tor_transport_retry_{attempt + 1}",
                        response_bytes=None,
                        source_id=None,
                    )
                    continue
                if authorization.privacy_route == "tor_preferred":
                    reason_code = "tor_transport_failed_direct_approval_required"
                    self._audit(
                        authorization,
                        url=url,
                        outcome="failed",
                        reason_code=reason_code,
                        response_bytes=None,
                        source_id=None,
                    )
                    raise ExternalDirectApprovalRequired(
                        url=url,
                        reason_code=reason_code,
                    ) from exc
                self._audit(
                    authorization,
                    url=url,
                    outcome="failed",
                    reason_code="transport_failed",
                    response_bytes=None,
                    source_id=None,
                )
                raise

            blocked_status = response.status in {403, 429, 503}
            challenge = (
                200 <= response.status < 300
                and _looks_like_access_challenge(response)
            )
            if challenge and authorization.privacy_route != "tor_preferred":
                self._audit(
                    authorization,
                    url=url,
                    outcome="failed",
                    reason_code="access_challenge_response",
                    response_bytes=len(response.body),
                    source_id=None,
                )
                raise ExternalResponsePolicyError(
                    "External response is an access challenge, not source evidence."
                )
            if (
                authorization.privacy_route == "tor_preferred"
                and (blocked_status or challenge)
            ):
                reason = (
                    f"tor_blocked_http_{response.status}"
                    if blocked_status
                    else "tor_access_challenge"
                )
                if attempt + 1 < attempts:
                    self._audit(
                        authorization,
                        url=url,
                        outcome="failed",
                        reason_code=reason + "_retry",
                        response_bytes=len(response.body),
                        source_id=None,
                    )
                    continue
                reason_code = reason + "_direct_approval_required"
                self._audit(
                    authorization,
                    url=url,
                    outcome="failed",
                    reason_code=reason_code,
                    response_bytes=len(response.body),
                    source_id=None,
                )
                raise ExternalDirectApprovalRequired(
                    url=url,
                    reason_code=reason_code,
                )
            return response

        if last_transport_error is not None:
            raise ExternalTransportError(
                "External transport attempts ended without a safe response."
            ) from last_transport_error
        raise ExternalTransportError(
            "External transport attempts ended without a safe response."
        )

    def _authorized_or_audit(
        self,
        authorization_id: uuid.UUID,
        *,
        url: str,
    ) -> ExternalAccessAuthorizationRecord:
        try:
            return self._require_authorized(authorization_id, url=url)
        except ExternalAccessError as exc:
            try:
                authorization = self.get_authorization(authorization_id)
            except ExternalAuthorizationError:
                raise
            self._audit(
                authorization,
                url=url,
                outcome="denied",
                reason_code=type(exc).__name__,
                response_bytes=None,
                source_id=None,
            )
            raise

    def _require_authorized(
        self,
        authorization_id: uuid.UUID,
        *,
        url: str,
    ) -> ExternalAccessAuthorizationRecord:
        authorization = self.get_authorization(authorization_id)
        actor_id = self.chat.ensure_local_user()
        now_us = utc_now_us()
        if authorization.actor_id != actor_id:
            raise ExternalAuthorizationError(
                "External authorization belongs to another actor."
            )
        if authorization.revoked_at_us is not None:
            raise ExternalAuthorizationError("External authorization was revoked.")
        if authorization.expires_at_us <= now_us:
            raise ExternalAuthorizationError("External authorization expired.")
        if authorization.origin != "explicit_user":
            raise ExternalAuthorizationError("External authorization origin is invalid.")

        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"}:
            raise ExternalDestinationError("Only HTTP(S) external URLs are permitted.")
        if parsed.username is not None or parsed.password is not None:
            raise ExternalDestinationError("Credentials in external URLs are prohibited.")
        if parsed.fragment:
            parsed = parsed._replace(fragment="")
        host = parsed.hostname
        if host is None:
            raise ExternalDestinationError("External URL has no hostname.")
        normalized = _normalize_host(host)
        allowed = set(_string_array(authorization.allowed_hosts_json))
        if normalized not in allowed:
            raise ExternalAuthorizationError(
                f"Destination host {normalized!r} is outside authorization scope."
            )
        _reject_unsafe_literal_or_name(normalized)
        port = parsed.port or _default_port(parsed.scheme)
        if port != _default_port(parsed.scheme):
            raise ExternalDestinationError(
                "ATHENA v1 external access permits only the default HTTP/HTTPS ports."
            )
        return authorization

    def _audit(
        self,
        authorization: ExternalAccessAuthorizationRecord,
        *,
        url: str,
        outcome: str,
        reason_code: str | None,
        response_bytes: int | None,
        source_id: uuid.UUID | None,
    ) -> uuid.UUID:
        """Persist one independently durable failed/denied audit event."""

        with self.database.write_transaction() as connection:
            return self._insert_audit_event(
                connection,
                authorization,
                url=url,
                outcome=outcome,
                reason_code=reason_code,
                response_bytes=response_bytes,
                source_id=source_id,
            )

    def _insert_audit_event(
        self,
        connection: sqlite3.Connection,
        authorization: ExternalAccessAuthorizationRecord,
        *,
        url: str,
        outcome: str,
        reason_code: str | None,
        response_bytes: int | None,
        source_id: uuid.UUID | None,
    ) -> uuid.UUID:
        """Insert one audit event in the caller-owned transaction."""

        event_id = new_uuid7()
        parsed = urlsplit(url)
        host = parsed.hostname or "<invalid>"
        url_hash = hashlib.sha256(
            url.encode("utf-8")
        ).digest()
        event_now_us = utc_now_us()

        previous = connection.execute(
            """
            SELECT MAX(created_at_us) AS created_at_us
            FROM external_access_events
            WHERE authorization_id = ?
            """,
            (
                uuid_to_blob(
                    authorization.authorization_id
                ),
            ),
        ).fetchone()

        previous_created_at_us = (
            None
            if (
                previous is None
                or previous["created_at_us"] is None
            )
            else int(
                previous["created_at_us"]
            )
        )

        event_created_at_us = (
            event_now_us
            if previous_created_at_us is None
            else max(
                event_now_us,
                previous_created_at_us + 1,
            )
        )

        connection.execute(
            """
            INSERT INTO external_access_events (
                event_id,
                authorization_id,
                request_url_hash,
                destination_host,
                method,
                privacy_route,
                outcome,
                reason_code,
                response_bytes,
                source_id,
                created_at_us
            ) VALUES (?, ?, ?, ?, 'GET', ?, ?, ?, ?, ?, ?)
            """,
            (
                uuid_to_blob(event_id),
                uuid_to_blob(
                    authorization.authorization_id
                ),
                url_hash,
                host.lower(),
                authorization.privacy_route,
                outcome,
                reason_code,
                response_bytes,
                (
                    uuid_to_blob(source_id)
                    if source_id is not None
                    else None
                ),
                event_created_at_us,
            ),
        )

        return event_id

    @staticmethod
    def _insert_external_source_capture(
        connection: sqlite3.Connection,
        *,
        source_id: uuid.UUID,
        authorization_id: uuid.UUID,
        access_event_id: uuid.UUID,
        provenance_url: str,
        captured_at_us: int,
    ) -> None:
        """Insert external Source provenance in the caller transaction."""

        connection.execute(
            """
            INSERT INTO external_source_captures (
                source_id,
                authorization_id,
                access_event_id,
                provenance_url,
                captured_at_us
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                uuid_to_blob(source_id),
                uuid_to_blob(authorization_id),
                uuid_to_blob(access_event_id),
                provenance_url,
                captured_at_us,
            ),
        )


class ExternalResearchService:
    """Capture explicit external URLs first, then freeze them through normal local Research."""

    def __init__(
        self,
        *,
        gateway: ExternalAccessGateway,
        research: ResearchService,
    ) -> None:
        self.gateway = gateway
        self.research = research

    def enqueue(
        self,
        *,
        query: str,
        authorization_id: uuid.UUID,
        urls: Sequence[str],
        requested_model_id: str | None = None,
        context_limit: int | None = None,
        output_reserve: int | None = None,
        safety_margin: int | None = None,
    ) -> JobRecord:
        normalized_urls = tuple(item.strip() for item in urls if item.strip())
        if not normalized_urls:
            raise ExternalAccessError("External Research requires at least one URL.")
        source_ids = tuple(
            self.gateway.capture_url(authorization_id, url).source.source_id
            for url in normalized_urls
        )
        return self.research.enqueue_local(
            query=query,
            explicit_source_ids=source_ids,
            requested_model_id=requested_model_id,
            context_limit=context_limit,
            output_reserve=output_reserve,
            safety_margin=safety_margin,
        )


def _http_over_socket(
    sock: socket.socket,
    *,
    url: str,
    max_bytes: int,
    timeout_seconds: float,
) -> ExternalResponse:
    parsed = urlsplit(url)
    host = parsed.hostname
    if host is None:
        raise ExternalDestinationError("External URL has no host.")
    host = _normalize_host(host)
    raw_sock: socket.socket = sock
    wrapped: ssl.SSLSocket | None = None
    try:
        if parsed.scheme == "https":
            context = ssl.create_default_context()
            wrapped = context.wrap_socket(sock, server_hostname=host)
            raw_sock = wrapped
        elif parsed.scheme != "http":
            raise ExternalDestinationError("Only HTTP(S) external URLs are supported.")
        raw_sock.settimeout(timeout_seconds)
        path = quote(
            parsed.path or "/",
            safe="/%:@!$&'()*+,;=-._~",
        )
        if parsed.query:
            path += "?" + quote(
                parsed.query,
                safe="=&;%:+,/?@!$'()*-._~",
            )
        port = parsed.port or _default_port(parsed.scheme)
        host_literal = f"[{host}]" if ":" in host else host
        host_header = host_literal
        if port != _default_port(parsed.scheme):
            host_header = f"{host_literal}:{port}"
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host_header}\r\n"
            "User-Agent: ATHENA/0.0.1 ExternalAccessGateway\r\n"
            "Accept: */*\r\n"
            "Accept-Encoding: identity\r\n"
            "Connection: close\r\n\r\n"
        ).encode("ascii")
        raw_sock.sendall(request)
        response = http.client.HTTPResponse(raw_sock)
        response.begin()
        headers = {key.lower(): value for key, value in response.getheaders()}
        encoding = headers.get("content-encoding", "identity").strip().lower()
        if encoding not in {"", "identity"}:
            raise ExternalResponsePolicyError(
                f"Unexpected compressed response encoding {encoding!r}; refusing hidden expansion."
            )
        body = response.read(max_bytes + 1)
        if len(body) > max_bytes:
            raise ExternalResponsePolicyError(
                "External response exceeded configured body limit."
            )
        return ExternalResponse(
            final_url=url,
            status=response.status,
            headers=headers,
            body=body,
        )
    finally:
        if wrapped is not None:
            wrapped.close()


def _recv_exact(sock: socket.socket, length: int) -> bytes:
    data = bytearray()
    while len(data) < length:
        chunk = sock.recv(length - len(data))
        if not chunk:
            raise ExternalTransportError("SOCKS5 connection closed unexpectedly.")
        data.extend(chunk)
    return bytes(data)


def _default_port(scheme: str) -> int:
    if scheme == "https":
        return 443
    if scheme == "http":
        return 80
    raise ExternalDestinationError("Unsupported external URL scheme.")


def _normalize_host(value: str) -> str:
    normalized = value.strip().rstrip(".").lower()
    if not normalized:
        raise ExternalDestinationError("External host must not be empty.")
    try:
        return normalized.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ExternalDestinationError("External hostname is invalid.") from exc


def _reject_unsafe_literal_or_name(host: str) -> None:
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        raise ExternalDestinationError("Local-network destination is prohibited.")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return
    if not address.is_global:
        raise ExternalDestinationError("Non-global IP destinations are prohibited.")


def _connect_direct_validated(
    host: str,
    port: int,
    *,
    timeout_seconds: float,
) -> socket.socket:
    _reject_unsafe_literal_or_name(host)
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ExternalDestinationError(
            f"Cannot safely resolve direct destination {host!r}."
        ) from exc
    if not infos:
        raise ExternalDestinationError("Direct destination resolved to no address.")
    for _family, _socktype, _proto, _canonname, sockaddr in infos:
        address = ipaddress.ip_address(str(sockaddr[0]).split("%", 1)[0])
        if not address.is_global:
            raise ExternalDestinationError(
                "Direct destination resolves to a non-global address."
            )

    failures: list[OSError] = []
    for family, socktype, proto, _canonname, sockaddr in infos:
        sock = socket.socket(family, socktype, proto)
        try:
            sock.settimeout(timeout_seconds)
            sock.connect(sockaddr)
            return sock
        except OSError as exc:
            failures.append(exc)
            sock.close()
    if failures:
        raise ExternalTransportError(
            f"Direct destination {host!r} could not be connected safely."
        ) from failures[-1]
    raise ExternalTransportError("Direct destination has no connectable safe address.")


def _looks_like_access_challenge(response: ExternalResponse) -> bool:
    if response.headers.get("cf-mitigated", "").strip().lower() == "challenge":
        return True
    content_type = response.headers.get("content-type", "").lower()
    if "text/html" not in content_type:
        return False
    sample = response.body[:256_000].lower()
    strong_markers = (
        b"challenges.cloudflare.com",
        b"cf-chl-",
        b"data-sitekey=",
        b"hcaptcha.com/1/api.js",
        b"recaptcha/api.js",
    )
    if any(marker in sample for marker in strong_markers):
        return True
    return (
        b"verify you are human" in sample
        and (b"captcha" in sample or b"cloudflare" in sample)
    )


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _string_array(value: str) -> tuple[str, ...]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ExternalAuthorizationError("Authorization host scope is invalid JSON.") from exc
    if not isinstance(parsed, list) or any(not isinstance(item, str) for item in parsed):
        raise ExternalAuthorizationError("Authorization host scope is invalid.")
    return tuple(parsed)


_SENSITIVE_QUERY_KEYS = frozenset(
    {
        "token", "access_token", "refresh_token", "key", "api_key", "apikey",
        "secret", "client_secret", "password", "auth", "authorization",
        "signature", "sig", "x-amz-signature", "session", "session_id",
        "code", "jwt",
    }
)


def _provenance_url(url: str) -> str:
    parsed = urlsplit(url)
    query = [
        (key, "[REDACTED]" if key.lower() in _SENSITIVE_QUERY_KEYS else value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
    ]
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urlencode(query),
            "",
        )
    )


def _extension_for_content_type(value: str | None) -> str:
    if value is None:
        return ".bin"
    media_type = value.split(";", 1)[0].strip().lower()
    return {
        "text/html": ".html",
        "text/plain": ".txt",
        "application/pdf": ".pdf",
        "application/json": ".json",
    }.get(media_type, ".bin")


def _external_name(url: str, extension: str) -> str:
    parsed = urlsplit(url)
    name = Path(parsed.path).name
    if not name:
        return f"external-snapshot{extension}"
    if "." not in name and extension:
        return name + extension
    return name
