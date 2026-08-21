"""Asynchronous Core API refresh boundary for the ATHENA desktop shell."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from queue import Empty, SimpleQueue
from typing import Literal, Protocol

from PySide6.QtCore import QMetaObject, QObject, QRunnable, Qt, QThreadPool, Signal, Slot

from athena.api.client import CoreApiClientError
from athena.api.contracts import (
    ChatSummaryResponse,
    ChatThreadResponse,
    DeletionPreviewResponse,
    DeletionResultResponse,
    GroundedChatResponse,
    HealthResponse,
    KnowledgeMergeReviewResponse,
    KnowledgeReviewResponse,
    MessageKnowledgeExtractionResponse,
    ModelResponse,
    ProviderHealthResponse,
    RememberedChatMessageResponse,
)
from athena.chat.send_identity import (
    assistant_message_id_for_operation,
    chat_id_for_operation,
)


class CoreApiGateway(Protocol):
    """Minimal local Core API surface consumed by the desktop controller."""

    def health(self) -> HealthResponse: ...

    def provider_health(self) -> ProviderHealthResponse: ...

    def list_models(self) -> tuple[ModelResponse, ...]: ...

    def list_chats(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[ChatSummaryResponse, ...]: ...

    def create_chat(
        self,
        chat_id: str | None = None,
    ) -> ChatThreadResponse: ...

    def load_chat(self, chat_id: str) -> ChatThreadResponse: ...

    def send_chat_message(
        self,
        chat_id: str,
        *,
        content: str,
        model_id: str | None = None,
        operation_id: str | None = None,
        effective_context_limit: int | None = None,
        max_output_tokens: int | None = None,
        temperature: float | None = None,
        thinking_enabled: bool | None = None,
    ) -> ChatThreadResponse: ...
    def send_unified_local_chat_message(
        self,
        chat_id: str,
        *,
        content: str,
        model_id: str | None = None,
        embedding_model_id: str | None = None,
        effective_context_limit: int | None = None,
        max_output_tokens: int | None = None,
        temperature: float | None = None,
        thinking_enabled: bool | None = None,
    ) -> GroundedChatResponse: ...
    def remember_chat_message(
        self,
        chat_id: str,
        message_id: str,
        *,
        revision_id: str,
    ) -> RememberedChatMessageResponse: ...

    def extract_chat_message_knowledge(
        self,
        chat_id: str,
        message_id: str,
        *,
        revision_id: str,
        model_id: str | None = None,
        effective_context_limit: int | None = None,
        max_output_tokens: int | None = None,
    ) -> MessageKnowledgeExtractionResponse: ...

    def prepare_knowledge_review(
        self,
        processing_run_id: str,
    ) -> KnowledgeReviewResponse: ...

    def load_knowledge_merge_review(
        self,
        review_id: str,
    ) -> KnowledgeMergeReviewResponse: ...

    def resolve_knowledge_merge_review(
        self,
        review_id: str,
        *,
        decision: str,
    ) -> KnowledgeMergeReviewResponse: ...

    def preview_chat_deletion(self, chat_id: str) -> DeletionPreviewResponse: ...

    def delete_chat(
        self,
        chat_id: str,
        *,
        preview_digest: str,
    ) -> DeletionResultResponse: ...

SnapshotFreshness = Literal["fresh", "stale", "unavailable"]


@dataclass(frozen=True, slots=True)
class DesktopApiSnapshot:
    """One coherent read snapshot rendered by the desktop shell."""

    health: HealthResponse
    provider: ProviderHealthResponse | None
    models: tuple[ModelResponse, ...]
    chats: tuple[ChatSummaryResponse, ...]
    chat_error: str | None = None
    model_error: str | None = None
    chat_freshness: SnapshotFreshness | None = None
    model_freshness: SnapshotFreshness | None = None

    @property
    def loaded_model(self) -> ModelResponse | None:
        return next((model for model in self.models if model.loaded), None)

    @property
    def resolved_chat_freshness(self) -> SnapshotFreshness:
        if self.chat_freshness is not None:
            return self.chat_freshness
        return "fresh" if self.chat_error is None else "unavailable"

    @property
    def resolved_model_freshness(self) -> SnapshotFreshness:
        if self.model_freshness is not None:
            return self.model_freshness
        return "fresh" if self.model_error is None else "unavailable"


@dataclass(frozen=True, slots=True)
class _RefreshOutcome:
    snapshot: DesktopApiSnapshot | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if (self.snapshot is None) == (self.error is None):
            raise ValueError("Refresh outcome requires exactly one result kind.")


@dataclass(frozen=True, slots=True)
class _ChatOperationOutcome:
    operation: str
    thread: ChatThreadResponse | None = None
    grounded: GroundedChatResponse | None = None
    deletion_preview: DeletionPreviewResponse | None = None
    deleted_chat_id: str | None = None
    remembered: RememberedChatMessageResponse | None = None
    knowledge_extraction: MessageKnowledgeExtractionResponse | None = None
    knowledge_review: KnowledgeReviewResponse | None = None
    merge_review: KnowledgeMergeReviewResponse | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        result_count = sum(
            item is not None
            for item in (
                self.thread,
                self.grounded,
                self.deletion_preview,
                self.deleted_chat_id,
                self.remembered,
                self.knowledge_extraction,
                self.knowledge_review,
                self.merge_review,
            )
        )
        if result_count > 1:
            raise ValueError("Chat outcome cannot contain multiple result kinds.")
        if self.error is None and result_count != 1:
            raise ValueError("Successful chat outcome requires exactly one result.")

_DirectSendReconciliationState = Literal[
    "absent",
    "incomplete",
    "complete",
    "conflict",
]


def _classify_direct_send(
    thread: ChatThreadResponse,
    *,
    chat_id: str,
    operation_id: str,
    content: str,
) -> _DirectSendReconciliationState:
    if thread.chat_id != chat_id:
        return "conflict"

    try:
        parsed_operation_id = uuid.UUID(
            operation_id
        )
    except ValueError:
        return "conflict"

    expected_user_id = str(
        parsed_operation_id
    )

    expected_assistant_id = str(
        assistant_message_id_for_operation(
            parsed_operation_id
        )
    )

    user_matches = tuple(
        message
        for message in thread.messages
        if message.message_id == expected_user_id
    )

    assistant_matches = tuple(
        message
        for message in thread.messages
        if message.message_id == expected_assistant_id
    )

    if (
        not user_matches
        and not assistant_matches
    ):
        return "absent"

    if len(user_matches) != 1:
        return "conflict"

    user_message = user_matches[0]

    if (
        user_message.chat_id != chat_id
        or user_message.message_type != "user"
        or user_message.content != content
    ):
        return "conflict"

    if not assistant_matches:
        return "incomplete"

    if len(assistant_matches) != 1:
        return "conflict"

    assistant_message = assistant_matches[0]

    if (
        assistant_message.chat_id != chat_id
        or assistant_message.message_type != "assistant"
        or assistant_message.sequence_no
        != user_message.sequence_no + 1
    ):
        return "conflict"

    return "complete"


class _ChatTask(QRunnable):
    """Run one chat read/mutation away from the UI thread."""

    def __init__(
        self,
        *,
        gateway: CoreApiGateway,
        operation: str,
        chat_id: str | None,
        content: str | None,
        model_id: str | None,
        operation_id: str | None,
        effective_context_limit: int | None,
        max_output_tokens: int | None,
        temperature: float | None,
        thinking_enabled: bool | None,
        preview_digest: str | None,
        message_id: str | None,
        revision_id: str | None,
        processing_run_id: str | None = None,
        review_id: str | None = None,
        review_decision: str | None = None,
        outcomes: SimpleQueue[_ChatOperationOutcome],
        receiver: QObject,
    ) -> None:
        super().__init__()
        self.gateway = gateway
        self.operation = operation
        self.chat_id = chat_id
        self.content = content
        self.model_id = model_id
        self.operation_id = operation_id
        self.effective_context_limit = effective_context_limit
        self.max_output_tokens = max_output_tokens
        self.temperature = temperature
        self.thinking_enabled = thinking_enabled
        self.preview_digest = preview_digest
        self.message_id = message_id
        self.revision_id = revision_id
        self.processing_run_id = processing_run_id
        self.review_id = review_id
        self.review_decision = review_decision
        self.outcomes = outcomes
        self.receiver = receiver
        self.setAutoDelete(False)
    @Slot()
    def run(self) -> None:
        resolved_chat_id = self.chat_id
        try:
            if self.operation == "load":
                if resolved_chat_id is None:
                    raise ValueError("Chat load requires a chat ID.")
                thread = self.gateway.load_chat(
                    resolved_chat_id
                )
                if thread.chat_id != resolved_chat_id:
                    raise RuntimeError(
                        "Loaded chat belongs to another chat."
                    )
                outcome = _ChatOperationOutcome(
                    operation=self.operation,
                    thread=thread,
                )
            elif self.operation == "send":
                content = self.content
                operation_id = self.operation_id

                if content is None or not content.strip():
                    raise ValueError(
                        "Chat send requires message content."
                    )

                if operation_id is None:
                    raise ValueError(
                        "Direct chat send requires "
                        "a stable operation ID."
                    )

                parsed_operation_id = uuid.UUID(
                    operation_id
                )

                if resolved_chat_id is None:
                    resolved_chat_id = str(
                        chat_id_for_operation(
                            parsed_operation_id
                        )
                    )

                    try:
                        created = self.gateway.create_chat(
                            resolved_chat_id
                        )
                    except CoreApiClientError as create_exc:
                        if create_exc.status is not None:
                            raise

                        try:
                            created = self.gateway.load_chat(
                                resolved_chat_id
                            )
                        except Exception as reconcile_exc:
                            raise create_exc from reconcile_exc

                    if created.chat_id != resolved_chat_id:
                        raise RuntimeError(
                            "Created chat belongs to another chat."
                        )

                if (
                    self.effective_context_limit is None
                    and self.max_output_tokens is None
                    and self.temperature is None
                    and self.thinking_enabled is None
                ):
                    thread = self.gateway.send_chat_message(
                        resolved_chat_id,
                        content=content,
                        model_id=self.model_id,
                        operation_id=operation_id,
                    )
                elif (
                    self.max_output_tokens is None
                    and self.temperature is None
                    and self.thinking_enabled is None
                ):
                    thread = self.gateway.send_chat_message(
                        resolved_chat_id,
                        content=content,
                        model_id=self.model_id,
                        operation_id=operation_id,
                        effective_context_limit=(
                            self.effective_context_limit
                        ),
                    )
                else:
                    thread = self.gateway.send_chat_message(
                        resolved_chat_id,
                        content=content,
                        model_id=self.model_id,
                        operation_id=operation_id,
                        effective_context_limit=(
                            self.effective_context_limit
                        ),
                        max_output_tokens=(
                            self.max_output_tokens
                        ),
                        temperature=self.temperature,
                        thinking_enabled=(
                            self.thinking_enabled
                        ),
                    )

                if (
                    _classify_direct_send(
                        thread,
                        chat_id=resolved_chat_id,
                        operation_id=operation_id,
                        content=content,
                    )
                    != "complete"
                ):
                    raise RuntimeError(
                        "Direct chat response does not contain "
                        "the expected durable send operation."
                    )

                outcome = _ChatOperationOutcome(
                    operation=self.operation,
                    thread=thread,
                )
            elif self.operation == "send_grounded":
                if self.content is None or not self.content.strip():
                    raise ValueError("Grounded chat send requires message content.")
                if resolved_chat_id is None:
                    resolved_chat_id = self.gateway.create_chat().chat_id
                if (
                    self.effective_context_limit is None
                    and self.max_output_tokens is None
                    and self.temperature is None
                    and self.thinking_enabled is None
                ):
                    grounded = self.gateway.send_unified_local_chat_message(
                        resolved_chat_id,
                        content=self.content,
                        model_id=self.model_id,
                    )
                elif (
                    self.max_output_tokens is None
                    and self.temperature is None
                    and self.thinking_enabled is None
                ):
                    grounded = self.gateway.send_unified_local_chat_message(
                        resolved_chat_id,
                        content=self.content,
                        model_id=self.model_id,
                        effective_context_limit=self.effective_context_limit,
                    )
                else:
                    grounded = self.gateway.send_unified_local_chat_message(
                        resolved_chat_id,
                        content=self.content,
                        model_id=self.model_id,
                        effective_context_limit=self.effective_context_limit,
                        max_output_tokens=self.max_output_tokens,
                        temperature=self.temperature,
                        thinking_enabled=self.thinking_enabled,
                    )
                if grounded.thread.chat_id != resolved_chat_id:
                    raise RuntimeError("Grounded response belongs to another chat.")
                outcome = _ChatOperationOutcome(
                    operation=self.operation,
                    grounded=grounded,
                )
            elif self.operation == "remember":
                message_id = self.message_id
                revision_id = self.revision_id
                if (
                    resolved_chat_id is None
                    or message_id is None
                    or revision_id is None
                ):
                    raise ValueError(
                        "Remember requires stable chat-message identity."
                    )
                remembered = self.gateway.remember_chat_message(
                    resolved_chat_id,
                    message_id,
                    revision_id=revision_id,
                )
                if (
                    remembered.chat_id != resolved_chat_id
                    or remembered.message_id != message_id
                    or remembered.message_revision_id != revision_id
                ):
                    raise RuntimeError(
                        "Remember result belongs to another message revision."
                    )
                outcome = _ChatOperationOutcome(
                    operation=self.operation,
                    remembered=remembered,
                )
            elif self.operation == "extract_knowledge":
                message_id = self.message_id
                revision_id = self.revision_id
                if (
                    resolved_chat_id is None
                    or message_id is None
                    or revision_id is None
                ):
                    raise ValueError(
                        "Knowledge extraction requires stable chat-message identity."
                    )
                extraction = self.gateway.extract_chat_message_knowledge(
                    resolved_chat_id,
                    message_id,
                    revision_id=revision_id,
                    model_id=self.model_id,
                    effective_context_limit=self.effective_context_limit,
                    max_output_tokens=self.max_output_tokens,
                )
                if (
                    extraction.chat_id != resolved_chat_id
                    or extraction.message_id != message_id
                    or extraction.message_revision_id != revision_id
                ):
                    raise RuntimeError(
                        "Knowledge extraction result belongs to another message revision."
                    )
                outcome = _ChatOperationOutcome(
                    operation=self.operation,
                    knowledge_extraction=extraction,
                )
            elif self.operation == "prepare_knowledge_review":
                processing_run_id = self.processing_run_id
                if processing_run_id is None:
                    raise ValueError(
                        "Knowledge review requires a ProcessingRun ID."
                    )
                outcome = _ChatOperationOutcome(
                    operation=self.operation,
                    knowledge_review=self.gateway.prepare_knowledge_review(
                        processing_run_id
                    ),
                )
            elif self.operation == "load_merge_review":
                review_id = self.review_id
                if review_id is None:
                    raise ValueError("Merge review load requires a review ID.")
                outcome = _ChatOperationOutcome(
                    operation=self.operation,
                    merge_review=self.gateway.load_knowledge_merge_review(
                        review_id
                    ),
                )
            elif self.operation == "resolve_merge_review":
                review_id = self.review_id
                review_decision = self.review_decision
                if review_id is None or review_decision is None:
                    raise ValueError(
                        "Merge review resolution requires review identity and decision."
                    )
                outcome = _ChatOperationOutcome(
                    operation=self.operation,
                    merge_review=self.gateway.resolve_knowledge_merge_review(
                        review_id,
                        decision=review_decision,
                    ),
                )
            elif self.operation == "preview_delete":
                if resolved_chat_id is None:
                    raise ValueError("Chat deletion preview requires a chat ID.")
                outcome = _ChatOperationOutcome(
                    operation=self.operation,
                    deletion_preview=self.gateway.preview_chat_deletion(
                        resolved_chat_id
                    ),
                )
            elif self.operation == "delete":
                if resolved_chat_id is None or self.preview_digest is None:
                    raise ValueError("Chat deletion requires a preview digest.")
                result = self.gateway.delete_chat(
                    resolved_chat_id,
                    preview_digest=self.preview_digest,
                )
                if result.entity_id != resolved_chat_id:
                    raise RuntimeError("Deletion result belongs to another chat.")
                outcome = _ChatOperationOutcome(
                    operation=self.operation,
                    deleted_chat_id=resolved_chat_id,
                )
            else:
                raise ValueError("Unknown desktop chat operation.")
        except CoreApiClientError as exc:
            if (
                self.operation == "send"
                and resolved_chat_id is not None
                and self.operation_id is not None
                and self.content is not None
            ):
                try:
                    reconciled = self.gateway.load_chat(
                        resolved_chat_id
                    )
                except Exception:
                    reconciled = None

                if reconciled is None:
                    outcome = _ChatOperationOutcome(
                        operation=self.operation,
                        error=str(exc),
                    )
                else:
                    state = _classify_direct_send(
                        reconciled,
                        chat_id=resolved_chat_id,
                        operation_id=self.operation_id,
                        content=self.content,
                    )

                    if state == "complete":
                        outcome = _ChatOperationOutcome(
                            operation=self.operation,
                            thread=reconciled,
                        )
                    elif state == "incomplete":
                        outcome = _ChatOperationOutcome(
                            operation=self.operation,
                            thread=reconciled,
                            error=(
                                "Direct send persisted the user turn "
                                "but no completed assistant turn. "
                                "Automatic re-execution is blocked."
                            ),
                        )
                    elif state == "conflict":
                        outcome = _ChatOperationOutcome(
                            operation=self.operation,
                            thread=reconciled,
                            error=(
                                "Direct send reconciliation detected "
                                "conflicting durable message identity."
                            ),
                        )
                    else:
                        outcome = _ChatOperationOutcome(
                            operation=self.operation,
                            thread=reconciled,
                            error=str(exc),
                        )

            elif (
                self.operation == "send_grounded"
                and resolved_chat_id is not None
            ):
                try:
                    reconciled = self.gateway.load_chat(
                        resolved_chat_id
                    )
                except Exception:
                    reconciled = None

                outcome = _ChatOperationOutcome(
                    operation=self.operation,
                    thread=reconciled,
                    error=str(exc),
                )

            elif (
                self.operation == "delete"
                and resolved_chat_id is not None
                and exc.status is None
            ):
                deletion_reconciled = False

                try:
                    self.gateway.load_chat(
                        resolved_chat_id
                    )
                except CoreApiClientError as reconcile_exc:
                    deletion_reconciled = (
                        reconcile_exc.status == 404
                        and reconcile_exc.code == "chat_not_found"
                    )
                except Exception:
                    deletion_reconciled = False

                if deletion_reconciled:
                    outcome = _ChatOperationOutcome(
                        operation=self.operation,
                        deleted_chat_id=resolved_chat_id,
                    )
                else:
                    outcome = _ChatOperationOutcome(
                        operation=self.operation,
                        error=str(exc),
                    )

            else:
                outcome = _ChatOperationOutcome(
                    operation=self.operation,
                    error=str(exc),
                )
        except Exception:
            outcome = _ChatOperationOutcome(
                operation=self.operation,
                error="ATHENA chat operation failed.",
            )

        self.outcomes.put(outcome)
        queued = QMetaObject.invokeMethod(
            self.receiver,
            "_drain_chat_outcome",
            Qt.ConnectionType.QueuedConnection,
        )
        if not queued:
            raise RuntimeError("ATHENA desktop could not queue the chat result.")
def _chat_snapshot(
    gateway: CoreApiGateway,
    *,
    chat_limit: int,
) -> tuple[tuple[ChatSummaryResponse, ...], str | None]:
    chats: list[ChatSummaryResponse] = []
    seen_chat_ids: set[str] = set()
    offset = 0

    while True:
        try:
            page = (
                gateway.list_chats(
                    limit=chat_limit,
                )
                if offset == 0
                else gateway.list_chats(
                    limit=chat_limit,
                    offset=offset,
                )
            )
        except CoreApiClientError as exc:
            return (), str(exc)
        except Exception:
            return (), "ATHENA chat status refresh failed."

        if len(page) > chat_limit:
            return (
                (),
                "ATHENA chat pagination exceeded the requested page size.",
            )

        for chat in page:
            if chat.chat_id in seen_chat_ids:
                return (
                    (),
                    "ATHENA chat pagination returned a duplicate chat identity.",
                )

            seen_chat_ids.add(
                chat.chat_id
            )

        chats.extend(page)

        if len(page) < chat_limit:
            return tuple(chats), None

        offset += len(page)


def _model_snapshot(
    gateway: CoreApiGateway,
) -> tuple[ProviderHealthResponse | None, tuple[ModelResponse, ...], str | None]:
    try:
        provider = gateway.provider_health()
    except CoreApiClientError as exc:
        return None, (), str(exc)
    except Exception:
        return None, (), "ATHENA model provider status refresh failed."

    try:
        return provider, gateway.list_models(), None
    except CoreApiClientError as exc:
        return provider, (), str(exc)
    except Exception:
        return provider, (), "ATHENA model list refresh failed."


def _collect_snapshot(
    gateway: CoreApiGateway,
    *,
    chat_limit: int,
) -> DesktopApiSnapshot:
    health = gateway.health()
    chats, chat_error = _chat_snapshot(gateway, chat_limit=chat_limit)
    provider, models, model_error = _model_snapshot(gateway)
    return DesktopApiSnapshot(
        health=health,
        provider=provider,
        models=models,
        chats=chats,
        chat_error=chat_error,
        model_error=model_error,
    )


class _RefreshTask(QRunnable):
    """Collect one API snapshot in a pool thread and queue delivery to the UI."""

    def __init__(
        self,
        *,
        gateway: CoreApiGateway,
        chat_limit: int,
        outcomes: SimpleQueue[_RefreshOutcome],
        receiver: QObject,
    ) -> None:
        super().__init__()
        self.gateway = gateway
        self.chat_limit = chat_limit
        self.outcomes = outcomes
        self.receiver = receiver

        # The controller retains this runnable until the queued UI delivery
        # completes. Do not let QThreadPool delete the native runnable first.
        self.setAutoDelete(False)

    @Slot()
    def run(self) -> None:
        try:
            snapshot = _collect_snapshot(
                self.gateway,
                chat_limit=self.chat_limit,
            )
        except CoreApiClientError as exc:
            outcome = _RefreshOutcome(error=str(exc))
        except Exception:
            outcome = _RefreshOutcome(
                error="ATHENA Core status refresh failed."
            )
        else:
            outcome = _RefreshOutcome(snapshot=snapshot)

        # SimpleQueue is the only cross-thread data boundary. No UI QObject
        # state is mutated from this worker thread.
        self.outcomes.put(outcome)

        queued = QMetaObject.invokeMethod(
            self.receiver,
            "_drain_worker_outcome",
            Qt.ConnectionType.QueuedConnection,
        )

        if not queued:
            raise RuntimeError(
                "ATHENA desktop could not queue the API refresh result."
            )


class DesktopApiController(QObject):
    """Run Core API work off the Qt UI thread and publish immutable results."""

    snapshot_ready = Signal(object)
    connection_failed = Signal(str)
    refresh_state_changed = Signal(bool)
    chat_loaded = Signal(object)
    chat_sent = Signal(object)
    grounded_chat_sent = Signal(object)
    chat_deletion_preview_ready = Signal(object)
    chat_deleted = Signal(str)
    message_remembered = Signal(object)
    knowledge_extraction_ready = Signal(object)
    knowledge_review_ready = Signal(object)
    knowledge_merge_review_ready = Signal(object)
    chat_operation_failed = Signal(str, str)
    chat_busy_changed = Signal(bool)

    def __init__(
        self,
        gateway: CoreApiGateway,
        *,
        thread_pool: QThreadPool | None = None,
        chat_limit: int = 50,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        if not 1 <= chat_limit <= 200:
            raise ValueError("Desktop chat limit must be between 1 and 200.")
        self.gateway = gateway
        self.thread_pool = thread_pool or QThreadPool.globalInstance()
        self.chat_limit = chat_limit
        self._refreshing = False
        self._refresh_requested = False
        self._outcomes: SimpleQueue[_RefreshOutcome] = SimpleQueue()
        self._active_task: _RefreshTask | None = None
        self._last_good_chats: tuple[ChatSummaryResponse, ...] | None = None
        self._last_good_provider: ProviderHealthResponse | None = None
        self._last_good_models: tuple[ModelResponse, ...] | None = None
        self._chat_busy = False
        self._chat_outcomes: SimpleQueue[_ChatOperationOutcome] = SimpleQueue()
        self._active_chat_task: _ChatTask | None = None

    @property
    def refreshing(self) -> bool:
        return self._refreshing

    @property
    def chat_busy(self) -> bool:
        return self._chat_busy

    def load_chat(self, chat_id: str) -> None:
        if not chat_id or self._chat_busy:
            return
        self._start_chat_task(operation="load", chat_id=chat_id)

    def send_message(
        self,
        *,
        chat_id: str | None,
        content: str,
        model_id: str | None = None,
        effective_context_limit: int | None = None,
        max_output_tokens: int | None = None,
        temperature: float | None = None,
        thinking_enabled: bool | None = None,
    ) -> None:
        if self._chat_busy or not content.strip():
            return
        self._start_chat_task(
            operation="send",
            chat_id=chat_id,
            content=content,
            model_id=model_id,
            operation_id=str(uuid.uuid4()),
            effective_context_limit=effective_context_limit,
            max_output_tokens=max_output_tokens,
            temperature=temperature,
            thinking_enabled=thinking_enabled,
        )
    def send_grounded_message(
        self,
        *,
        chat_id: str | None,
        content: str,
        model_id: str | None = None,
        effective_context_limit: int | None = None,
        max_output_tokens: int | None = None,
        temperature: float | None = None,
        thinking_enabled: bool | None = None,
    ) -> None:
        if self._chat_busy or not content.strip():
            return
        self._start_chat_task(
            operation="send_grounded",
            chat_id=chat_id,
            content=content,
            model_id=model_id,
            effective_context_limit=effective_context_limit,
            max_output_tokens=max_output_tokens,
            temperature=temperature,
            thinking_enabled=thinking_enabled,
        )
    def remember_message(
        self,
        *,
        chat_id: str,
        message_id: str,
        revision_id: str,
    ) -> None:
        if self._chat_busy or not chat_id or not message_id or not revision_id:
            return
        self._start_chat_task(
            operation="remember",
            chat_id=chat_id,
            message_id=message_id,
            revision_id=revision_id,
        )

    def extract_message_knowledge(
        self,
        *,
        chat_id: str,
        message_id: str,
        revision_id: str,
        model_id: str | None = None,
        effective_context_limit: int | None = None,
        max_output_tokens: int | None = None,
    ) -> None:
        if self._chat_busy or not chat_id or not message_id or not revision_id:
            return
        self._start_chat_task(
            operation="extract_knowledge",
            chat_id=chat_id,
            message_id=message_id,
            revision_id=revision_id,
            model_id=model_id,
            effective_context_limit=effective_context_limit,
            max_output_tokens=max_output_tokens,
        )

    def prepare_knowledge_review(
        self,
        processing_run_id: str,
    ) -> None:
        if self._chat_busy or not processing_run_id:
            return
        self._start_chat_task(
            operation="prepare_knowledge_review",
            chat_id=None,
            processing_run_id=processing_run_id,
        )

    def load_knowledge_merge_review(self, review_id: str) -> None:
        if self._chat_busy or not review_id:
            return
        self._start_chat_task(
            operation="load_merge_review",
            chat_id=None,
            review_id=review_id,
        )

    def resolve_knowledge_merge_review(
        self,
        review_id: str,
        *,
        decision: str,
    ) -> None:
        if (
            self._chat_busy
            or not review_id
            or decision not in {"merge", "keep_separate"}
        ):
            return
        self._start_chat_task(
            operation="resolve_merge_review",
            chat_id=None,
            review_id=review_id,
            review_decision=decision,
        )

    def preview_chat_deletion(self, chat_id: str) -> None:
        if not chat_id or self._chat_busy:
            return
        self._start_chat_task(operation="preview_delete", chat_id=chat_id)

    def delete_chat(self, chat_id: str, *, preview_digest: str) -> None:
        if not chat_id or not preview_digest or self._chat_busy:
            return
        self._start_chat_task(
            operation="delete",
            chat_id=chat_id,
            preview_digest=preview_digest,
        )

    def _start_chat_task(
        self,
        *,
        operation: str,
        chat_id: str | None,
        content: str | None = None,
        model_id: str | None = None,
        operation_id: str | None = None,
        effective_context_limit: int | None = None,
        max_output_tokens: int | None = None,
        temperature: float | None = None,
        thinking_enabled: bool | None = None,
        preview_digest: str | None = None,
        message_id: str | None = None,
        revision_id: str | None = None,
        processing_run_id: str | None = None,
        review_id: str | None = None,
        review_decision: str | None = None,
    ) -> None:
        task = _ChatTask(
            gateway=self.gateway,
            operation=operation,
            chat_id=chat_id,
            content=content,
            model_id=model_id,
            operation_id=operation_id,
            effective_context_limit=effective_context_limit,
            max_output_tokens=max_output_tokens,
            temperature=temperature,
            thinking_enabled=thinking_enabled,
            preview_digest=preview_digest,
            message_id=message_id,
            revision_id=revision_id,
            processing_run_id=processing_run_id,
            review_id=review_id,
            review_decision=review_decision,
            outcomes=self._chat_outcomes,
            receiver=self,
        )
        self._active_chat_task = task
        self._chat_busy = True
        self.chat_busy_changed.emit(True)
        self.thread_pool.start(task)
    @Slot()
    def refresh(self) -> None:
        if self._refreshing:
            self._refresh_requested = True
            return
        self._start_refresh_task()

    def _start_refresh_task(self) -> None:
        task = _RefreshTask(
            gateway=self.gateway,
            chat_limit=self.chat_limit,
            outcomes=self._outcomes,
            receiver=self,
        )
        self._active_task = task
        if not self._refreshing:
            self._refreshing = True
            self.refresh_state_changed.emit(True)
        self.thread_pool.start(task)

    def _stabilize_snapshot(
        self,
        snapshot: DesktopApiSnapshot,
    ) -> DesktopApiSnapshot:
        if snapshot.chat_error is None:
            chats = snapshot.chats
            self._last_good_chats = chats
            chat_freshness: SnapshotFreshness = "fresh"
        elif self._last_good_chats is not None:
            chats = self._last_good_chats
            chat_freshness = "stale"
        else:
            chats = ()
            chat_freshness = "unavailable"

        provider = snapshot.provider
        models = snapshot.models

        if snapshot.model_error is None:
            self._last_good_provider = provider
            self._last_good_models = models
            model_freshness: SnapshotFreshness = "fresh"
        else:
            if provider is not None:
                self._last_good_provider = provider

            if self._last_good_models is not None:
                provider = (
                    provider
                    if provider is not None
                    else self._last_good_provider
                )
                models = self._last_good_models
                model_freshness = "stale"
            else:
                provider = (
                    provider
                    if provider is not None
                    else self._last_good_provider
                )
                models = ()
                model_freshness = "unavailable"

        return DesktopApiSnapshot(
            health=snapshot.health,
            provider=provider,
            models=models,
            chats=chats,
            chat_error=snapshot.chat_error,
            model_error=snapshot.model_error,
            chat_freshness=chat_freshness,
            model_freshness=model_freshness,
        )

    @Slot()
    def _drain_worker_outcome(self) -> None:
        try:
            try:
                outcome = self._outcomes.get_nowait()
            except Empty:
                self.connection_failed.emit(
                    "ATHENA Core status refresh result was lost."
                )
                return
            if outcome.snapshot is not None:
                self.snapshot_ready.emit(
                    self._stabilize_snapshot(outcome.snapshot)
                )
                return
            assert outcome.error is not None
            self.connection_failed.emit(outcome.error)
        finally:
            self._finish_refresh()

    def _finish_refresh(self) -> None:
        self._active_task = None
        if self._refresh_requested:
            self._refresh_requested = False
            self._start_refresh_task()
            return
        self._refreshing = False
        self.refresh_state_changed.emit(False)

    @Slot()
    def _drain_chat_outcome(self) -> None:
        try:
            try:
                outcome = self._chat_outcomes.get_nowait()
            except Empty:
                self.chat_operation_failed.emit(
                    "unknown",
                    "ATHENA chat result was lost.",
                )
                return

            if outcome.error is not None:
                # Failed send mutations may have committed the user turn. The
                # worker reconciles only with a safe GET; it never retries POST.
                if outcome.thread is not None:
                    self.chat_loaded.emit(outcome.thread)
                self.chat_operation_failed.emit(
                    outcome.operation,
                    outcome.error,
                )
                return

            if outcome.grounded is not None:
                self.grounded_chat_sent.emit(outcome.grounded)
            elif outcome.deletion_preview is not None:
                self.chat_deletion_preview_ready.emit(outcome.deletion_preview)
            elif outcome.deleted_chat_id is not None:
                self.chat_deleted.emit(outcome.deleted_chat_id)
            elif outcome.remembered is not None:
                self.message_remembered.emit(outcome.remembered)
            elif outcome.knowledge_extraction is not None:
                self.knowledge_extraction_ready.emit(outcome.knowledge_extraction)
            elif outcome.knowledge_review is not None:
                self.knowledge_review_ready.emit(outcome.knowledge_review)
            elif outcome.merge_review is not None:
                self.knowledge_merge_review_ready.emit(outcome.merge_review)
            elif outcome.thread is not None:
                if outcome.operation == "send":
                    self.chat_sent.emit(outcome.thread)
                else:
                    self.chat_loaded.emit(outcome.thread)
        finally:
            self._active_chat_task = None
            self._chat_busy = False
            self.chat_busy_changed.emit(False)
