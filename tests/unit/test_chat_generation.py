from __future__ import annotations

import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

import pytest

from athena.chat.generation import ChatGenerationService, ModelSelectionError
from athena.chat.grounding import (
    GroundingContract,
    GroundingEvidenceRef,
    GroundingViolation,
)
from athena.chat.models import MessageType
from athena.chat.repository import ChatRepository
from athena.chat.service import ChatService
from athena.model.domain import ModelChatMessage, ModelInfo, ProviderHealth, ProviderHealthStatus
from athena.storage.database import SQLiteDatabase


class FakeInteractiveDemand:
    def __init__(self) -> None:
        self.active = False
        self.entries = 0
        self.exits = 0
        self.purposes: list[str] = []
        self.renewals = 0
        self.forced_renewals = 0
        self.lease = object()

    @contextmanager
    def interactive_session(
        self,
        *,
        purpose: str = "chat_generation",
    ) -> Iterator[object]:
        assert not self.active
        self.active = True
        self.entries += 1
        self.purposes.append(purpose)
        try:
            yield self.lease
        finally:
            self.active = False
            self.exits += 1

    def renew_interactive_demand(
        self,
        lease,
        *,
        force: bool = False,
    ):
        assert self.active
        assert lease is self.lease
        self.renewals += 1
        if force:
            self.forced_renewals += 1
        return lease


class FakeProvider:
    provider_id = "lm_studio"

    def __init__(self, models: tuple[ModelInfo, ...], chunks: tuple[str, ...]) -> None:
        self.models = models
        self.chunks = chunks
        self.requests: list[tuple[str, tuple[ModelChatMessage, ...]]] = []
        self.controls: list[tuple[int | None, str | None]] = []

    def health(self) -> ProviderHealth:
        return ProviderHealth(ProviderHealthStatus.READY)

    def discover_models(self) -> tuple[ModelInfo, ...]:
        return self.models

    def stream_chat(
        self,
        *,
        model_id: str,
        messages: Sequence[ModelChatMessage],
        max_output_tokens: int | None = None,
        reasoning_mode: str | None = None,
    ) -> Iterator[str]:
        self.requests.append((model_id, tuple(messages)))
        self.controls.append((max_output_tokens, reasoning_mode))
        yield from self.chunks


def _model(model_id: str = "example/model", *, loaded: bool = True) -> ModelInfo:
    return ModelInfo(
        provider="lm_studio",
        backend_model_id=model_id,
        display_name=model_id,
        model_type="llm",
        context_capacity=32768,
        quantization="Q4_K_M",
        loaded=loaded,
        vision=False,
        trained_for_tool_use=False,
        loaded_context_length=32768,
    )


def _chat_service(tmp_path: Path) -> tuple[SQLiteDatabase, ChatService]:
    database = SQLiteDatabase(tmp_path / "athena.db")
    database.start()
    return database, ChatService(ChatRepository(database))


def test_streamed_reply_is_persisted_only_after_completion(tmp_path) -> None:
    database, chat = _chat_service(tmp_path)
    try:
        chat_id = chat.create_chat()
        provider = FakeProvider((_model(),), ("Hello", " world"))
        service = ChatGenerationService(chat, provider)
        visible: list[str] = []

        result = service.send_message(
            chat_id=chat_id,
            content="Say hello",
            on_delta=visible.append,
        )

        assert visible == ["Hello", " world"]
        assert result.assistant_message.content == "Hello world"
        thread = chat.load_chat(chat_id)
        assert [message.message_type for message in thread.messages] == [
            MessageType.USER,
            MessageType.ASSISTANT,
        ]
        assert [message.content for message in thread.messages] == [
            "Say hello",
            "Hello world",
        ]
        assert provider.requests == [
            (
                "example/model",
                (ModelChatMessage(role="user", content="Say hello"),),
            )
        ]
    finally:
        database.stop()


def test_generation_forwards_explicit_reasoning_off_with_output_cap(tmp_path) -> None:
    database, chat = _chat_service(tmp_path)
    try:
        chat_id = chat.create_chat()
        provider = FakeProvider((_model(),), ("bounded answer",))
        service = ChatGenerationService(chat, provider)

        service.send_message(
            chat_id=chat_id,
            content="Answer without hidden reasoning",
            max_output_tokens=1000,
            reasoning_mode="off",
        )

        assert provider.controls == [(1000, "off")]
    finally:
        database.stop()


