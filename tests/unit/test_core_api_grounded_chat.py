from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from athena.api.asgi import CoreApiAsgiApp
from athena.api.executor import SerializedCoreApiSurface
from athena.api.runtime import LocalApiRuntime
from athena.api.service import CoreApiFacade
from athena.chat.models import (
    ChatMessage,
    ChatSummary,
    ChatThread,
    MessageType,
)
from athena.knowledge.models import EpistemicStatus
from athena.model.domain import (
    ModelInfo,
    ProviderHealth,
    ProviderHealthStatus,
)
from athena.observability.health import HealthService
from athena.retrieval.evidence import (
    EvidenceClass,
    MemoryEvidenceClassification,
    MemoryEvidenceSelection,
)
from athena.retrieval.search import SearchEntityType

CHAT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
USER_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
MODEL_ACTOR_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
KNOWLEDGE_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")
KNOWLEDGE_REVISION_ID = uuid.UUID(
    "55555555-5555-5555-5555-555555555555"
)
ANCHOR_ID = uuid.UUID("66666666-6666-6666-6666-666666666666")
SOURCE_ID = uuid.UUID("77777777-7777-7777-7777-777777777777")
REPRESENTATION_ID = uuid.UUID(
    "88888888-8888-8888-8888-888888888888"
)
MEMORY_ID = uuid.UUID("99999999-9999-9999-9999-999999999999")
MEMORY_REVISION_ID = uuid.UUID(
    "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
)
RUN_ID = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


class _Chat:
    def __init__(self) -> None:
        self.messages: tuple[ChatMessage, ...] = ()

    def list_chats(
        self,
        *,
        limit: int = 50,
    ) -> tuple[ChatSummary, ...]:
        del limit
        return ()

    def create_chat(self) -> uuid.UUID:
        return CHAT_ID

    def load_chat(self, chat_id: uuid.UUID) -> ChatThread:
        assert chat_id == CHAT_ID
        return ChatThread(
            chat_id=CHAT_ID,
            started_at_us=1,
            ended_at_us=None,
            archive_mode="standard",
            lifecycle_state="active",
            messages=self.messages,
        )


class _Provider:
    @property
    def provider_id(self) -> str:
        return "lm_studio"

    def health(self) -> ProviderHealth:
        return ProviderHealth(status=ProviderHealthStatus.READY)

    def discover_models(self) -> tuple[ModelInfo, ...]:
        return ()


