from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from athena.chat.repository import ChatRepository
from athena.chat.service import ChatService
from athena.model.provenance import ModelSignature
from athena.retrieval.context import ContextBuilderService
from athena.retrieval.context_package import (
    ContextPackageBudget,
    ContextPackageService,
    ContextSnapshotDriftError,
    ContextTokenEstimates,
)
from athena.retrieval.ranking import RankedSearchResult
from athena.retrieval.search import SearchEntityType
from athena.storage.database import SQLiteDatabase


def _signature() -> ModelSignature:
    return ModelSignature(
        model_signature_id=uuid.uuid4(),
        provider="lm_studio",
        model_identifier="primary",
        model_revision=None,
        quantization="Q4_K_M",
        generation_parameters_json=(
            '{"max_output_tokens":1000,"reasoning_mode":"off"}'
        ),
        context_configuration_json='{"context_package_version":1}',
        signature_hash=b"s" * 32,
        created_at_us=1,
    )


def _ranked(text: str) -> RankedSearchResult:
    return RankedSearchResult(
        entity_id=uuid.uuid4(),
        revision_id=uuid.uuid4(),
        entity_type=SearchEntityType.KNOWLEDGE,
        title="Knowledge",
        snippet=text,
        text=text,
        score=0.9,
        lexical_score=1.0,
        authority_score=1.0,
        contradiction_score=0.0,
        contradiction_count=0,
        duplicate_count=0,
        duplicate_entity_ids=(),
    )


def _database(tmp_path: Path) -> SQLiteDatabase:
    database = SQLiteDatabase(tmp_path / "athena.db")
    database.start()
    return database


def test_context_package_contains_required_structured_fields_and_exact_refs(tmp_path) -> None:
    database = _database(tmp_path)
    try:
        chat = ChatService(ChatRepository(database))
        chat_id = chat.create_chat()
        prior = chat.add_user_message(chat_id=chat_id, content="Vorherige Frage")
        service = ContextPackageService(database)
        retrieval_snapshot = service.current_commit_seq()

        source = _ranked("Berlin ist die Hauptstadt von Deutschland.")
        context = ContextBuilderService().build_from_ranked(
            query="Was ist die Hauptstadt?",
            results=(source,),
            max_estimated_tokens=800,
        )

        current = chat.add_user_message(
            chat_id=chat_id,
            content="Was ist die Hauptstadt?",
        )
        package_snapshot = service.assert_user_commit_follows(
            retrieval_snapshot,
            current,
        )
        system_text = "GROUNDING\n" + context.rendered_text
        package = service.build(
            model_signature=_signature(),
            context=context,
            system_text=system_text,
            prior_messages=(prior,),
            current_user_message=current,
            budget=ContextPackageBudget(
                effective_context_limit=4096,
                context_budget=800,
                output_reserve=1000,
                safety_margin=200,
            ),
            token_estimates=ContextTokenEstimates(
                conversation_tokens=10,
                current_user_tokens=10,
                system_tokens=100,
                context_tokens=context.estimated_tokens,
                estimated_input_tokens=120,
                estimated_total_tokens=1320,
            ),
            snapshot_commit_seq=package_snapshot,
            retrieval_candidate_count=1,
            memory_candidate_count=0,
        )

        snapshot = package.run_snapshot()
        required = {
            "request_id",
            "model_signature",
            "budget",
            "sections",
            "included_refs",
            "excluded_candidate_summary",
            "token_estimates",
            "snapshot_commit_seq",
        }
        assert required <= snapshot.keys()
        assert package.snapshot_commit_seq == package_snapshot
        assert package.current_user_ref().entity_id == current.message_id
        assert package.current_user_ref().revision_id == current.revision_id

        refs = {(item.entity_type, item.entity_id) for item in package.included_refs}
        assert ("knowledge", source.entity_id) in refs
        assert ("chat_message", prior.message_id) in refs
        assert ("chat_message", current.message_id) in refs

        messages = package.model_messages()
        assert [message.role for message in messages] == ["system", "user", "user"]
        assert messages[-1].content == "Was ist die Hauptstadt?"

        persisted_snapshot = json.dumps(snapshot, ensure_ascii=False)
        assert "Berlin ist die Hauptstadt von Deutschland." not in persisted_snapshot
        assert "content_sha256" in persisted_snapshot
    finally:
        database.stop()


