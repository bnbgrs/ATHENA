from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QLabel

from athena.api.asgi import CoreApiAsgiApp
from athena.api.client import CoreApiClient
from athena.api.contracts import (
    ChatMessageResponse,
    ChatSummaryResponse,
    ChatThreadResponse,
    HealthResponse,
    ModelResponse,
    ProviderHealthResponse,
)
from athena.api.runtime import LocalApiRuntime
from athena.desktop.api_controller import DesktopApiSnapshot
from athena.desktop.window import AthenaMainWindow, navigation_names
from athena.model.adapters.lm_studio import (
    LMStudioProvider,
    ProviderOutputLimitError,
)
from athena.model.domain import ModelChatMessage


class _Stream:
    def __init__(self) -> None:
        self.lines = (
            b'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":null}]}\n',
            b'data: [DONE]\n',
        )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def __iter__(self):
        return iter(self.lines)


class _RecordingClient(CoreApiClient):
    def __init__(self, tmp_path) -> None:
        super().__init__(tmp_path)
        self.body = None

    def _request(self, method, path, *, query=None, expected_status, json_body=None, timeout_seconds=None):
        del method, path, query, expected_status, timeout_seconds
        self.body = json_body
        return {
            "chat_id": "11111111-1111-1111-1111-111111111111",
            "started_at_us": 1,
            "ended_at_us": None,
            "archive_mode": "standard",
            "lifecycle_state": "active",
            "messages": [],
        }


def _model(model_id: str, *, loaded: bool, model_type: str = "llm") -> ModelResponse:
    return ModelResponse(
        provider="lm_studio",
        backend_model_id=model_id,
        display_name=model_id,
        model_type=model_type,
        context_capacity=32768,
        quantization="Q4",
        loaded=loaded,
        vision=False,
        trained_for_tool_use=True,
        loaded_context_length=32768 if loaded else None,
    )


def _snapshot() -> DesktopApiSnapshot:
    return DesktopApiSnapshot(
        health=HealthResponse(api_version="v1", core_status="ok", detail=None),
        provider=ProviderHealthResponse(provider="lm_studio", status="ready", detail=None),
        models=(
            _model("loaded-llm", loaded=True),
            _model("available-llm", loaded=False),
            _model("embedding", loaded=True, model_type="embedding"),
        ),
        chats=(
            ChatSummaryResponse(
                chat_id="chat-existing",
                started_at_us=1,
                ended_at_us=None,
                archive_mode="standard",
                lifecycle_state="active",
                message_count=62,
            ),
        ),
    )


def test_desktop_starts_and_refreshes_in_explicit_new_chat_state() -> None:
    app = QApplication.instance() or QApplication([])
    window = AthenaMainWindow(api_controller=None)
    try:
        window.apply_api_snapshot(_snapshot())
        window.apply_api_snapshot(_snapshot())
        assert window.current_chat_id is None
        assert window.chat_selector.currentData() is None
        assert window.new_chat_button.text() == "NEW CHAT"
        assert window.chat_selector.findData("chat-existing") >= 0
    finally:
        window.close()
        app.processEvents()


def test_model_selector_lists_available_llms_but_not_embeddings() -> None:
    app = QApplication.instance() or QApplication([])
    window = AthenaMainWindow(api_controller=None)
    try:
        window.apply_api_snapshot(_snapshot())
        assert window.model_selector.count() == 2
        assert window.model_selector.currentData() == "loaded-llm"
        unloaded = window.model_selector.findData("available-llm")
        assert unloaded >= 0
        window.model_selector.setCurrentIndex(unloaded)
        window._on_model_selected(unloaded)
        assert window.status_text.text() == "LOCAL / MODEL NOT LOADED"
    finally:
        window.close()
        app.processEvents()


def test_settings_expose_separate_context_output_temperature_and_thinking() -> None:
    app = QApplication.instance() or QApplication([])
    window = AthenaMainWindow(api_controller=None)
    try:
        window.apply_api_snapshot(_snapshot())
        assert "SETTINGS" in navigation_names()
        assert window.context_slider.maximum() == 32768
        assert window.max_output_spin.value() == 8192
        assert window.temperature_spin.value() == 0.7
        assert window.thinking_checkbox.isChecked() is False
        window.max_output_spin.setValue(4096)
        window.temperature_spin.setValue(0.25)
        window.thinking_checkbox.setChecked(True)
        assert window._max_output_tokens() == 4096
        assert window._temperature() == 0.25
        assert window._thinking_enabled() is True
    finally:
        window.close()
        app.processEvents()


