from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from urllib.error import URLError

import pytest
from PySide6.QtCore import QThreadPool
from PySide6.QtTest import QSignalSpy

from athena.api import client as client_module
from athena.api.asgi import CoreApiAsgiApp
from athena.api.client import CoreApiClient, CoreApiClientError
from athena.api.contracts import (
    KnowledgeUnitProposalResponse,
    MessageKnowledgeExtractionResponse,
    RememberedChatMessageResponse,
)
from athena.api.executor import SerializedCoreApiSurface
from athena.api.runtime import LocalApiRuntime
from athena.api.service import (
    ChatMessageRevisionMismatchError,
    CoreApiFacade,
)
from athena.chat.models import ChatMessage, ChatSummary, ChatThread, MessageType
from athena.desktop.api_controller import DesktopApiController
from athena.desktop.app import create_application
from athena.knowledge.extraction_models import (
    ChatExtractionResult,
    ExtractionProposalSet,
    MergeCandidate,
    ProposalEntityType,
    ProposedClaim,
    ProposedKnowledgeUnit,
    ProposedRelation,
)
from athena.knowledge.models import ClaimKind, EpistemicStatus, KnowledgeKind
from athena.memory.models import MemoryKind, PersonalMemoryDraft, PersonalMemoryRevision
from athena.model.domain import ModelInfo, ProviderHealth, ProviderHealthStatus
from athena.model.provenance import ModelSignature, ProcessingRun
from athena.observability.health import HealthService

CHAT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
MESSAGE_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
REVISION_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
ACTOR_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")
MEMORY_ID = uuid.UUID("55555555-5555-5555-5555-555555555555")
MEMORY_REVISION_ID = uuid.UUID("66666666-6666-6666-6666-666666666666")
RUN_ID = uuid.UUID("77777777-7777-7777-7777-777777777777")
SIGNATURE_ID = uuid.UUID("88888888-8888-8888-8888-888888888888")