class _Unified:
    def __init__(
        self,
        chat: _Chat,
        *,
        missing_grounding: bool = False,
    ) -> None:
        self.chat = chat
        self.missing_grounding = missing_grounding
        self.calls: list[
            tuple[uuid.UUID, str, str | None, str | None]
        ] = []

    def send_message(
        self,
        *,
        chat_id: uuid.UUID,
        content: str,
        requested_model_id: str | None = None,
        requested_embedding_model_id: str | None = None,
    ) -> Any:
        self.calls.append(
            (
                chat_id,
                content,
                requested_model_id,
                requested_embedding_model_id,
            )
        )
        user = ChatMessage(
            message_id=uuid.uuid4(),
            chat_id=chat_id,
            sequence_no=1,
            message_type=MessageType.USER,
            actor_id=USER_ID,
            created_at_us=10,
            revision_id=uuid.uuid4(),
            content=content,
            content_format="text/plain",
        )
        assistant = ChatMessage(
            message_id=uuid.uuid4(),
            chat_id=chat_id,
            sequence_no=2,
            message_type=MessageType.ASSISTANT,
            actor_id=MODEL_ACTOR_ID,
            created_at_us=11,
            revision_id=uuid.uuid4(),
            content=(
                "Berlin [CTX-001]; Quelle [SOURCE:CTX-002]"
                '\n\nATHENA_PROVENANCE {"version":3}'
            ),
            content_format="text/plain",
        )
        self.chat.messages = (user, assistant)

        report = None
        if not self.missing_grounding:
            report = SimpleNamespace(
                cited_context_ids=("CTX-001", "CTX-002"),
                canonical_context_ids=("CTX-001",),
                user_statement_context_ids=(),
                conversation_context_ids=(),
                source_context_ids=("CTX-002",),
                research_context_ids=(),
                news_context_ids=(),
                invalid_context_ids=(),
                uses_inference=False,
                uses_model_prior=False,
                uses_unknown=False,
                has_provenance_marker=True,
            )

        source_text = "Imported source text."
        memory_context = SimpleNamespace(
            items=(
                SimpleNamespace(
                    context_id="CTX-001",
                    entity_id=KNOWLEDGE_ID,
                    revision_id=KNOWLEDGE_REVISION_ID,
                    entity_type=SearchEntityType.KNOWLEDGE,
                    title="Stored capital",
                    text="Berlin ist die Hauptstadt Deutschlands.",
                    truncated=False,
                ),
            ),
            memory_items=(
                SimpleNamespace(
                    context_id="MEM-001",
                    memory_id=MEMORY_ID,
                    revision_id=MEMORY_REVISION_ID,
                    memory_kind="preference",
                    scope_kind="global",
                    scope_entity_id=None,
                    content="Antworten auf Deutsch.",
                ),
            ),
        )
        source_context = SimpleNamespace(
            items=(
                SimpleNamespace(
                    context_id="CTX-002",
                    anchor_id=ANCHOR_ID,
                    source_id=SOURCE_ID,
                    representation_id=REPRESENTATION_ID,
                    start_offset=20,
                    end_offset=20 + len(source_text),
                    page_start=2,
                    page_end=2,
                    quoted_hash=hashlib.sha256(
                        source_text.encode("utf-8")
                    ).digest(),
                    source_name="berlin.txt",
                    source_uri="file:///berlin.txt",
                    text=source_text,
                    truncated=False,
                ),
            ),
        )
        selection = MemoryEvidenceSelection(
            policy_id="typed-provenance-v1",
            results=(),
            classifications=(
                MemoryEvidenceClassification(
                    entity_id=KNOWLEDGE_ID,
                    revision_id=KNOWLEDGE_REVISION_ID,
                    entity_type=SearchEntityType.KNOWLEDGE,
                    evidence_class=EvidenceClass.CANONICAL,
                    message_type=None,
                    epistemic_status=EpistemicStatus.ASSERTED,
                ),
            ),
        )
        return SimpleNamespace(
            generation=SimpleNamespace(
                assistant_message=assistant,
                model=SimpleNamespace(
                    backend_model_id="primary-model"
                ),
                grounding_report=report,
            ),
            memory_context=memory_context,
            source_context=source_context,
            evidence_selection=selection,
            processing_run=SimpleNamespace(processing_run_id=RUN_ID),
            embedding_model=SimpleNamespace(
                backend_model_id="embedding-model"
            ),
        )


def _facade(
    *,
    missing_grounding: bool = False,
) -> tuple[CoreApiFacade, _Unified]:
    chat = _Chat()
    health = HealthService()
    health.mark_ok()
    facade = CoreApiFacade(
        health=health,
        chat=chat,  # type: ignore[arg-type]
        model_provider=_Provider(),
    )
    unified = _Unified(chat, missing_grounding=missing_grounding)
    facade.attach_unified_local_chat(
        unified  # type: ignore[arg-type]
    )
    return facade, unified


def test_facade_maps_real_evidence_identity() -> None:
    facade, unified = _facade()

    assert (
        "chat.send.unified_local"
        in facade.capabilities().features
    )
    result = facade.send_unified_local_chat_message(
        str(CHAT_ID),
        content="Was weiß ATHENA über Berlin?",
        requested_model_id="primary-model",
        requested_embedding_model_id="embedding-model",
    )

    assert len(unified.calls) == 1
    assert result.assistant_text == (
        "Berlin [CTX-001]; Quelle [SOURCE:CTX-002]"
    )
    assert "ATHENA_PROVENANCE" not in result.assistant_text
    assert result.thread.messages[-1].content is not None
    assert (
        "ATHENA_PROVENANCE"
        not in result.thread.messages[-1].content
    )
    assert [item.evidence_class for item in result.evidence] == [
        "canonical",
        "source",
    ]
    assert all(item.cited for item in result.evidence)
    assert result.evidence[0].epistemic_status == "asserted"
    assert result.evidence[1].epistemic_status is None
    assert result.evidence[0].revision_id == str(
        KNOWLEDGE_REVISION_ID
    )
    assert result.evidence[1].entity_id == str(ANCHOR_ID)
    assert result.evidence[1].source_id == str(SOURCE_ID)
    assert result.evidence[1].representation_id == str(
        REPRESENTATION_ID
    )
    assert len(result.evidence[1].quoted_sha256 or "") == 64
    assert result.personal_memory[0].memory_id == str(MEMORY_ID)
    assert result.grounding.canonical_context_ids == ("CTX-001",)
    assert result.grounding.source_context_ids == ("CTX-002",)
    assert result.processing_run_id == str(RUN_ID)
    assert result.model_id == "primary-model"
    assert result.embedding_model_id == "embedding-model"


