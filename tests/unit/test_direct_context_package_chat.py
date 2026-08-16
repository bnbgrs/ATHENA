from __future__ import annotations

import json
from collections.abc import Iterator, Sequence

import pytest

from athena.chat.direct import DirectChatService
from athena.chat.generation import ChatGenerationService
from athena.chat.repository import ChatRepository
from athena.chat.service import ChatService
from athena.model.domain import (
    ModelChatMessage,
    ModelInfo,
    ProviderHealth,
    ProviderHealthStatus,
)
from athena.model.provenance import ModelRunRepository
from athena.retrieval.context_package import ContextPackageService, ContextSnapshotDriftError
from athena.storage.database import SQLiteDatabase


class FakeProvider:
    provider_id = "lm_studio"

    def __init__(self, *, drift_on_discover_call: int | None = None, drift=None) -> None:
        self.discover_calls = 0
        self.stream_calls = 0
        self.requests: list[tuple[ModelChatMessage, ...]] = []
        self.drift_on_discover_call = drift_on_discover_call
        self.drift = drift

    def health(self) -> ProviderHealth:
        return ProviderHealth(ProviderHealthStatus.READY)

    def discover_models(self) -> tuple[ModelInfo, ...]:
        self.discover_calls += 1
        if (
            self.drift_on_discover_call is not None
            and self.discover_calls == self.drift_on_discover_call
            and self.drift is not None
        ):
            self.drift()
        return (
            ModelInfo(
                provider="lm_studio",
                backend_model_id="primary",
                display_name="primary",
                model_type="llm",
                context_capacity=32768,
                quantization="Q4_K_M",
                loaded=True,
                vision=False,
                trained_for_tool_use=False,
                loaded_context_length=4096,
            ),
        )

    def stream_chat(
        self,
        *,
        model_id: str,
        messages: Sequence[ModelChatMessage],
        max_output_tokens: int | None = None,
        reasoning_mode: str | None = None,
    ) -> Iterator[str]:
        assert model_id == "primary"
        assert max_output_tokens == 1000
        assert reasoning_mode == "off"
        self.stream_calls += 1
        self.requests.append(tuple(messages))
        yield "direct answer"


def _runtime(tmp_path, provider: FakeProvider):
    database = SQLiteDatabase(tmp_path / "athena.db")
    database.start()
    chat = ChatService(ChatRepository(database))
    generation = ChatGenerationService(chat, provider)
    runs = ModelRunRepository(database)
    service = DirectChatService(
        chat_generation=generation,
        context_packages=ContextPackageService(database),
        model_runs=runs,
    )
    return database, chat, runs, service


def test_direct_chat_is_bounded_and_provider_receives_only_package(tmp_path) -> None:
    provider = FakeProvider()
    database, chat, runs, service = _runtime(tmp_path, provider)
    try:
        chat_id = chat.create_chat()
        chat.add_user_message(chat_id=chat_id, content="old user")
        chat.add_assistant_message(
            chat_id=chat_id,
            content="old assistant",
            provider_id="lm_studio",
            model_id="primary",
        )
        recent_user = chat.add_user_message(
            chat_id=chat_id,
            content="recent user [CTX-777]",
        )
        recent_assistant = chat.add_assistant_message(
            chat_id=chat_id,
            content=(
                "recent assistant [CTX-001], "
                "[SOURCE:CTX-002].\n\n"
                'ATHENA_PROVENANCE '
                '{"athena_provenance_version":3,"evidence":[]}'
            ),
            provider_id="lm_studio",
            model_id="primary",
        )

        result = service.send_message(
            chat_id=chat_id,
            content="current user",
            requested_model_id="primary",
            max_recent_conversation_turns=1,
            output_reserve=1000,
            safety_margin=100,
        )

        assert provider.stream_calls == 1
        sent = provider.requests[0]
        assert tuple((item.role, item.content) for item in sent) == (
            ("user", "recent user"),
            ("assistant", "recent assistant."),
            ("user", "current user"),
        )

        assert all(
            "CTX-" not in item.content
            for item in sent[:-1]
        )
        assert all(
            "ATHENA_PROVENANCE" not in item.content
            for item in sent[:-1]
        )

        persisted = chat.load_chat(chat_id).messages

        assert (
            persisted[2].content
            == "recent user [CTX-777]"
        )

        assert (
            persisted[3].content
            == (
                "recent assistant [CTX-001], "
                "[SOURCE:CTX-002].\n\n"
                'ATHENA_PROVENANCE '
                '{"athena_provenance_version":3,"evidence":[]}'
            )
        )
        assert tuple(
            (item.role, item.content)
            for item in result.context_package.model_messages()
        ) == tuple((item.role, item.content) for item in sent)

        snapshot = json.loads(result.processing_run.input_snapshot_json)
        assert snapshot["excluded_candidate_summary"]["conversation_candidate_count"] == 4
        assert snapshot["excluded_candidate_summary"]["conversation_included_count"] == 2
        assert snapshot["excluded_candidate_summary"]["conversation_excluded_count"] == 2
        refs = snapshot["included_refs"]
        assert any(
            item["entity_id"] == str(recent_user.message_id)
            and item["revision_id"] == str(recent_user.revision_id)
            for item in refs
        )
        assert any(
            item["entity_id"] == str(recent_assistant.message_id)
            and item["revision_id"] == str(recent_assistant.revision_id)
            for item in refs
        )
        assert result.processing_run.status == "succeeded"
        assert runs.load_signature(
            result.context_package.model_signature.model_signature_id
        ).model_identifier == "primary"
    finally:
        database.stop()


def test_direct_chat_pre_provider_drift_makes_zero_provider_calls(tmp_path) -> None:
    database = SQLiteDatabase(tmp_path / "athena.db")
    database.start()
    try:
        chat = ChatService(ChatRepository(database))
        target_chat = chat.create_chat()
        drift_chat = chat.create_chat()

        def drift() -> None:
            chat.add_user_message(chat_id=drift_chat, content="concurrent write")

        provider = FakeProvider(drift_on_discover_call=2, drift=drift)
        service = DirectChatService(
            chat_generation=ChatGenerationService(chat, provider),
            context_packages=ContextPackageService(database),
            model_runs=ModelRunRepository(database),
        )

        with pytest.raises(ContextSnapshotDriftError):
            service.send_message(
                chat_id=target_chat,
                content="current",
                requested_model_id="primary",
                output_reserve=1000,
                safety_margin=100,
            )

        assert provider.stream_calls == 0
        messages = chat.load_chat(target_chat).messages
        assert len(messages) == 1
        assert messages[0].content == "current"
        row = database.connection.execute(
            "SELECT status, error_detail FROM processing_runs"
        ).fetchone()
        assert row is not None
        assert str(row["status"]) == "failed"
        assert "ContextSnapshotDriftError" in str(row["error_detail"])
    finally:
        database.stop()