def test_second_turn_uses_athena_persisted_history(tmp_path) -> None:
    database, chat = _chat_service(tmp_path)
    try:
        chat_id = chat.create_chat()
        provider = FakeProvider((_model(),), ("First answer",))
        service = ChatGenerationService(chat, provider)
        service.send_message(chat_id=chat_id, content="First question")

        provider.chunks = ("Second answer",)
        service.send_message(chat_id=chat_id, content="Second question")

        _, history = provider.requests[-1]
        assert history == (
            ModelChatMessage(role="user", content="First question"),
            ModelChatMessage(role="assistant", content="First answer"),
            ModelChatMessage(role="user", content="Second question"),
        )
    finally:
        database.stop()


def test_cancelled_stream_does_not_persist_partial_assistant(tmp_path) -> None:
    database, chat = _chat_service(tmp_path)
    try:
        chat_id = chat.create_chat()
        provider = FakeProvider((_model(),), ("partial", " never seen"))
        service = ChatGenerationService(chat, provider)

        def cancel_on_first_delta(_chunk: str) -> None:
            raise KeyboardInterrupt

        with pytest.raises(KeyboardInterrupt):
            service.send_message(
                chat_id=chat_id,
                content="Cancel this",
                on_delta=cancel_on_first_delta,
            )

        thread = chat.load_chat(chat_id)
        assert len(thread.messages) == 1
        assert thread.messages[0].message_type is MessageType.USER
        assert thread.messages[0].content == "Cancel this"
    finally:
        database.stop()


def test_multiple_loaded_models_require_explicit_selection(tmp_path) -> None:
    database, chat = _chat_service(tmp_path)
    try:
        provider = FakeProvider((_model("one"), _model("two")), ("unused",))
        service = ChatGenerationService(chat, provider)

        with pytest.raises(ModelSelectionError, match="Multiple loaded LLMs"):
            service.select_model()

        assert service.select_model("two").backend_model_id == "two"
    finally:
        database.stop()


def test_unloaded_explicit_model_is_rejected(tmp_path) -> None:
    database, chat = _chat_service(tmp_path)
    try:
        provider = FakeProvider((_model("cold", loaded=False),), ("unused",))
        service = ChatGenerationService(chat, provider)

        with pytest.raises(ModelSelectionError, match="not loaded"):
            service.select_model("cold")
    finally:
        database.stop()


def test_unreferenced_retrieved_context_is_rejected_before_persistence(tmp_path) -> None:
    database, chat = _chat_service(tmp_path)
    try:
        chat_id = chat.create_chat()
        provider = FakeProvider((_model(),), ("unused",))
        service = ChatGenerationService(chat, provider)

        with pytest.raises(ValueError, match="without durable grounding references"):
            service.send_message(
                chat_id=chat_id,
                content="What is remembered?",
                retrieved_context='{"items":[{"text":"untraceable"}]}',
            )

        assert provider.requests == []
        assert chat.load_chat(chat_id).messages == ()
    finally:
        database.stop()


def test_grounded_answer_is_validated_before_assistant_persistence(tmp_path) -> None:
    database, chat = _chat_service(tmp_path)
    try:
        chat_id = chat.create_chat()
        provider = FakeProvider((_model(),), ("Unsupported answer [CTX-999]",))
        service = ChatGenerationService(chat, provider)

        with pytest.raises(GroundingViolation, match="not supplied"):
            service.send_message(
                chat_id=chat_id,
                content="What is remembered?",
                retrieved_context='{"items":[{"context_id":"CTX-001"}]}',
                grounding_contract=GroundingContract(
                    evidence_refs=(
                        GroundingEvidenceRef(
                            context_id="CTX-001",
                            entity_type="knowledge",
                            entity_id=uuid.uuid4(),
                            revision_id=uuid.uuid4(),
                        ),
                    ),
                ),
            )

        thread = chat.load_chat(chat_id)
        assert [message.message_type for message in thread.messages] == [
            MessageType.USER,
        ]
    finally:
        database.stop()


def test_valid_grounded_answer_persists_with_grounding_report(tmp_path) -> None:
    database, chat = _chat_service(tmp_path)
    try:
        chat_id = chat.create_chat()
        provider = FakeProvider((_model(),), ("Stored evidence. [CTX-001]",))
        service = ChatGenerationService(chat, provider)

        result = service.send_message(
            chat_id=chat_id,
            content="What is remembered?",
            retrieved_context='{"items":[{"context_id":"CTX-001"}]}',
            grounding_contract=GroundingContract(
                evidence_refs=(
                    GroundingEvidenceRef(
                        context_id="CTX-001",
                        entity_type="knowledge",
                        entity_id=uuid.uuid4(),
                        revision_id=uuid.uuid4(),
                    ),
                ),
            ),
        )

        assert result.grounding_report is not None
        assert result.grounding_report.cited_context_ids == ("CTX-001",)
        assert "ATHENA_PROVENANCE" in result.assistant_message.content
        assert '"context_id":"CTX-001"' in result.assistant_message.content
        thread = chat.load_chat(chat_id)
        assert [message.message_type for message in thread.messages] == [
            MessageType.USER,
            MessageType.ASSISTANT,
        ]
    finally:
        database.stop()