def test_transient_failed_turn_survives_thread_rerender() -> None:
    app = QApplication.instance() or QApplication([])
    window = AthenaMainWindow(api_controller=None)
    thread = ChatThreadResponse(
        chat_id="chat-transient",
        started_at_us=1,
        ended_at_us=None,
        archive_mode="standard",
        lifecycle_state="active",
        messages=(
            ChatMessageResponse(
                message_id="message-user",
                chat_id="chat-transient",
                sequence_no=1,
                message_type="user",
                actor_id="actor-user",
                created_at_us=1,
                revision_id="revision-user",
                content="generate a long answer",
                content_format="text/plain",
            ),
        ),
    )
    try:
        window.apply_api_snapshot(_snapshot())
        window.apply_chat_loaded(thread)
        window.apply_chat_operation_failure(
            "send",
            "The model reached the configured maximum output tokens.",
        )
        window.apply_chat_loaded(thread)

        labels = [
            label.text()
            for label in window.chat_messages_widget.findChildren(QLabel)
        ]
        assert "generate a long answer" in labels
        assert any(
            "configured maximum output tokens" in text
            for text in labels
        )
    finally:
        window.close()
        app.processEvents()


def test_lm_studio_health_and_model_list_share_short_discovery_cache() -> None:
    provider = LMStudioProvider("http://127.0.0.1:1234")
    with patch.object(
        LMStudioProvider,
        "_get_json",
        return_value={"models": []},
    ) as get_json:
        assert provider.health().status.value == "ready"
        assert provider.discover_models() == ()
    assert get_json.call_count == 1


class _OutputLimitSurface:
    def send_chat_message(self, *args, **kwargs):
        del args, kwargs
        raise ProviderOutputLimitError("provider output limit")


def test_asgi_projects_output_limit_without_internal_error(tmp_path) -> None:
    runtime = LocalApiRuntime(tmp_path / "runtime")
    runtime.publish(port=32123)
    token = runtime.token_path.read_text(encoding="utf-8").strip()
    app = CoreApiAsgiApp(
        facade=_OutputLimitSurface(),  # type: ignore[arg-type]
        runtime=runtime,
    )

    async def exercise() -> tuple[int, dict[str, object]]:
        sent: list[dict[str, object]] = []
        received = False

        async def receive() -> dict[str, object]:
            nonlocal received
            if received:
                return {"type": "http.disconnect"}
            received = True
            return {
                "type": "http.request",
                "body": json.dumps({"content": "long"}).encode("utf-8"),
                "more_body": False,
            }

        async def send(message: dict[str, object]) -> None:
            sent.append(message)

        await app(
            {
                "type": "http",
                "method": "POST",
                "path": (
                    "/api/v1/chats/"
                    "11111111-1111-1111-1111-111111111111/messages"
                ),
                "query_string": b"",
                "headers": [
                    (
                        b"authorization",
                        f"Bearer {token}".encode("ascii"),
                    )
                ],
            },
            receive,
            send,
        )
        assert len(sent) == 2
        status = int(sent[0]["status"])
        payload = json.loads(bytes(sent[1]["body"]).decode("utf-8"))
        assert isinstance(payload, dict)
        return status, payload

    status, payload = asyncio.run(exercise())
    assert status == 409
    assert payload["code"] == "output_limit_reached"
    assert "not persisted" in str(payload["message"])

def test_client_transports_explicit_inference_controls(tmp_path) -> None:
    client = _RecordingClient(tmp_path)
    client.send_chat_message(
        "11111111-1111-1111-1111-111111111111",
        content="hello",
        model_id="loaded-llm",
        effective_context_limit=32768,
        max_output_tokens=8192,
        temperature=0.25,
        thinking_enabled=True,
    )
    assert client.body == {
        "content": "hello",
        "model_id": "loaded-llm",
        "effective_context_limit": 32768,
        "max_output_tokens": 8192,
        "temperature": 0.25,
        "thinking_enabled": True,
    }


def test_lm_studio_stream_chat_sends_temperature_and_native_thinking() -> None:
    provider = LMStudioProvider("http://127.0.0.1:1234")
    captured = {}

    def fake_urlopen(request, timeout):
        del timeout
        captured.update(json.loads(request.data.decode("utf-8")))
        return _Stream()

    with patch("athena.model.adapters.lm_studio.urlopen", side_effect=fake_urlopen):
        chunks = tuple(
            provider.stream_chat(
                model_id="loaded-llm",
                messages=(ModelChatMessage(role="user", content="hello"),),
                max_output_tokens=8192,
                reasoning_mode=None,
                temperature=0.25,
            )
        )
    assert chunks == ("ok",)
    assert captured["max_tokens"] == 8192
    assert captured["temperature"] == 0.25
    assert "reasoning_effort" not in captured
