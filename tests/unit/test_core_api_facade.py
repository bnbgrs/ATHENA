from __future__ import annotations

import uuid

from athena.api.contracts import API_VERSION
from athena.api.service import CoreApiFacade
from athena.chat.models import ChatMessage, ChatSummary, ChatThread, MessageType
from athena.model.domain import ModelInfo, ProviderHealth, ProviderHealthStatus
from athena.observability.health import HealthService


class _Chat:
    def __init__(self) -> None:
        self.chat_id = uuid.UUID("11111111-1111-1111-1111-111111111111")
        self.message_id = uuid.UUID("22222222-2222-2222-2222-222222222222")
        self.revision_id = uuid.UUID("33333333-3333-3333-3333-333333333333")
        self.actor_id = uuid.UUID("44444444-4444-4444-4444-444444444444")

    def list_chats(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[ChatSummary, ...]:
        assert limit > 0
        assert offset >= 0
        return (
            ChatSummary(
                chat_id=self.chat_id,
                started_at_us=10,
                ended_at_us=None,
                archive_mode="standard",
                lifecycle_state="active",
                message_count=1,
            ),
        )

    def create_chat(self) -> uuid.UUID:
        return self.chat_id

    def load_chat(self, chat_id: uuid.UUID) -> ChatThread:
        assert chat_id == self.chat_id
        return ChatThread(
            chat_id=self.chat_id,
            started_at_us=10,
            ended_at_us=None,
            archive_mode="standard",
            lifecycle_state="active",
            messages=(
                ChatMessage(
                    message_id=self.message_id,
                    chat_id=self.chat_id,
                    sequence_no=1,
                    message_type=MessageType.USER,
                    actor_id=self.actor_id,
                    created_at_us=11,
                    revision_id=self.revision_id,
                    content="hello",
                    content_format="text/plain",
                ),
            ),
        )


class _Provider:
    @property
    def provider_id(self) -> str:
        return "lm_studio"

    def health(self) -> ProviderHealth:
        return ProviderHealth(status=ProviderHealthStatus.READY)

    def discover_models(self) -> tuple[ModelInfo, ...]:
        return (
            ModelInfo(
                provider="lm_studio",
                backend_model_id="example/model",
                display_name="Example Model",
                model_type="llm",
                context_capacity=262144,
                quantization="Q4_K_S",
                loaded=True,
                vision=True,
                trained_for_tool_use=True,
                loaded_context_length=8192,
            ),
        )


def _facade() -> CoreApiFacade:
    health = HealthService()
    health.mark_ok()
    return CoreApiFacade(
        health=health,
        chat=_Chat(),  # type: ignore[arg-type]
        model_provider=_Provider(),
    )


def test_health_contract_is_versioned_and_json_safe() -> None:
    result = _facade().health()

    assert result.api_version == API_VERSION
    assert result.core_status == "ok"
    assert result.to_dict() == {
        "api_version": "v1",
        "core_status": "ok",
        "detail": None,
    }


def test_capabilities_are_explicit_and_stable() -> None:
    result = _facade().capabilities()

    assert result.features == (
        "health",
        "capabilities",
        "chat.read",
        "chat.create",
        "models.read",
    )
    assert result.to_dict()["features"] == [
        "health",
        "capabilities",
        "chat.read",
        "chat.create",
        "models.read",
    ]


def test_chat_summary_does_not_leak_domain_types() -> None:
    result = _facade().list_chats(limit=20)[0]

    assert result.chat_id == "11111111-1111-1111-1111-111111111111"
    assert result.message_count == 1
    assert isinstance(result.to_dict()["chat_id"], str)


def test_create_chat_returns_complete_client_thread() -> None:
    result = _facade().create_chat()

    assert result.chat_id == "11111111-1111-1111-1111-111111111111"
    assert result.messages[0].message_type == "user"
    assert result.messages[0].actor_id == "44444444-4444-4444-4444-444444444444"
    assert result.to_dict()["messages"] == [
        {
            "message_id": "22222222-2222-2222-2222-222222222222",
            "chat_id": "11111111-1111-1111-1111-111111111111",
            "sequence_no": 1,
            "message_type": "user",
            "actor_id": "44444444-4444-4444-4444-444444444444",
            "created_at_us": 11,
            "revision_id": "33333333-3333-3333-3333-333333333333",
            "content": "hello",
            "content_format": "text/plain",
        }
    ]


def test_load_chat_validates_uuid_at_boundary() -> None:
    facade = _facade()

    result = facade.load_chat("11111111-1111-1111-1111-111111111111")
    assert result.chat_id == "11111111-1111-1111-1111-111111111111"


def test_provider_health_is_normalized() -> None:
    result = _facade().provider_health()

    assert result.to_dict() == {
        "provider": "lm_studio",
        "status": "ready",
        "detail": None,
    }


def test_model_discovery_is_normalized() -> None:
    result = _facade().list_models()[0]

    assert result.backend_model_id == "example/model"
    assert result.loaded is True
    assert result.loaded_context_length == 8192
    assert result.to_dict()["provider"] == "lm_studio"


def test_application_exposes_facade_without_starting_transport(tmp_path) -> None:
    from athena.config.settings import AthenaSettings
    from athena.core.application import AthenaApplication

    app = AthenaApplication(
        settings=AthenaSettings(local_root=tmp_path / "runtime"),
    )

    assert app.api.health().core_status == "stopped"
    assert app.api.capabilities().api_version == API_VERSION