def test_persisted_provenance_envelope_is_not_replayed_as_model_history(tmp_path) -> None:
    database, chat = _chat_service(tmp_path)
    try:
        chat_id = chat.create_chat()
        chat.add_user_message(chat_id=chat_id, content="First question")
        chat.add_assistant_message(
            chat_id=chat_id,
            content=(
                "First grounded answer. [MODEL-PRIOR]\n\n"
                'ATHENA_PROVENANCE {"athena_provenance_version":2,"evidence":[],"uses_model_prior":true}'
            ),
            provider_id="lm_studio",
            model_id="example/model",
        )
        provider = FakeProvider((_model(),), ("Second answer",))
        service = ChatGenerationService(chat, provider)

        service.send_message(chat_id=chat_id, content="Second question")

        _, history = provider.requests[-1]
        assert history == (
            ModelChatMessage(role="user", content="First question"),
            ModelChatMessage(
                role="assistant",
                content="First grounded answer. [MODEL-PRIOR]",
            ),
            ModelChatMessage(role="user", content="Second question"),
        )
        persisted = chat.load_chat(chat_id)
        assert "ATHENA_PROVENANCE" in (persisted.messages[1].content or "")
    finally:
        database.stop()


def test_source_grounded_generation_persists_anchor_provenance_without_chunk_id(tmp_path) -> None:
    from athena.retrieval.evidence import EvidenceClass

    database, chat = _chat_service(tmp_path)
    try:
        chat_id = chat.create_chat()
        provider = FakeProvider(
            (_model(),),
            ("The imported source mentions Berlin. [SOURCE:CTX-001]",),
        )
        service = ChatGenerationService(chat, provider)
        anchor_id = uuid.uuid4()
        source_id = uuid.uuid4()
        representation_id = uuid.uuid4()
        quoted_hash = b"s" * 32

        result = service.send_message(
            chat_id=chat_id,
            content="What does the source say?",
            retrieved_context='{"items":[{"context_id":"CTX-001"}]}',
            grounding_contract=GroundingContract(
                evidence_refs=(
                    GroundingEvidenceRef(
                        context_id="CTX-001",
                        entity_type="source_anchor",
                        entity_id=anchor_id,
                        revision_id=None,
                        evidence_class=EvidenceClass.SOURCE,
                        source_id=source_id,
                        representation_id=representation_id,
                        start_offset=0,
                        end_offset=42,
                        quoted_hash=quoted_hash,
                    ),
                ),
            ),
        )

        report = result.grounding_report
        assert report is not None
        assert report.source_context_ids == ("CTX-001",)
        content = result.assistant_message.content or ""
        assert "[SOURCE:CTX-001]" in content
        assert '"athena_provenance_version":3' in content
        assert f'"anchor_id":"{anchor_id}"' in content
        assert f'"source_id":"{source_id}"' in content
        assert f'"representation_id":"{representation_id}"' in content
        assert "chunk_id" not in content
    finally:
        database.stop()


class SequencedGroundingProvider:
    provider_id = "lm_studio"

    def __init__(
        self,
        responses: tuple[
            tuple[str, ...],
            ...,
        ],
    ) -> None:
        self.responses = responses
        self.requests: list[
            tuple[
                str,
                tuple[ModelChatMessage, ...],
            ]
        ] = []
        self.controls: list[
            tuple[
                int | None,
                str | None,
            ]
        ] = []

    def health(
        self,
    ) -> ProviderHealth:
        return ProviderHealth(
            ProviderHealthStatus.READY
        )

    def discover_models(
        self,
    ) -> tuple[ModelInfo, ...]:
        return (
            _model(),
        )

    def stream_chat(
        self,
        *,
        model_id: str,
        messages: Sequence[ModelChatMessage],
        max_output_tokens: int | None = None,
        reasoning_mode: str | None = None,
    ) -> Iterator[str]:
        index = len(
            self.requests
        )

        if index >= len(
            self.responses
        ):
            raise AssertionError(
                "Unexpected extra model attempt."
            )

        self.requests.append(
            (
                model_id,
                tuple(
                    messages
                ),
            )
        )

        self.controls.append(
            (
                max_output_tokens,
                reasoning_mode,
            )
        )

        yield from self.responses[
            index
        ]


