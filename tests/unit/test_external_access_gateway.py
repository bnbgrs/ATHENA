from __future__ import annotations

from pathlib import Path

import pytest

from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.external.gateway import (
    ExternalAuthorizationError,
    ExternalDestinationError,
    ExternalDirectApprovalRequired,
    ExternalResponse,
    ExternalResponsePolicyError,
)
from athena.source.models import SourceType


class _Transport:
    def fetch(self, url: str, *, max_bytes: int, timeout_seconds: float) -> ExternalResponse:
        del max_bytes, timeout_seconds
        return ExternalResponse(
            final_url=url,
            status=200,
            headers={"content-type": "text/html; charset=utf-8"},
            body=b"<html><body>captured external evidence</body></html>",
        )


def test_external_capture_requires_explicit_scope_and_becomes_raw_source(
    tmp_path: Path,
) -> None:
    app = AthenaApplication(settings=AthenaSettings(local_root=tmp_path / "runtime"))
    app.start()
    app.external_access.transports["direct_explicit"] = _Transport()
    authorization = app.external_access.authorize_explicit(
        purpose="test evidence capture",
        allowed_hosts=("example.com",),
        privacy_route="direct_explicit",
    )

    result = app.external_access.capture_url(
        authorization.authorization_id,
        "https://example.com/report?token=secret&topic=athena",
    )
    assert result.source.source_type is SourceType.WEB_SNAPSHOT
    assert result.source.source_uri is not None
    assert "secret" not in result.source.source_uri
    assert "%5BREDACTED%5D" in result.source.source_uri

    capture = app.database.connection.execute(
        "SELECT provenance_url FROM external_source_captures WHERE source_id = ?",
        (result.source.source_id.bytes,),
    ).fetchone()
    assert capture is not None
    assert "secret" not in str(capture["provenance_url"])

    with pytest.raises(ExternalAuthorizationError):
        app.external_access.capture_url(
            authorization.authorization_id,
            "https://example.org/not-authorized",
        )

    app.external_access.revoke(authorization.authorization_id)
    with pytest.raises(ExternalAuthorizationError):
        app.external_access.capture_url(
            authorization.authorization_id,
            "https://example.com/after-revoke",
        )
    app.stop()

class _BlockedTorTransport:
    def __init__(self) -> None:
        self.calls = 0

    def fetch(
        self,
        url: str,
        *,
        max_bytes: int,
        timeout_seconds: float,
    ) -> ExternalResponse:
        del max_bytes, timeout_seconds
        self.calls += 1
        return ExternalResponse(
            final_url=url,
            status=403,
            headers={"content-type": "text/html"},
            body=b"tor exit blocked",
        )


class _DirectTrapTransport:
    def __init__(self) -> None:
        self.called = False

    def fetch(
        self,
        url: str,
        *,
        max_bytes: int,
        timeout_seconds: float,
    ) -> ExternalResponse:
        del url, max_bytes, timeout_seconds
        self.called = True
        raise AssertionError("Direct transport must never be a silent Tor fallback.")


def test_tor_preferred_requires_separate_explicit_direct_authorization(
    tmp_path: Path,
) -> None:
    app = AthenaApplication(settings=AthenaSettings(local_root=tmp_path / "runtime"))
    app.start()
    trap = _DirectTrapTransport()
    blocked = _BlockedTorTransport()
    app.external_access.transports["tor"] = blocked
    app.external_access.transports["direct_explicit"] = trap
    authorization = app.external_access.authorize_explicit(
        purpose="tor preferred test",
        allowed_hosts=("example.com",),
    )
    assert authorization.privacy_route == "tor_preferred"

    with pytest.raises(ExternalDirectApprovalRequired) as exc_info:
        app.external_access.capture_url(
            authorization.authorization_id,
            "https://example.com/blocked",
        )
    assert "direct_approval_required" in exc_info.value.reason_code
    assert blocked.calls == 2
    assert trap.called is False

    direct_authorization = app.external_access.authorize_direct_fallback(
        authorization.authorization_id,
        host="example.com",
        ttl_seconds=300,
    )
    assert direct_authorization.privacy_route == "direct_explicit"
    assert direct_authorization.authorization_id != authorization.authorization_id
    assert direct_authorization.allowed_hosts_json == '["example.com"]'
    with pytest.raises(ExternalAuthorizationError):
        app.external_access.authorize_direct_fallback(
            authorization.authorization_id,
            host="example.org",
            ttl_seconds=300,
        )
    app.external_access.transports["direct_explicit"] = _Transport()
    direct_result = app.external_access.capture_url(
        direct_authorization.authorization_id,
        "https://example.com/blocked",
    )
    assert direct_result.source.source_type is SourceType.WEB_SNAPSHOT

    event = app.database.connection.execute(
        """
        SELECT privacy_route, outcome, reason_code
        FROM external_access_events
        WHERE authorization_id = ?
        ORDER BY created_at_us DESC
        LIMIT 1
        """,
        (authorization.authorization_id.bytes,),
    ).fetchone()
    assert event is not None
    assert event["privacy_route"] == "tor_preferred"
    assert event["outcome"] == "failed"
    assert "direct_approval_required" in str(event["reason_code"])
    app.stop()