def test_context_package_snapshot_guard_rejects_canonical_drift(tmp_path) -> None:
    database = _database(tmp_path)
    try:
        chat = ChatService(ChatRepository(database))
        chat_id = chat.create_chat()
        service = ContextPackageService(database)
        snapshot = service.current_commit_seq()

        chat.add_user_message(chat_id=chat_id, content="Concurrent write")

        with pytest.raises(ContextSnapshotDriftError, match="Canonical state changed"):
            service.assert_snapshot_current(snapshot, phase="unit-test")
    finally:
        database.stop()


def test_user_commit_guard_rejects_intervening_canonical_write(tmp_path) -> None:
    database = _database(tmp_path)
    try:
        chat = ChatService(ChatRepository(database))
        first_chat = chat.create_chat()
        second_chat = chat.create_chat()
        service = ContextPackageService(database)
        snapshot = service.current_commit_seq()

        chat.add_user_message(chat_id=second_chat, content="Intervening write")
        current = chat.add_user_message(chat_id=first_chat, content="Current request")

        with pytest.raises(ContextSnapshotDriftError, match="only new commit"):
            service.assert_user_commit_follows(snapshot, current)
    finally:
        database.stop()



def test_context_package_removes_turn_local_markers_only_from_prior_conversation(
    tmp_path,
) -> None:
    database = _database(tmp_path)

    try:
        chat = ChatService(
            ChatRepository(database)
        )

        chat_id = chat.create_chat()

        prior_user = chat.add_user_message(
            chat_id=chat_id,
            content="Earlier user reference [CTX-777].",
        )

        prior_assistant = chat.add_assistant_message(
            chat_id=chat_id,
            content=(
                "Earlier answer used 7319 [CTX-001], "
                "[SOURCE:CTX-002].\n\n"
                'ATHENA_PROVENANCE '
                '{"athena_provenance_version":3,"evidence":[]}'
            ),
            provider_id="lm_studio",
            model_id="primary",
        )

        service = ContextPackageService(
            database
        )

        retrieval_snapshot = (
            service.current_commit_seq()
        )

        context = (
            ContextBuilderService()
            .build_from_ranked(
                query="Current request",
                results=(),
                max_estimated_tokens=800,
            )
        )

        current = chat.add_user_message(
            chat_id=chat_id,
            content="Current request [CTX-999].",
        )

        package_snapshot = (
            service.assert_user_commit_follows(
                retrieval_snapshot,
                current,
            )
        )

        package = service.build(
            model_signature=_signature(),
            context=context,
            system_text=(
                "GROUNDING\n"
                + context.rendered_text
            ),
            prior_messages=(
                prior_user,
                prior_assistant,
            ),
            current_user_message=current,
            budget=ContextPackageBudget(
                effective_context_limit=4096,
                context_budget=800,
                output_reserve=1000,
                safety_margin=200,
            ),
            token_estimates=ContextTokenEstimates(
                conversation_tokens=100,
                current_user_tokens=20,
                system_tokens=100,
                context_tokens=(
                    context.estimated_tokens
                ),
                estimated_input_tokens=220,
                estimated_total_tokens=1420,
            ),
            snapshot_commit_seq=(
                package_snapshot
            ),
            retrieval_candidate_count=0,
            memory_candidate_count=0,
        )

        messages = package.model_messages()

        assert [
            item.role
            for item in messages
        ] == [
            "system",
            "user",
            "assistant",
            "user",
        ]

        assert (
            messages[1].content
            == "Earlier user reference."
        )

        assert (
            messages[2].content
            == "Earlier answer used 7319."
        )

        # CURRENT-USER is not rewritten.
        assert (
            messages[3].content
            == "Current request [CTX-999]."
        )

        # Canonical persisted history is untouched.
        thread = chat.load_chat(
            chat_id
        )

        assert (
            thread.messages[0].content
            == "Earlier user reference [CTX-777]."
        )

        assert (
            thread.messages[1].content
            == (
                "Earlier answer used 7319 [CTX-001], "
                "[SOURCE:CTX-002].\n\n"
                'ATHENA_PROVENANCE '
                '{"athena_provenance_version":3,"evidence":[]}'
            )
        )

    finally:
        database.stop()