def _single_canonical_grounding_contract() -> GroundingContract:
    return GroundingContract(
        evidence_refs=(
            GroundingEvidenceRef(
                context_id="CTX-001",
                entity_type="knowledge",
                entity_id=uuid.uuid4(),
                revision_id=uuid.uuid4(),
            ),
        ),
        allow_model_prior=False,
    )


def test_grounded_generation_retries_once_without_exposing_invalid_candidate(
    tmp_path,
) -> None:
    database, chat = _chat_service(
        tmp_path
    )

    try:
        chat_id = chat.create_chat()

        provider = SequencedGroundingProvider(
            responses=(
                (
                    "Project Atlas has a code.\n"
                    "The code is 1101 [CTX-001].",
                ),
                (
                    "Project Atlas has code 1101 [CTX-001].",
                ),
            )
        )

        service = ChatGenerationService(
            chat,
            provider,
        )

        visible: list[str] = []

        result = service.send_message(
            chat_id=chat_id,
            content=(
                "What is the Project Atlas code?"
            ),
            requested_model_id="example/model",
            on_delta=visible.append,
            retrieved_context=(
                '{"items":[{"context_id":"CTX-001",'
                '"text":"Project Atlas has code 1101."}]}'
            ),
            grounding_contract=(
                _single_canonical_grounding_contract()
            ),
            max_output_tokens=1000,
            reasoning_mode="off",
        )

        assert len(
            provider.requests
        ) == 2

        first_model, first_messages = (
            provider.requests[0]
        )

        second_model, second_messages = (
            provider.requests[1]
        )

        assert first_model == "example/model"
        assert second_model == "example/model"

        first_flattened = "\n".join(
            item.content
            for item
            in first_messages
        )

        second_flattened = "\n".join(
            item.content
            for item
            in second_messages
        )

        assert (
            "ATHENA GROUNDING VALIDATION RETRY"
            not in first_flattened
        )

        assert (
            "ATHENA GROUNDING VALIDATION RETRY"
            in second_flattened
        )

        assert (
            "Grounded answer contains substantive lines "
            "without provenance markers"
            in second_flattened
        )

        # The rejected candidate never reaches the user-facing callback.
        assert all(
            "Project Atlas has a code."
            not in item
            for item
            in visible
        )

        assert any(
            "Project Atlas has code 1101 [CTX-001]."
            in item
            for item
            in visible
        )

        assert any(
            "ATHENA_PROVENANCE"
            in item
            for item
            in visible
        )

        persisted = (
            result.assistant_message
            .content
        )

        assert persisted is not None

        assert (
            "Project Atlas has a code."
            not in persisted
        )

        assert (
            "Project Atlas has code 1101 [CTX-001]."
            in persisted
        )

        thread = chat.load_chat(
            chat_id
        )

        assert [
            item.message_type
            for item
            in thread.messages
        ] == [
            MessageType.USER,
            MessageType.ASSISTANT,
        ]

    finally:
        database.stop()


def test_grounded_generation_retry_remains_fail_closed_after_retry_exhaustion(
    tmp_path,
) -> None:
    database, chat = _chat_service(
        tmp_path
    )

    try:
        chat_id = chat.create_chat()

        provider = SequencedGroundingProvider(
            responses=(
                (
                    "Uncited first candidate.",
                ),
                (
                    "Still uncited after first retry.",
                ),
                (
                    "Still uncited after final retry.",
                ),
            )
        )

        service = ChatGenerationService(
            chat,
            provider,
        )

        visible: list[str] = []

        with pytest.raises(
            GroundingViolation
        ):
            service.send_message(
                chat_id=chat_id,
                content="What is remembered?",
                requested_model_id="example/model",
                on_delta=visible.append,
                retrieved_context=(
                    '{"items":[{"context_id":"CTX-001"}]}'
                ),
                grounding_contract=(
                    _single_canonical_grounding_contract()
                ),
                max_output_tokens=1000,
                reasoning_mode="off",
            )

        assert len(
            provider.requests
        ) == 3

        assert visible == []

        thread = chat.load_chat(
            chat_id
        )

        assert [
            item.message_type
            for item
            in thread.messages
        ] == [
            MessageType.USER,
        ]

    finally:
        database.stop()


