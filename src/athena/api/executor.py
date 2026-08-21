"""Single-owner execution boundary for the long-lived ATHENA Core process."""

from __future__ import annotations

import threading
from concurrent.futures import Future
from queue import Queue
from typing import Callable, TypeVar, cast

from athena.api.contracts import (
    CapabilitiesResponse,
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
from athena.api.ports import CoreApiSurface
from athena.core.application import ApplicationState, AthenaApplication

_ResultT = TypeVar("_ResultT")
_QueuedCall = tuple[Callable[[], object], Future[object]] | None


class CoreDomainExecutorError(RuntimeError):
    """Raised when the dedicated Core owner thread cannot execute safely."""


class CoreDomainExecutor:
    """Own ATHENA startup, SQLite, domain calls, and shutdown on one thread."""

    def __init__(self, app: AthenaApplication) -> None:
        self.app = app
        self._queue: Queue[_QueuedCall] = Queue()
        self._submission_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._shutdown_error: BaseException | None = None
        self._accepting = False

    @property
    def running(self) -> bool:
        thread = self._thread
        return (
            thread is not None
            and thread.is_alive()
            and self._accepting
            and self.app.state is ApplicationState.RUNNING
        )

    @property
    def thread_id(self) -> int | None:
        return self._thread_id

    def start(self) -> None:
        if self.running:
            return
        if self._thread is not None:
            raise CoreDomainExecutorError(
                "ATHENA Core owner thread startup is already in progress."
            )

        self._shutdown_error = None
        startup_result: Queue[BaseException | None] = Queue(maxsize=1)

        thread = threading.Thread(
            target=self._run,
            args=(startup_result,),
            name="athena-core-domain-owner",
            daemon=False,
        )
        self._thread = thread
        thread.start()

        startup_error = startup_result.get()
        if startup_error is not None:
            thread.join()
            self._thread = None
            self._thread_id = None
            raise CoreDomainExecutorError(
                "ATHENA Core owner thread could not start."
            ) from startup_error

        if not self.running:
            self.stop()
            raise CoreDomainExecutorError(
                "ATHENA Core owner thread exited during startup."
            )

    def call(self, callback: Callable[[], _ResultT]) -> _ResultT:
        if threading.get_ident() == self._thread_id:
            return callback()

        future: Future[object] = Future()
        with self._submission_lock:
            if not self._accepting:
                raise CoreDomainExecutorError(
                    "ATHENA Core owner thread is not accepting API work."
                )
            self._queue.put((cast(Callable[[], object], callback), future))

        return cast(_ResultT, future.result())

    def stop(self) -> None:
        thread = self._thread
        if thread is None:
            return

        with self._submission_lock:
            if self._accepting:
                self._accepting = False
                self._queue.put(None)

        if threading.get_ident() == self._thread_id:
            raise CoreDomainExecutorError(
                "ATHENA Core owner thread cannot synchronously join itself."
            )

        thread.join()
        self._thread = None
        self._thread_id = None

        shutdown_error = self._shutdown_error
        self._shutdown_error = None
        if shutdown_error is not None:
            raise CoreDomainExecutorError(
                "ATHENA Core owner thread did not stop cleanly."
            ) from shutdown_error

    def _run(
        self,
        startup_result: Queue[BaseException | None],
    ) -> None:
        self._thread_id = threading.get_ident()

        try:
            self.app.start()
        except BaseException as exc:
            try:
                if self.app.state is not ApplicationState.STOPPED:
                    self.app.stop()
            except BaseException as stop_exc:
                self._shutdown_error = stop_exc
            finally:
                startup_result.put(exc)
            return

        with self._submission_lock:
            self._accepting = True
        startup_result.put(None)

        try:
            while True:
                item = self._queue.get()
                if item is None:
                    break

                callback, future = item
                if not future.set_running_or_notify_cancel():
                    continue

                try:
                    result = callback()
                except BaseException as exc:
                    future.set_exception(exc)
                else:
                    future.set_result(result)
        finally:
            try:
                if self.app.state is not ApplicationState.STOPPED:
                    self.app.stop()
            except BaseException as exc:
                self._shutdown_error = exc
            finally:
                with self._submission_lock:
                    self._accepting = False


class SerializedCoreApiSurface:
    """Dispatch every Core API facade operation onto its single owner thread."""

    def __init__(
        self,
        surface: CoreApiSurface,
        executor: CoreDomainExecutor,
    ) -> None:
        self._surface = surface
        self._executor = executor

    def health(self) -> HealthResponse:
        return self._executor.call(self._surface.health)

    def capabilities(self) -> CapabilitiesResponse:
        return self._executor.call(self._surface.capabilities)

    def list_chats(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[ChatSummaryResponse, ...]:
        return self._executor.call(
            lambda: self._surface.list_chats(
                limit=limit,
                offset=offset,
            )
        )

    def create_chat(
        self,
        chat_id: str | None = None,
    ) -> ChatThreadResponse:
        if chat_id is None:
            return self._executor.call(
                self._surface.create_chat
            )

        return self._executor.call(
            lambda: self._surface.create_chat(
                chat_id
            )
        )

    def load_chat(self, chat_id: str) -> ChatThreadResponse:
        return self._executor.call(
            lambda: self._surface.load_chat(chat_id)
        )

    def provider_health(self) -> ProviderHealthResponse:
        return self._executor.call(self._surface.provider_health)

    def remember_chat_message(
        self,
        chat_id: str,
        message_id: str,
        *,
        revision_id: str,
    ) -> RememberedChatMessageResponse:
        return self._executor.call(
            lambda: self._surface.remember_chat_message(
                chat_id,
                message_id,
                revision_id=revision_id,
            )
        )

    def extract_chat_message_knowledge(
        self,
        chat_id: str,
        message_id: str,
        *,
        revision_id: str,
        requested_model_id: str | None = None,
        effective_context_limit: int | None = None,
        max_output_tokens: int | None = None,
    ) -> MessageKnowledgeExtractionResponse:
        return self._executor.call(
            lambda: self._surface.extract_chat_message_knowledge(
                chat_id,
                message_id,
                revision_id=revision_id,
                requested_model_id=requested_model_id,
                effective_context_limit=effective_context_limit,
                max_output_tokens=max_output_tokens,
            )
        )

    def prepare_knowledge_review(
        self,
        processing_run_id: str,
    ) -> KnowledgeReviewResponse:
        return self._executor.call(
            lambda: self._surface.prepare_knowledge_review(processing_run_id)
        )

    def load_knowledge_merge_review(
        self,
        review_id: str,
    ) -> KnowledgeMergeReviewResponse:
        return self._executor.call(
            lambda: self._surface.load_knowledge_merge_review(review_id)
        )

    def resolve_knowledge_merge_review(
        self,
        review_id: str,
        *,
        decision: str,
    ) -> KnowledgeMergeReviewResponse:
        return self._executor.call(
            lambda: self._surface.resolve_knowledge_merge_review(
                review_id,
                decision=decision,
            )
        )

    def preview_chat_deletion(self, chat_id: str) -> DeletionPreviewResponse:
        return self._executor.call(
            lambda: self._surface.preview_chat_deletion(chat_id)
        )

    def delete_chat(
        self,
        chat_id: str,
        *,
        preview_digest: str,
    ) -> DeletionResultResponse:
        return self._executor.call(
            lambda: self._surface.delete_chat(
                chat_id,
                preview_digest=preview_digest,
            )
        )

    def list_models(self) -> tuple[ModelResponse, ...]:
        return self._executor.call(self._surface.list_models)

    def send_chat_message(
        self,
        chat_id: str,
        *,
        content: str,
        requested_model_id: str | None = None,
        operation_id: str | None = None,
        effective_context_limit: int | None = None,
        max_output_tokens: int | None = None,
        temperature: float | None = None,
        thinking_enabled: bool | None = None,
    ) -> ChatThreadResponse:
        if operation_id is None:
            if (
                effective_context_limit is None
                and max_output_tokens is None
                and temperature is None
                and thinking_enabled is None
            ):
                return self._executor.call(
                    lambda: self._surface.send_chat_message(
                        chat_id,
                        content=content,
                        requested_model_id=requested_model_id,
                    )
                )

            if (
                max_output_tokens is None
                and temperature is None
                and thinking_enabled is None
            ):
                return self._executor.call(
                    lambda: self._surface.send_chat_message(
                        chat_id,
                        content=content,
                        requested_model_id=requested_model_id,
                        effective_context_limit=effective_context_limit,
                    )
                )

            return self._executor.call(
                lambda: self._surface.send_chat_message(
                    chat_id,
                    content=content,
                    requested_model_id=requested_model_id,
                    effective_context_limit=effective_context_limit,
                    max_output_tokens=max_output_tokens,
                    temperature=temperature,
                    thinking_enabled=thinking_enabled,
                )
            )

        if (
            effective_context_limit is None
            and max_output_tokens is None
            and temperature is None
            and thinking_enabled is None
        ):
            return self._executor.call(
                lambda: self._surface.send_chat_message(
                    chat_id,
                    content=content,
                    requested_model_id=requested_model_id,
                    operation_id=operation_id,
                )
            )

        if (
            max_output_tokens is None
            and temperature is None
            and thinking_enabled is None
        ):
            return self._executor.call(
                lambda: self._surface.send_chat_message(
                    chat_id,
                    content=content,
                    requested_model_id=requested_model_id,
                    operation_id=operation_id,
                    effective_context_limit=effective_context_limit,
                )
            )

        return self._executor.call(
            lambda: self._surface.send_chat_message(
                chat_id,
                content=content,
                requested_model_id=requested_model_id,
                operation_id=operation_id,
                effective_context_limit=effective_context_limit,
                max_output_tokens=max_output_tokens,
                temperature=temperature,
                thinking_enabled=thinking_enabled,
            )
        )

    def send_unified_local_chat_message(
        self,
        chat_id: str,
        *,
        content: str,
        requested_model_id: str | None = None,
        requested_embedding_model_id: str | None = None,
        effective_context_limit: int | None = None,
        max_output_tokens: int | None = None,
        temperature: float | None = None,
        thinking_enabled: bool | None = None,
    ) -> GroundedChatResponse:
        if (
            effective_context_limit is None
            and max_output_tokens is None
            and temperature is None
            and thinking_enabled is None
        ):
            return self._executor.call(
                lambda: self._surface.send_unified_local_chat_message(
                    chat_id,
                    content=content,
                    requested_model_id=requested_model_id,
                    requested_embedding_model_id=requested_embedding_model_id,
                )
            )
        if (
            max_output_tokens is None
            and temperature is None
            and thinking_enabled is None
        ):
            return self._executor.call(
                lambda: self._surface.send_unified_local_chat_message(
                    chat_id,
                    content=content,
                    requested_model_id=requested_model_id,
                    requested_embedding_model_id=requested_embedding_model_id,
                    effective_context_limit=effective_context_limit,
                )
            )
        return self._executor.call(
            lambda: self._surface.send_unified_local_chat_message(
                chat_id,
                content=content,
                requested_model_id=requested_model_id,
                requested_embedding_model_id=requested_embedding_model_id,
                effective_context_limit=effective_context_limit,
                max_output_tokens=max_output_tokens,
                temperature=temperature,
                thinking_enabled=thinking_enabled,
            )
        )