class _ChallengeTorTransport:
    def __init__(self) -> None:
        self.calls = 0

    def fetch(
        self,
        url: str,
        *,
        max_bytes: int,
        timeout_seconds: float,
    ) -> ExternalResponse:
        del max_bytes, timeout_seconds
        self.calls += 1
        return ExternalResponse(
            final_url=url,
            status=200,
            headers={"content-type": "text/html", "cf-mitigated": "challenge"},
            body=b"<html>verify you are human</html>",
        )


def test_tor_preferred_detects_http_200_challenge(tmp_path: Path) -> None:
    app = AthenaApplication(settings=AthenaSettings(local_root=tmp_path / "challenge-runtime"))
    app.start()
    challenge = _ChallengeTorTransport()
    app.external_access.transports["tor"] = challenge
    authorization = app.external_access.authorize_explicit(
        purpose="challenge test",
        allowed_hosts=("example.com",),
    )
    with pytest.raises(ExternalDirectApprovalRequired) as exc_info:
        app.external_access.capture_url(
            authorization.authorization_id,
            "https://example.com/challenge",
        )
    assert exc_info.value.reason_code == "tor_access_challenge_direct_approval_required"
    assert challenge.calls == 2
    app.stop()


def test_direct_authorization_rejects_non_default_web_port(tmp_path: Path) -> None:
    app = AthenaApplication(settings=AthenaSettings(local_root=tmp_path / "port-runtime"))
    app.start()
    app.external_access.transports["direct_explicit"] = _Transport()
    authorization = app.external_access.authorize_explicit(
        purpose="port scope test",
        allowed_hosts=("example.com",),
        privacy_route="direct_explicit",
    )
    with pytest.raises(ExternalDestinationError):
        app.external_access.capture_url(
            authorization.authorization_id,
            "https://example.com:8443/report",
        )
    app.stop()


class _PolicyFailureTorTransport:
    def fetch(
        self,
        url: str,
        *,
        max_bytes: int,
        timeout_seconds: float,
    ) -> ExternalResponse:
        del url, max_bytes, timeout_seconds
        raise ExternalResponsePolicyError("synthetic response policy failure")


def test_tor_response_policy_failure_does_not_request_direct_fallback(
    tmp_path: Path,
) -> None:
    app = AthenaApplication(settings=AthenaSettings(local_root=tmp_path / "policy-runtime"))
    app.start()
    app.external_access.transports["tor"] = _PolicyFailureTorTransport()
    authorization = app.external_access.authorize_explicit(
        purpose="response policy test",
        allowed_hosts=("example.com",),
    )
    with pytest.raises(ExternalResponsePolicyError):
        app.external_access.capture_url(
            authorization.authorization_id,
            "https://example.com/large",
        )
    app.stop()

def test_direct_access_challenge_is_not_captured_as_source_evidence(
    tmp_path: Path,
) -> None:
    app = AthenaApplication(settings=AthenaSettings(local_root=tmp_path / "direct-challenge"))
    app.start()
    app.external_access.transports["direct_explicit"] = _ChallengeTorTransport()
    authorization = app.external_access.authorize_explicit(
        purpose="direct challenge policy test",
        allowed_hosts=("example.com",),
        privacy_route="direct_explicit",
    )
    before = len(app.sources.list())
    with pytest.raises(ExternalResponsePolicyError, match="access challenge"):
        app.external_access.capture_url(
            authorization.authorization_id,
            "https://example.com/challenge",
        )
    assert len(app.sources.list()) == before
    app.stop()