def test_grounded_generation_can_recover_on_final_retry(
    tmp_path,
) -> None:
    database, chat = _chat_service(
        tmp_path
    )

    try:
        chat_id = chat.create_chat()

        provider = SequencedGroundingProvider(
            responses=(
                (
                    "Uncited first candidate.",
                ),
                (
                    "Based on the retrieved evidence:\n"
                    "Project Atlas has code 1101 [CTX-001].",
                ),
                (
                    "Project Atlas has code 1101 [CTX-001].",
                ),
            )
        )

        service = ChatGenerationService(
            chat,
            provider,
        )

        visible: list[str] = []

        result = service.send_message(
            chat_id=chat_id,
            content=(
                "What is the exact "
                "Project Atlas code?"
            ),
            requested_model_id="example/model",
            on_delta=visible.append,
            retrieved_context=(
                '{"items":[{"context_id":"CTX-001",'
                '"text":"Project Atlas has code 1101."}]}'
            ),
            grounding_contract=(
                _single_canonical_grounding_contract()
            ),
            max_output_tokens=1000,
            reasoning_mode="off",
        )

        assert len(
            provider.requests
        ) == 3

        assert all(
            (
                "Uncited first candidate."
                not in item
            )
            for item
            in visible
        )

        assert all(
            (
                "Based on the retrieved evidence:"
                not in item
            )
            for item
            in visible
        )

        assert any(
            (
                "Project Atlas has code "
                "1101 [CTX-001]."
                in item
            )
            for item
            in visible
        )

        assert any(
            "ATHENA_PROVENANCE"
            in item
            for item
            in visible
        )

        persisted = (
            result.assistant_message
            .content
        )

        assert persisted is not None

        assert (
            "Project Atlas has code "
            "1101 [CTX-001]."
            in persisted
        )

        assert (
            "Uncited first candidate."
            not in persisted
        )

        assert (
            "Based on the retrieved evidence:"
            not in persisted
        )

        thread = chat.load_chat(
            chat_id
        )

        assert [
            item.message_type
            for item
            in thread.messages
        ] == [
            MessageType.USER,
            MessageType.ASSISTANT,
        ]

    finally:
        database.stop()

def test_provider_generation_runs_inside_interactive_demand_lease(
    tmp_path: Path,
) -> None:
    database, chat = _chat_service(tmp_path)
    try:
        demand = FakeInteractiveDemand()

        class GuardAwareProvider(FakeProvider):
            def stream_chat(
                self,
                *,
                model_id: str,
                messages: Sequence[ModelChatMessage],
                max_output_tokens: int | None = None,
                reasoning_mode: str | None = None,
            ) -> Iterator[str]:
                assert demand.active
                yield from super().stream_chat(
                    model_id=model_id,
                    messages=messages,
                    max_output_tokens=max_output_tokens,
                    reasoning_mode=reasoning_mode,
                )

        chat_id = chat.create_chat()
        provider = GuardAwareProvider(
            (_model(),),
            ("interactive answer",),
        )
        service = ChatGenerationService(
            chat,
            provider,
            interactive_demand=demand,
        )

        result = service.send_message(
            chat_id=chat_id,
            content="Interactive request",
        )

        assert result.assistant_message.content == "interactive answer"
        assert demand.entries == 1
        assert demand.exits == 1
        assert demand.purposes == ["chat_generation"]
        assert demand.forced_renewals == 1
        assert demand.renewals >= 2
        assert not demand.active
    finally:
        database.stop()


def test_interactive_demand_lease_is_released_on_provider_failure(
    tmp_path: Path,
) -> None:
    database, chat = _chat_service(tmp_path)
    try:
        demand = FakeInteractiveDemand()

        class FailingProvider(FakeProvider):
            def stream_chat(
                self,
                *,
                model_id: str,
                messages: Sequence[ModelChatMessage],
                max_output_tokens: int | None = None,
                reasoning_mode: str | None = None,
            ) -> Iterator[str]:
                del model_id, messages, max_output_tokens, reasoning_mode
                assert demand.active
                raise RuntimeError("synthetic provider failure")
                yield  # pragma: no cover

        chat_id = chat.create_chat()
        provider = FailingProvider((_model(),), ())
        service = ChatGenerationService(
            chat,
            provider,
            interactive_demand=demand,
        )

        with pytest.raises(
            RuntimeError,
            match="synthetic provider failure",
        ):
            service.send_message(
                chat_id=chat_id,
                content="Fail safely",
            )

        assert demand.entries == 1
        assert demand.exits == 1
        assert demand.forced_renewals == 1
        assert demand.renewals == 1
        assert not demand.active

        thread = chat.load_chat(chat_id)
        assert len(thread.messages) == 1
        assert thread.messages[0].message_type is MessageType.USER
    finally:
        database.stop()