def test_facade_fails_closed_without_grounding_report() -> None:
    facade, _ = _facade(missing_grounding=True)

    with pytest.raises(
        RuntimeError,
        match="without a grounding report",
    ):
        facade.send_unified_local_chat_message(
            str(CHAT_ID),
            content="ground me",
        )


async def _post_unified(
    app: CoreApiAsgiApp,
    runtime: LocalApiRuntime,
    *,
    body: bytes,
) -> tuple[int, dict[str, Any]]:
    token = runtime.token_path.read_text(
        encoding="utf-8"
    ).strip()
    scope: dict[str, Any] = {
        "type": "http",
        "method": "POST",
        "path": (
            f"/api/v1/chats/{CHAT_ID}/"
            "messages/unified-local"
        ),
        "query_string": b"",
        "headers": [
            (
                b"authorization",
                f"Bearer {token}".encode("ascii"),
            ),
            (b"content-type", b"application/json"),
        ],
    }
    delivered = False

    async def receive() -> dict[str, Any]:
        nonlocal delivered
        if delivered:
            return {
                "type": "http.request",
                "body": b"",
                "more_body": False,
            }
        delivered = True
        return {
            "type": "http.request",
            "body": body,
            "more_body": False,
        }

    sent: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    await app(scope, receive, send)
    start, response = sent
    return (
        int(start["status"]),
        json.loads(response["body"].decode("utf-8")),
    )


def test_asgi_unified_local_route_returns_structured_evidence(
    tmp_path,
) -> None:
    facade, unified = _facade()
    runtime = LocalApiRuntime(tmp_path / "api")
    runtime.publish(port=32123)
    app = CoreApiAsgiApp(
        facade=facade,
        runtime=runtime,
    )

    status, payload = asyncio.run(
        _post_unified(
            app,
            runtime,
            body=json.dumps(
                {
                    "content": "Was weiß ATHENA über Berlin?",
                    "model_id": "primary-model",
                    "embedding_model_id": "embedding-model",
                }
            ).encode("utf-8"),
        )
    )

    assert status == 200
    assert payload["evidence"][0]["context_id"] == "CTX-001"
    assert payload["evidence"][1]["entity_type"] == "source_anchor"
    assert payload["grounding"]["source_context_ids"] == [
        "CTX-002"
    ]
    assert len(unified.calls) == 1


def test_asgi_unified_local_route_rejects_unknown_fields(
    tmp_path,
) -> None:
    facade, unified = _facade()
    runtime = LocalApiRuntime(tmp_path / "api")
    runtime.publish(port=32123)
    app = CoreApiAsgiApp(
        facade=facade,
        runtime=runtime,
    )

    status, payload = asyncio.run(
        _post_unified(
            app,
            runtime,
            body=json.dumps(
                {
                    "content": "hello",
                    "unexpected": True,
                }
            ).encode("utf-8"),
        )
    )

    assert status == 400
    assert payload["code"] == "invalid_request"
    assert unified.calls == []



class _RecordingExecutor:
    def __init__(self) -> None:
        self.calls = 0

    def call(self, callback):
        self.calls += 1
        return callback()


def test_serialized_surface_dispatches_grounded_mutation() -> None:
    facade, unified = _facade()
    executor = _RecordingExecutor()
    surface = SerializedCoreApiSurface(
        facade,
        executor,  # type: ignore[arg-type]
    )

    result = surface.send_unified_local_chat_message(
        str(CHAT_ID),
        content="owner thread please",
    )

    assert executor.calls == 1
    assert len(unified.calls) == 1
    assert result.evidence
