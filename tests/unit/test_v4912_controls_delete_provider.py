from __future__ import annotations

import json
import uuid

import pytest
from PySide6.QtWidgets import QApplication

from athena.api.client import CoreApiClient
from athena.api.contracts import (
    ChatSummaryResponse,
    DeletionResultResponse,
    HealthResponse,
    JsonValue,
    ModelResponse,
    ProviderHealthResponse,
)
from athena.api.service import CoreApiFacade
from athena.desktop.api_controller import DesktopApiSnapshot
from athena.desktop.window import AthenaMainWindow
from athena.lifecycle.service import (
    DeletionDependency,
    DeletionPreview,
    DeletionResult,
)
from athena.model.adapters.lm_studio import LMStudioProvider, ProviderOutputLimitError
from athena.model.domain import ModelInfo, ProviderHealth, ProviderHealthStatus
from athena.observability.health import HealthService

CHAT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
MSG_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
DIGEST = "a" * 64


class _Chat:
    def list_chats(self, *, limit: int = 50):
        return ()

    def create_chat(self):
        return CHAT_ID

    def load_chat(self, chat_id):
        raise AssertionError("not used")


class _Provider:
    @property
    def provider_id(self) -> str:
        return "lm_studio"

    def health(self) -> ProviderHealth:
        return ProviderHealth(status=ProviderHealthStatus.READY)

    def discover_models(self) -> tuple[ModelInfo, ...]:
        return ()


class _Deletion:
    def preview(self, entity_id: uuid.UUID) -> DeletionPreview:
        assert entity_id == CHAT_ID
        return DeletionPreview(
            entity_id=CHAT_ID,
            entity_type="chat",
            lifecycle_state="active",
            dependencies=(
                DeletionDependency(
                    relation="chat.owned_message",
                    count=1,
                    dependent_entity_id=MSG_ID,
                    dependent_entity_type="chat_message",
                ),
            ),
            preview_digest=DIGEST,
        )

    def delete(self, entity_id: uuid.UUID, *, preview_digest: str) -> DeletionResult:
        assert entity_id == CHAT_ID
        assert preview_digest == DIGEST
        return DeletionResult(
            entity_id=CHAT_ID,
            entity_type="chat",
            commit_id=uuid.UUID("33333333-3333-3333-3333-333333333333"),
            deleted_entity_ids=(CHAT_ID, MSG_ID),
            preview_digest=DIGEST,
        )


def test_facade_projects_existing_lifecycle_chat_deletion() -> None:
    health = HealthService()
    health.mark_ok()
    facade = CoreApiFacade(
        health=health,
        chat=_Chat(),  # type: ignore[arg-type]
        model_provider=_Provider(),
        lifecycle_deletion=_Deletion(),  # type: ignore[arg-type]
    )

    preview = facade.preview_chat_deletion(str(CHAT_ID))
    assert preview.entity_type == "chat"
    assert preview.dependencies[0].relation == "chat.owned_message"
    assert preview.dependencies[0].dependent_entity_id == str(MSG_ID)
    assert "chat.delete" in facade.capabilities().features

    result = facade.delete_chat(str(CHAT_ID), preview_digest=preview.preview_digest)
    assert result.entity_id == str(CHAT_ID)
    assert result.deleted_entity_ids == (str(CHAT_ID), str(MSG_ID))


def test_streaming_length_finish_reason_is_not_silent_truncation() -> None:
    payload = json.dumps(
        {
            "choices": [
                {
                    "delta": {},
                    "finish_reason": "length",
                }
            ]
        }
    )
    with pytest.raises(ProviderOutputLimitError, match="output-token limit"):
        LMStudioProvider._parse_chat_chunk(payload)


class _RecordingClient(CoreApiClient):
    def __init__(self, tmp_path) -> None:
        super().__init__(tmp_path)
        self.calls: list[tuple[str, str, dict[str, JsonValue] | None]] = []

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
        del query, expected_status, timeout_seconds
        self.calls.append((method, path, json_body))
        if method == "DELETE":
            return {
                "entity_id": str(CHAT_ID),
                "entity_type": "chat",
                "commit_id": "33333333-3333-3333-3333-333333333333",
                "deleted_entity_ids": [str(CHAT_ID), str(MSG_ID)],
                "preview_digest": DIGEST,
            }
        return {
            "chat_id": str(CHAT_ID),
            "started_at_us": 1,
            "ended_at_us": None,
            "archive_mode": "standard",
            "lifecycle_state": "active",
            "messages": [],
        }


def test_client_transports_selected_model_context_and_delete_once(tmp_path) -> None:
    client = _RecordingClient(tmp_path)
    client.send_chat_message(
        str(CHAT_ID),
        content="hello",
        model_id="model-a",
        effective_context_limit=16384,
    )
    assert client.calls[-1] == (
        "POST",
        f"/api/v1/chats/{CHAT_ID}/messages",
        {
            "content": "hello",
            "model_id": "model-a",
            "effective_context_limit": 16384,
        },
    )

    result = client.delete_chat(str(CHAT_ID), preview_digest=DIGEST)
    assert isinstance(result, DeletionResultResponse)
    assert client.calls[-1][0] == "DELETE"
    assert client.calls[-1][2] == {"preview_digest": DIGEST}


def _model(model_id: str, name: str, context: int) -> ModelResponse:
    return ModelResponse(
        provider="lm_studio",
        backend_model_id=model_id,
        display_name=name,
        model_type="llm",
        context_capacity=262144,
        quantization="Q4_K_S",
        loaded=True,
        vision=True,
        trained_for_tool_use=True,
        loaded_context_length=context,
    )


def test_window_exposes_compact_loaded_model_context_and_chat_controls() -> None:
    app = QApplication.instance() or QApplication([])
    window = AthenaMainWindow(api_controller=None)
    snapshot = DesktopApiSnapshot(
        health=HealthResponse(api_version="v1", core_status="ok", detail=None),
        provider=ProviderHealthResponse(
            provider="lm_studio",
            status="ready",
            detail=None,
        ),
        models=(
            _model("model-a", "Model A", 8192),
            _model("model-b", "Model B", 16384),
        ),
        chats=(
            ChatSummaryResponse(
                chat_id=str(CHAT_ID),
                started_at_us=1,
                ended_at_us=None,
                archive_mode="standard",
                lifecycle_state="active",
                message_count=3,
            ),
        ),
    )

    window.apply_api_snapshot(snapshot)
    assert window.model_selector.count() == 2
    assert window.model_selector.currentData() == "model-a"
    assert window.context_slider.maximum() == 8192
    assert window.chat_selector.findData(str(CHAT_ID)) >= 0
    assert window.status_text.text() == "LOCAL / READY"

    window.model_selector.setCurrentIndex(1)
    window._on_model_selected(1)
    assert window._selected_model_id() == "model-b"
    assert window.context_slider.maximum() == 16384

    empty_snapshot = DesktopApiSnapshot(
        health=snapshot.health,
        provider=snapshot.provider,
        models=(),
        chats=(),
    )
    window.apply_api_snapshot(empty_snapshot)
    assert window.status_text.text() == "LOCAL / MODEL REQUIRED"
    window.close()
    app.processEvents()