def test_external_audit_order_is_strict_with_coarse_clock(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = AthenaApplication(
        settings=AthenaSettings(local_root=tmp_path / "coarse-clock-runtime")
    )
    app.start()
    blocked = _BlockedTorTransport()
    app.external_access.transports["tor"] = blocked

    authorization = app.external_access.authorize_explicit(
        purpose="coarse clock audit ordering",
        allowed_hosts=("example.com",),
    )

    fixed_now = authorization.created_at_us + 1
    monkeypatch.setattr(
        "athena.external.gateway.utc_now_us",
        lambda: fixed_now,
    )

    with pytest.raises(ExternalDirectApprovalRequired):
        app.external_access.capture_url(
            authorization.authorization_id,
            "https://example.com/blocked",
        )

    events = app.database.connection.execute(
        """
        SELECT reason_code, created_at_us
        FROM external_access_events
        WHERE authorization_id = ?
        ORDER BY created_at_us ASC
        """,
        (authorization.authorization_id.bytes,),
    ).fetchall()

    assert len(events) == 2
    assert events[0]["reason_code"] == "tor_blocked_http_403_retry"
    assert "direct_approval_required" in str(events[1]["reason_code"])
    assert int(events[1]["created_at_us"]) > int(events[0]["created_at_us"])
    app.stop()



def test_external_capture_finalization_rolls_back_source_audit_and_link(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = AthenaApplication(
        settings=AthenaSettings(
            local_root=tmp_path / "atomic-finalization-runtime"
        )
    )
    app.start()

    try:
        app.external_access.transports[
            "direct_explicit"
        ] = _Transport()

        authorization = app.external_access.authorize_explicit(
            purpose="atomic external capture",
            allowed_hosts=("example.com",),
            privacy_route="direct_explicit",
        )

        tables = (
            "blob_records",
            "sources",
            "commit_records",
            "entity_registry",
            "provenance_records",
            "external_access_events",
            "external_source_captures",
        )

        before = {
            table: int(
                app.database.connection.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
            )
            for table in tables
        }

        def fail_external_source_link(
            connection: object,
            **kwargs: object,
        ) -> None:
            del connection, kwargs
            raise RuntimeError(
                "synthetic external capture link failure"
            )

        monkeypatch.setattr(
            app.external_access,
            "_insert_external_source_capture",
            fail_external_source_link,
        )

        with pytest.raises(
            RuntimeError,
            match="synthetic external capture link failure",
        ):
            app.external_access.capture_url(
                authorization.authorization_id,
                "https://example.com/atomic-finalization",
            )

        after = {
            table: int(
                app.database.connection.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
            )
            for table in tables
        }

        assert after == before
        assert app.database.connection.in_transaction is False

        assert (
            app.external_access.get_authorization(
                authorization.authorization_id
            ).authorization_id
            == authorization.authorization_id
        )

    finally:
        app.stop()


def test_successful_external_capture_has_complete_atomic_provenance_triplet(
    tmp_path: Path,
) -> None:
    app = AthenaApplication(
        settings=AthenaSettings(
            local_root=tmp_path / "atomic-success-runtime"
        )
    )
    app.start()

    try:
        app.external_access.transports[
            "direct_explicit"
        ] = _Transport()

        authorization = app.external_access.authorize_explicit(
            purpose="complete external provenance",
            allowed_hosts=("example.com",),
            privacy_route="direct_explicit",
        )

        result = app.external_access.capture_url(
            authorization.authorization_id,
            "https://example.com/complete",
        )

        row = app.database.connection.execute(
            """
            SELECT
                esc.authorization_id,
                esc.access_event_id,
                esc.provenance_url,
                e.source_id,
                e.outcome,
                e.reason_code,
                e.response_bytes
            FROM external_source_captures AS esc
            JOIN external_access_events AS e
              ON e.event_id = esc.access_event_id
            WHERE esc.source_id = ?
            """,
            (
                result.source.source_id.bytes,
            ),
        ).fetchone()

        assert row is not None
        assert (
            bytes(row["authorization_id"])
            == authorization.authorization_id.bytes
        )
        assert (
            bytes(row["source_id"])
            == result.source.source_id.bytes
        )
        assert row["outcome"] == "captured"
        assert row["reason_code"] is None
        assert int(row["response_bytes"]) > 0
        assert "example.com" in str(
            row["provenance_url"]
        )

    finally:
        app.stop()
