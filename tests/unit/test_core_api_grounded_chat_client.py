from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.error import URLError

import pytest

from athena.api import client as client_module
from athena.api.client import CoreApiClient, CoreApiClientError


class _Response:
    def __init__(
        self,
        payload: dict[str, Any],
        *,
        status: int = 200,
    ) -> None:
        self.status = status
        self._raw = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *args: object) -> bool:
        del args
        return False

    def read(self) -> bytes:
        return self._raw


def _bootstrap(runtime_root: Path) -> None:
    runtime_root.mkdir(parents=True, exist_ok=True)
    token_path = runtime_root / "core-api.token"
    token_path.write_text("token-one\n", encoding="ascii")
    (runtime_root / "core-api.json").write_text(
        json.dumps(
            {
                "api_version": "v1",
                "host": "127.0.0.1",
                "port": 32123,
                "token_path": str(token_path),
                "process_id": 1234,
            }
        ),
        encoding="utf-8",
    )


def _payload() -> dict[str, Any]:
    return {
        "thread": {
            "chat_id": "11111111-1111-1111-1111-111111111111",
            "started_at_us": 1,
            "ended_at_us": None,
            "archive_mode": "standard",
            "lifecycle_state": "active",
            "messages": [],
        },
        "assistant_text": "Berlin [CTX-001]",
        "evidence": [
            {
                "context_id": "CTX-001",
                "evidence_class": "canonical",
                "entity_type": "knowledge",
                "entity_id": "44444444-4444-4444-4444-444444444444",
                "revision_id": "55555555-5555-5555-5555-555555555555",
                "title": "Stored capital",
                "text": "Berlin ist die Hauptstadt Deutschlands.",
                "cited": True,
                "epistemic_status": "asserted",
                "source_id": None,
                "representation_id": None,
                "source_name": None,
                "source_uri": None,
                "start_offset": None,
                "end_offset": None,
                "page_start": None,
                "page_end": None,
                "quoted_sha256": None,
                "truncated": False,
            }
        ],
        "personal_memory": [],
        "grounding": {
            "cited_context_ids": ["CTX-001"],
            "canonical_context_ids": ["CTX-001"],
            "user_statement_context_ids": [],
            "conversation_context_ids": [],
            "source_context_ids": [],
            "research_context_ids": [],
            "news_context_ids": [],
            "invalid_context_ids": [],
            "uses_inference": False,
            "uses_model_prior": False,
            "uses_unknown": False,
            "has_provenance_marker": True,
        },
        "processing_run_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        "model_id": "primary-model",
        "embedding_model_id": None,
    }


def test_grounded_client_posts_once_and_parses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_root = tmp_path / "api"
    _bootstrap(runtime_root)
    calls = 0

    def fake_urlopen(
        request: Any,
        timeout: float,
    ) -> _Response:
        nonlocal calls
        calls += 1
        assert timeout == 45.0
        assert request.get_method() == "POST"
        assert request.full_url.endswith(
            "/messages/unified-local"
        )
        assert json.loads(
            request.data.decode("utf-8")
        ) == {
            "content": "hello",
            "model_id": "primary-model",
        }
        return _Response(_payload())

    monkeypatch.setattr(
        client_module,
        "urlopen",
        fake_urlopen,
    )

    client = CoreApiClient(
        runtime_root,
        generation_timeout_seconds=45.0,
    )
    result = client.send_unified_local_chat_message(
        "11111111-1111-1111-1111-111111111111",
        content="hello",
        model_id="primary-model",
    )

    assert calls == 1
    assert result.model_id == "primary-model"
    assert result.evidence[0].evidence_class == "canonical"
    assert result.evidence[0].epistemic_status == "asserted"
    assert result.grounding.cited_context_ids == ("CTX-001",)


def test_grounded_client_never_retries_ambiguous_post(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_root = tmp_path / "api"
    _bootstrap(runtime_root)
    calls = 0

    def fake_urlopen(
        request: Any,
        timeout: float,
    ) -> _Response:
        nonlocal calls
        del request, timeout
        calls += 1
        raise URLError("response lost")

    monkeypatch.setattr(
        client_module,
        "urlopen",
        fake_urlopen,
    )

    client = CoreApiClient(
        runtime_root,
        generation_timeout_seconds=45.0,
    )

    with pytest.raises(
        CoreApiClientError,
        match="unavailable",
    ):
        client.send_unified_local_chat_message(
            "11111111-1111-1111-1111-111111111111",
            content="hello",
        )

    assert calls == 1


def test_grounded_client_rejects_inconsistent_citation_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_root = tmp_path / "api"
    _bootstrap(runtime_root)
    payload = _payload()
    payload["evidence"][0]["cited"] = False

    def fake_urlopen(
        request: Any,
        timeout: float,
    ) -> _Response:
        del request, timeout
        return _Response(payload)

    monkeypatch.setattr(
        client_module,
        "urlopen",
        fake_urlopen,
    )

    client = CoreApiClient(runtime_root)

    with pytest.raises(
        CoreApiClientError,
        match="citation state",
    ):
        client.send_unified_local_chat_message(
            "11111111-1111-1111-1111-111111111111",
            content="hello",
        )


def test_grounded_client_rejects_invalid_canonical_epistemic_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_root = tmp_path / "api"
    _bootstrap(runtime_root)
    payload = _payload()
    payload["evidence"][0]["epistemic_status"] = "verified"

    def fake_urlopen(
        request: Any,
        timeout: float,
    ) -> _Response:
        del request, timeout
        return _Response(payload)

    monkeypatch.setattr(
        client_module,
        "urlopen",
        fake_urlopen,
    )

    client = CoreApiClient(runtime_root)

    with pytest.raises(
        CoreApiClientError,
        match="epistemic status",
    ):
        client.send_unified_local_chat_message(
            "11111111-1111-1111-1111-111111111111",
            content="hello",
        )


def test_grounded_client_requires_epistemic_status_field(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_root = tmp_path / "api"
    _bootstrap(runtime_root)
    payload = _payload()
    del payload["evidence"][0]["epistemic_status"]

    def fake_urlopen(
        request: Any,
        timeout: float,
    ) -> _Response:
        del request, timeout
        return _Response(payload)

    monkeypatch.setattr(
        client_module,
        "urlopen",
        fake_urlopen,
    )

    client = CoreApiClient(runtime_root)

    with pytest.raises(
        CoreApiClientError,
        match="epistemic_status",
    ):
        client.send_unified_local_chat_message(
            "11111111-1111-1111-1111-111111111111",
            content="hello",
        )