class _Chat:
    def list_chats(self, *, limit: int = 50) -> tuple[ChatSummary, ...]:
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
            messages=(
                ChatMessage(
                    message_id=MESSAGE_ID,
                    chat_id=CHAT_ID,
                    sequence_no=1,
                    message_type=MessageType.USER,
                    actor_id=ACTOR_ID,
                    created_at_us=2,
                    revision_id=REVISION_ID,
                    content="Remember SQLite as a local preference.",
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
        return ()


class _Memory:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def remember(self, *, content: str) -> PersonalMemoryRevision:
        self.calls.append(content)
        return PersonalMemoryRevision(
            memory_id=MEMORY_ID,
            revision_id=MEMORY_REVISION_ID,
            revision_no=1,
            created_at_us=3,
            created_by_actor_id=ACTOR_ID,
            provenance_id=uuid.UUID("99999999-9999-9999-9999-999999999999"),
            payload=PersonalMemoryDraft(
                memory_kind=MemoryKind.OTHER,
                content=content,
            ),
        )


class _Extraction:
    def __init__(self) -> None:
        self.calls: list[tuple[uuid.UUID, uuid.UUID, uuid.UUID]] = []

    def extract_message(
        self,
        *,
        chat_id: uuid.UUID,
        message_id: uuid.UUID,
        revision_id: uuid.UUID,
        requested_model_id: str | None = None,
        context_limit: int | None = None,
        output_reserve: int | None = None,
    ) -> ChatExtractionResult:
        assert requested_model_id == "model-1"
        assert context_limit == 4096
        assert output_reserve == 1024
        self.calls.append((chat_id, message_id, revision_id))
        proposals = ExtractionProposalSet(
            knowledge_units=(
                ProposedKnowledgeUnit(
                    source_sequence_no=1,
                    source_quote="SQLite",
                    knowledge_kind=KnowledgeKind.FACT,
                    title="Database",
                    body="SQLite is used locally.",
                    epistemic_status=EpistemicStatus.ASSERTED,
                    confidence=0.9,
                ),
            ),
            claims=(
                ProposedClaim(
                    source_sequence_no=1,
                    source_quote="SQLite",
                    claim_kind=ClaimKind.FACTUAL_ASSERTION,
                    statement="SQLite is used locally.",
                    epistemic_status=EpistemicStatus.ASSERTED,
                    confidence=0.8,
                ),
            ),
            relations=(
                ProposedRelation(
                    left_type=ProposalEntityType.KNOWLEDGE,
                    left_index=0,
                    relation_type="supports",
                    right_type=ProposalEntityType.CLAIM,
                    right_index=0,
                    confidence=0.7,
                ),
            ),
            merge_candidates=(
                MergeCandidate(
                    proposal_type=ProposalEntityType.KNOWLEDGE,
                    proposal_index=0,
                    reason="Possible overlap",
                    confidence=0.6,
                ),
            ),
        )
        return ChatExtractionResult(
            chat_id=chat_id,
            model=ModelInfo(
                provider="lm_studio",
                backend_model_id="model-1",
                display_name="Model One",
                model_type="llm",
                context_capacity=8192,
                quantization=None,
                loaded=True,
                vision=False,
                trained_for_tool_use=True,
            ),
            model_signature=cast(
                ModelSignature,
                SimpleNamespace(model_signature_id=SIGNATURE_ID),
            ),
            processing_run=cast(
                ProcessingRun,
                SimpleNamespace(processing_run_id=RUN_ID),
            ),
            proposals=proposals,
        )


def _facade() -> tuple[CoreApiFacade, _Memory, _Extraction]:
    health = HealthService()
    health.mark_ok()
    memory = _Memory()
    extraction = _Extraction()
    facade = CoreApiFacade(
        health=health,
        chat=_Chat(),  # type: ignore[arg-type]
        model_provider=_Provider(),
    )
    facade.attach_knowledge_interaction(
        personal_memory=memory,
        extraction=extraction,
    )
    return facade, memory, extraction


class _ImmediateExecutor:
    def __init__(self) -> None:
        self.calls = 0

    def call(self, callback: Any) -> Any:
        self.calls += 1
        return callback()


def test_serialized_surface_delegates_message_actions() -> None:
    facade, memory, extraction = _facade()
    executor = _ImmediateExecutor()
    surface = SerializedCoreApiSurface(
        facade,
        cast(Any, executor),
    )

    remembered = surface.remember_chat_message(
        str(CHAT_ID),
        str(MESSAGE_ID),
        revision_id=str(REVISION_ID),
    )
    result = surface.extract_chat_message_knowledge(
        str(CHAT_ID),
        str(MESSAGE_ID),
        revision_id=str(REVISION_ID),
        requested_model_id="model-1",
        effective_context_limit=4096,
        max_output_tokens=1024,
    )

    assert remembered.memory_id == str(MEMORY_ID)
    assert result.processing_run_id == str(RUN_ID)
    assert memory.calls == ["Remember SQLite as a local preference."]
    assert extraction.calls == [(CHAT_ID, MESSAGE_ID, REVISION_ID)]
    assert executor.calls == 2


def test_facade_uses_exact_message_revision_for_memory_and_extraction() -> None:
    facade, memory, extraction = _facade()

    remembered = facade.remember_chat_message(
        str(CHAT_ID),
        str(MESSAGE_ID),
        revision_id=str(REVISION_ID),
    )
    result = facade.extract_chat_message_knowledge(
        str(CHAT_ID),
        str(MESSAGE_ID),
        revision_id=str(REVISION_ID),
        requested_model_id="model-1",
        effective_context_limit=4096,
        max_output_tokens=1024,
    )

    assert remembered.memory_id == str(MEMORY_ID)
    assert memory.calls == ["Remember SQLite as a local preference."]
    assert extraction.calls == [(CHAT_ID, MESSAGE_ID, REVISION_ID)]
    assert result.processing_run_id == str(RUN_ID)
    assert result.model_signature_id == str(SIGNATURE_ID)
    assert result.knowledge_units[0].proposal_index == 0
    assert result.claims[0].proposal_index == 0
    assert result.relations[0].left_type == "knowledge"
    assert result.extractor_merge_candidates[0].proposal_index == 0
    assert "memory.remember.chat_message" in facade.capabilities().features
    assert "knowledge.extract.chat_message" in facade.capabilities().features


def test_facade_rejects_stale_revision_before_memory_write() -> None:
    facade, memory, _ = _facade()

    with pytest.raises(ChatMessageRevisionMismatchError, match="stale"):
        facade.remember_chat_message(
            str(CHAT_ID),
            str(MESSAGE_ID),
            revision_id=str(uuid.uuid4()),
        )

    assert memory.calls == []


def test_application_attaches_knowledge_interaction(tmp_path: Path) -> None:
    from athena.config.settings import AthenaSettings
    from athena.core.application import AthenaApplication

    app = AthenaApplication(
        settings=AthenaSettings(local_root=tmp_path / "runtime"),
    )

    features = app.api.capabilities().features
    assert "memory.remember.chat_message" in features
    assert "knowledge.extract.chat_message" in features


async def _request(
    app: CoreApiAsgiApp,
    runtime: LocalApiRuntime,
    *,
    path: str,
    token: str,
    body: dict[str, Any],
) -> tuple[int, dict[str, Any]]:
    scope: dict[str, Any] = {
        "type": "http",
        "method": "POST",
        "path": path,
        "query_string": b"",
        "headers": [(b"authorization", f"Bearer {token}".encode("ascii"))],
    }
    delivered = False

    async def receive() -> dict[str, Any]:
        nonlocal delivered
        if delivered:
            return {"type": "http.request", "body": b"", "more_body": False}
        delivered = True
        return {
            "type": "http.request",
            "body": json.dumps(body).encode("utf-8"),
            "more_body": False,
        }

    sent: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    await app(scope, receive, send)
    assert len(sent) == 2
    return int(sent[0]["status"]), json.loads(sent[1]["body"].decode("utf-8"))


def test_asgi_exposes_message_actions_and_stale_revision_is_409(tmp_path: Path) -> None:
    facade, _, _ = _facade()
    runtime = LocalApiRuntime(tmp_path / "api")
    runtime.publish(port=32123)
    token = runtime.token_path.read_text(encoding="utf-8").strip()
    app = CoreApiAsgiApp(facade=facade, runtime=runtime)

    status, payload = asyncio.run(
        _request(
            app,
            runtime,
            path=f"/api/v1/chats/{CHAT_ID}/messages/{MESSAGE_ID}/remember",
            token=token,
            body={"revision_id": str(REVISION_ID)},
        )
    )
    extraction_status, extraction_payload = asyncio.run(
        _request(
            app,
            runtime,
            path=(
                f"/api/v1/chats/{CHAT_ID}/messages/{MESSAGE_ID}/"
                "knowledge-extraction"
            ),
            token=token,
            body={
                "revision_id": str(REVISION_ID),
                "model_id": "model-1",
                "effective_context_limit": 4096,
                "max_output_tokens": 1024,
            },
        )
    )
    stale_status, stale = asyncio.run(
        _request(
            app,
            runtime,
            path=f"/api/v1/chats/{CHAT_ID}/messages/{MESSAGE_ID}/remember",
            token=token,
            body={"revision_id": str(uuid.uuid4())},
        )
    )

    assert status == 201
    assert payload["memory_id"] == str(MEMORY_ID)
    assert extraction_status == 201
    assert extraction_payload["processing_run_id"] == str(RUN_ID)
    assert extraction_payload["knowledge_units"][0]["proposal_index"] == 0
    assert stale_status == 409
    assert stale["code"] == "chat_message_revision_stale"


class _Response:
    def __init__(self, payload: dict[str, Any], *, status: int = 201) -> None:
        self.status = status
        self._raw = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> _Response:
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


def _extraction_payload() -> dict[str, Any]:
    return {
        "chat_id": str(CHAT_ID),
        "message_id": str(MESSAGE_ID),
        "message_revision_id": str(REVISION_ID),
        "processing_run_id": str(RUN_ID),
        "model_id": "model-1",
        "model_signature_id": str(SIGNATURE_ID),
        "knowledge_units": [
            {
                "proposal_index": 0,
                "source_sequence_no": 1,
                "source_quote": "SQLite",
                "knowledge_kind": "fact",
                "title": "Database",
                "body": "SQLite is used locally.",
                "epistemic_status": "asserted",
                "confidence": 0.9,
            }
        ],
        "claims": [],
        "relations": [],
        "extractor_merge_candidates": [],
    }


def test_client_parses_message_actions_without_retrying_posts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_root = tmp_path / "api"
    _bootstrap(runtime_root)
    calls: list[str] = []

    def fake_urlopen(request: Any, timeout: float) -> _Response:
        del timeout
        calls.append(request.full_url)
        if request.full_url.endswith("/remember"):
            return _Response(
                {
                    "chat_id": str(CHAT_ID),
                    "message_id": str(MESSAGE_ID),
                    "message_revision_id": str(REVISION_ID),
                    "memory_id": str(MEMORY_ID),
                    "memory_revision_id": str(MEMORY_REVISION_ID),
                    "content": "Remember SQLite as a local preference.",
                }
            )
        return _Response(_extraction_payload())

    monkeypatch.setattr(client_module, "urlopen", fake_urlopen)
    client = CoreApiClient(runtime_root)

    remembered = client.remember_chat_message(
        str(CHAT_ID),
        str(MESSAGE_ID),
        revision_id=str(REVISION_ID),
    )
    extracted = client.extract_chat_message_knowledge(
        str(CHAT_ID),
        str(MESSAGE_ID),
        revision_id=str(REVISION_ID),
    )

    assert remembered.memory_id == str(MEMORY_ID)
    assert extracted.knowledge_units[0].proposal_index == 0
    assert len(calls) == 2


def test_client_does_not_retry_remember_transport_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_root = tmp_path / "api"
    _bootstrap(runtime_root)
    calls = 0

    def fake_urlopen(request: Any, timeout: float) -> _Response:
        nonlocal calls
        del request, timeout
        calls += 1
        raise URLError("response lost")

    monkeypatch.setattr(client_module, "urlopen", fake_urlopen)

    with pytest.raises(CoreApiClientError, match="unavailable"):
        CoreApiClient(runtime_root).remember_chat_message(
            str(CHAT_ID),
            str(MESSAGE_ID),
            revision_id=str(REVISION_ID),
        )

    assert calls == 1


class _ControllerGateway:
    def remember_chat_message(
        self,
        chat_id: str,
        message_id: str,
        *,
        revision_id: str,
    ) -> RememberedChatMessageResponse:
        return RememberedChatMessageResponse(
            chat_id=chat_id,
            message_id=message_id,
            message_revision_id=revision_id,
            memory_id=str(MEMORY_ID),
            memory_revision_id=str(MEMORY_REVISION_ID),
            content="remembered",
        )

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
        del model_id, effective_context_limit, max_output_tokens
        return MessageKnowledgeExtractionResponse(
            chat_id=chat_id,
            message_id=message_id,
            message_revision_id=revision_id,
            processing_run_id=str(RUN_ID),
            model_id="model-1",
            model_signature_id=str(SIGNATURE_ID),
            knowledge_units=(
                KnowledgeUnitProposalResponse(
                    proposal_index=0,
                    source_sequence_no=1,
                    source_quote="SQLite",
                    knowledge_kind="fact",
                    title=None,
                    body="SQLite",
                    epistemic_status="asserted",
                    confidence=1.0,
                ),
            ),
            claims=(),
            relations=(),
            extractor_merge_candidates=(),
        )


def test_controller_dispatches_message_actions_off_ui_thread() -> None:
    app = create_application(["athena-knowledge-controller-test"])
    pool = QThreadPool()
    pool.setMaxThreadCount(1)
    controller = DesktopApiController(  # type: ignore[arg-type]
        _ControllerGateway(),
        thread_pool=pool,
    )
    remembered = QSignalSpy(controller.message_remembered)
    extracted = QSignalSpy(controller.knowledge_extraction_ready)

    controller.remember_message(
        chat_id=str(CHAT_ID),
        message_id=str(MESSAGE_ID),
        revision_id=str(REVISION_ID),
    )
    assert pool.waitForDone(2_000)
    app.processEvents()
    assert remembered.count() == 1

    controller.extract_message_knowledge(
        chat_id=str(CHAT_ID),
        message_id=str(MESSAGE_ID),
        revision_id=str(REVISION_ID),
    )
    assert pool.waitForDone(2_000)
    app.processEvents()
    assert extracted.count() == 1
