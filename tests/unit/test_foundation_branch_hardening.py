from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, replace
from pathlib import Path
from unittest.mock import patch

import pytest

from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.jobs.models import JobState
from athena.jobs.repository import JobLeaseError
from athena.knowledge.models import KnowledgeKind
from athena.model.adapters.lm_studio import (
    LMStudioProvider,
    ProviderProtocolError,
)
from athena.model.adapters.lm_studio_embeddings import LMStudioEmbeddingProvider
from athena.model.domain import ModelChatMessage
from athena.model.provenance import ModelSignature
from athena.research.models import ResearchScopeState, ResearchWorkState
from athena.research.repository import ResearchFenceError
from athena.retrieval.context_package import (
    ContextIncludedRef,
    ContextPackageBudget,
    ContextPackageError,
    ContextPackageService,
    ContextSection,
    ContextTokenEstimates,
    ExcludedCandidateSummary,
)
from athena.retrieval.search import current_search_projection_commit_seq
from athena.retrieval.semantic import LocalSemanticSearchService, SemanticSearchError
from athena.storage.database import SQLiteDatabase
from athena.storage.schema import DatabaseCompatibilityError


def _app(root: Path) -> AthenaApplication:
    app = AthenaApplication(settings=AthenaSettings(local_root=root))
    app.start()
    return app


def _capture(app: AthenaApplication, path: Path, text: str):
    path.write_text(text, encoding="utf-8", newline="")
    return app.sources.capture_file(path)


def _lease_parent(app: AthenaApplication, job_id: uuid.UUID) -> bytes:
    current = app.jobs.get(job_id)
    if current.state is JobState.WAITING:
        app.jobs.wake(job_id)
    leased = app.jobs.acquire(
        job_id,
        worker_id="foundation-hardening-parent",
        lease_seconds=120,
    )
    assert leased.lease_token is not None
    return leased.lease_token


def _advance_parent_to_wait(
    app: AthenaApplication,
    job_id: uuid.UUID,
    *,
    limit: int = 50,
):
    token = _lease_parent(app, job_id)
    for _ in range(limit):
        result = app.research_worker.step(
            job_id,
            lease_token=token,
            extend_seconds=120,
        )
        if result.waiting or result.done:
            return result
    raise AssertionError("Research parent did not reach a waiting/terminal boundary.")


def _drive_parent_to_synthesis_wait(
    app: AthenaApplication,
    job_id: uuid.UUID,
    *,
    limit: int = 50,
):
    token = _lease_parent(app, job_id)
    for _ in range(limit):
        result = app.research_worker.step(
            job_id,
            lease_token=token,
            extend_seconds=120,
        )
        if result.completed_stage == "awaiting_synthesis":
            assert result.waiting
            return result
        if result.waiting:
            raise AssertionError(
                f"Unexpected Research wait before synthesis: {result.completed_stage}"
            )
    raise AssertionError("Research parent did not reach awaiting_synthesis.")


def test_matching_but_expired_job_lease_is_rejected_before_recovery(tmp_path: Path) -> None:
    app = _app(tmp_path / "runtime")
    try:
        job = app.jobs.create(job_type="source.process")
        leased = app.jobs.acquire(
            job.job_id,
            worker_id="expiring-worker",
            lease_seconds=1,
            now_us=1_000_000,
        )
        assert leased.lease_token is not None

        with pytest.raises(JobLeaseError, match="expired"):
            app.jobs.checkpoint(
                job.job_id,
                lease_token=leased.lease_token,
                current_stage="must-not-commit",
                now_us=2_000_001,
            )

        assert app.jobs.checkpoints(job.job_id) == ()
    finally:
        app.stop()


def test_expired_cancel_requested_lease_recovers_to_cancelled(tmp_path: Path) -> None:
    app = _app(tmp_path / "runtime")
    try:
        job = app.jobs.create(job_type="source.process")
        leased = app.jobs.acquire(
            job.job_id,
            worker_id="cancel-worker",
            lease_seconds=1,
            now_us=1_000_000,
        )
        assert leased.lease_token is not None
        requested = app.jobs.request_cancel(job.job_id)
        assert requested.state is JobState.CANCEL_REQUESTED

        recovered = app.jobs.recover_startup(now_us=2_000_001)

        assert [item.job_id for item in recovered] == [job.job_id]
        final = app.jobs.get(job.job_id)
        assert final.state is JobState.CANCELLED
        assert final.blocked_reason == "recovered_cancel_after_expired_lease"
        assert final.lease_token is None
    finally:
        app.stop()


def test_write_transaction_rolls_back_partial_mutation_on_exception(tmp_path: Path) -> None:
    database = SQLiteDatabase(tmp_path / "athena.db")
    database.start()
    try:
        with pytest.raises(RuntimeError, match="force rollback"):
            with database.write_transaction() as connection:
                connection.execute("CREATE TABLE foundation_rollback_probe(value INTEGER)")
                connection.execute(
                    "INSERT INTO foundation_rollback_probe(value) VALUES (1)"
                )
                raise RuntimeError("force rollback")

        row = database.connection.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type = 'table' AND name = 'foundation_rollback_probe'"
        ).fetchone()
        assert row is None
    finally:
        database.stop()


def test_nested_write_transaction_is_rejected_without_ending_outer_transaction(
    tmp_path: Path,
) -> None:
    database = SQLiteDatabase(tmp_path / "athena.db")
    database.start()
    try:
        with database.write_transaction() as connection:
            with pytest.raises(RuntimeError, match="Nested ATHENA"):
                with database.write_transaction():
                    pass
            assert connection.in_transaction
    finally:
        database.stop()


def test_current_schema_metadata_tamper_fails_closed_on_restart(tmp_path: Path) -> None:
    path = tmp_path / "athena.db"
    database = SQLiteDatabase(path)
    database.start()
    database.stop()

    raw = sqlite3.connect(path, autocommit=True)
    try:
        raw.execute(
            "UPDATE schema_metadata SET schema_version = schema_version - 1 "
            "WHERE singleton_id = 1"
        )
    finally:
        raw.close()

    reopened = SQLiteDatabase(path)
    with pytest.raises(DatabaseCompatibilityError, match="schema_metadata"):
        reopened.start()


def test_current_schema_foreign_key_corruption_fails_closed_on_restart(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runtime"
    app = _app(root)
    job = app.jobs.create(job_type="source.process")
    db_path = app.database.path
    app.stop()

    raw = sqlite3.connect(db_path, autocommit=True)
    try:
        raw.execute("PRAGMA foreign_keys = OFF")
        raw.execute(
            "UPDATE jobs SET created_by_actor_id = ? WHERE job_id = ?",
            (uuid.uuid4().bytes, job.job_id.bytes),
        )
    finally:
        raw.close()

    reopened = SQLiteDatabase(db_path)
    with pytest.raises(DatabaseCompatibilityError, match="foreign-key"):
        reopened.start()


def test_research_corrupt_raw_blob_is_failed_not_unavailable_or_irrelevant(
    tmp_path: Path,
) -> None:
    app = _app(tmp_path / "runtime")
    try:
        captured = _capture(
            app,
            tmp_path / "corrupt.txt",
            "Research corruption classification evidence.",
        )
        stored = app.blob_store.resolve_blob_path(
            storage_area=captured.blob.storage_area,
            storage_locator=captured.blob.storage_locator,
        )
        stored.write_text("tampered bytes", encoding="utf-8")

        job = app.research.enqueue_local(
            query="Classify corrupt source.",
            explicit_source_ids=(captured.source.source_id,),
        )
        result = _advance_parent_to_wait(app, job.job_id)

        assert result.completed_stage == "awaiting_synthesis"
        scope = app.research.initialize(job.job_id)
        work = app.research_repository.list_work_items(scope.scope_id)
        assert len(work) == 1
        assert work[0].state is ResearchWorkState.FAILED
        coverage = app.research.coverage(job.job_id)
        assert coverage.failed_count == 1
        assert coverage.unavailable_count == 0
        assert coverage.irrelevant_count == 0
        assert coverage.coverage_ratio == 0.0
    finally:
        app.stop()


@pytest.mark.parametrize(
    ("terminal_mode", "expected_child_state"),
    (
        ("failed", JobState.FAILED),
        ("cancelled", JobState.CANCELLED),
        ("completed_without_output", JobState.COMPLETED),
    ),
)
def test_research_terminal_processing_child_without_ready_source_is_failed(
    tmp_path: Path,
    terminal_mode: str,
    expected_child_state: JobState,
) -> None:
    app = _app(tmp_path / terminal_mode)
    try:
        captured = _capture(
            app,
            tmp_path / f"{terminal_mode}.txt",
            "Processing child terminal-state evidence.",
        )
        job = app.research.enqueue_local(
            query="Processing child failure visibility.",
            explicit_source_ids=(captured.source.source_id,),
        )
        waiting = _advance_parent_to_wait(app, job.job_id)
        assert waiting.completed_stage == "waiting_source_processing"

        scope = app.research.initialize(job.job_id)
        work = app.research_repository.list_work_items(scope.scope_id)
        assert len(work) == 1
        child_id = work[0].source_processing_job_id
        assert child_id is not None

        if terminal_mode == "cancelled":
            child = app.jobs.request_cancel(child_id)
        else:
            leased_child = app.jobs.acquire(
                child_id,
                worker_id=f"child-{terminal_mode}",
                lease_seconds=60,
            )
            assert leased_child.lease_token is not None
            if terminal_mode == "failed":
                child = app.jobs.fail(
                    child_id,
                    lease_token=leased_child.lease_token,
                    blocked_reason="forced_processing_failure",
                )
            else:
                child = app.jobs.complete(
                    child_id,
                    lease_token=leased_child.lease_token,
                )
        assert child.state is expected_child_state

        result = _drive_parent_to_synthesis_wait(app, job.job_id)
        assert result.completed_stage == "awaiting_synthesis"
        refreshed = app.research_repository.get_work_item(work[0].work_item_id)
        assert refreshed.state is ResearchWorkState.FAILED
        coverage = app.research.coverage(job.job_id)
        assert coverage.failed_count == 1
        assert coverage.coverage_ratio == 0.0
    finally:
        app.stop()


@pytest.mark.parametrize(
    ("run_child", "expected_child_state"),
    (
        (False, JobState.CANCELLED),
        (True, JobState.CANCEL_REQUESTED),
    ),
)
def test_research_cancel_propagates_to_linked_processing_child(
    tmp_path: Path,
    run_child: bool,
    expected_child_state: JobState,
) -> None:
    app = _app(tmp_path / ("running" if run_child else "queued"))
    try:
        captured = _capture(
            app,
            tmp_path / "cancel-child.txt",
            "Linked child cancellation evidence.",
        )
        job = app.research.enqueue_local(
            query="Cancel linked work.",
            explicit_source_ids=(captured.source.source_id,),
        )
        waiting = _advance_parent_to_wait(app, job.job_id)
        assert waiting.completed_stage == "waiting_source_processing"

        scope = app.research.initialize(job.job_id)
        work = app.research_repository.list_work_items(scope.scope_id)
        child_id = work[0].source_processing_job_id
        assert child_id is not None

        if run_child:
            leased_child = app.jobs.acquire(
                child_id,
                worker_id="linked-running-child",
                lease_seconds=120,
            )
            assert leased_child.state is JobState.RUNNING

        parent = app.research.cancel(job.job_id)

        assert parent.state is JobState.CANCELLED
        assert app.jobs.get(child_id).state is expected_child_state
        assert (
            app.research_repository.get_scope(scope.scope_id).state
            is ResearchScopeState.PARTIAL
        )
    finally:
        app.stop()


def test_research_stale_parent_fence_rejects_work_state_commit(tmp_path: Path) -> None:
    app = _app(tmp_path / "runtime")
    try:
        captured = _capture(
            app,
            tmp_path / "fence.txt",
            "Research stale fence evidence.",
        )
        job = app.research.enqueue_local(
            query="Fence research work.",
            explicit_source_ids=(captured.source.source_id,),
        )
        scope = app.research.initialize(job.job_id)
        app.research.freeze_candidates(job.job_id)
        work = app.research_repository.list_work_items(scope.scope_id)
        assert len(work) == 1

        # Acquire a structurally valid lease entirely in the past. This keeps
        # the jobs-table CHECK constraints satisfied while ensuring that the
        # Research repository's own wall-clock fence check sees the parent as stale.
        leased = app.jobs.acquire(
            job.job_id,
            worker_id="stale-research-parent",
            lease_seconds=1,
            now_us=1_000_000,
        )
        assert leased.lease_token is not None
        assert leased.lease_expires_at_us == 2_000_000

        with pytest.raises(ResearchFenceError, match="stale or mismatched"):
            app.research_repository.mark_work_state_fenced(
                work[0].work_item_id,
                parent_job_id=job.job_id,
                lease_token=leased.lease_token,
                state=ResearchWorkState.FAILED,
            )

        assert (
            app.research_repository.get_work_item(work[0].work_item_id).state
            is ResearchWorkState.PENDING
        )
    finally:
        app.stop()


def _signature() -> ModelSignature:
    return ModelSignature(
        model_signature_id=uuid.uuid4(),
        provider="lm_studio",
        model_identifier="primary",
        model_revision=None,
        quantization="Q4_K_M",
        generation_parameters_json='{"max_output_tokens":128,"reasoning_mode":"off"}',
        context_configuration_json='{"context_package_version":1}',
        signature_hash=b"s" * 32,
        created_at_us=1,
    )


def _section_inputs():
    ref = ContextIncludedRef(
        ref_id="E1",
        entity_type="source_analysis_artifact",
        entity_id=uuid.uuid4(),
        revision_id=None,
    )
    section = ContextSection(
        name="research-evidence",
        role="user",
        content="Grounded research evidence.",
        included_ref_ids=("E1",),
    )
    budget = ContextPackageBudget(
        effective_context_limit=1000,
        context_budget=600,
        output_reserve=200,
        safety_margin=100,
    )
    estimates = ContextTokenEstimates(
        conversation_tokens=0,
        current_user_tokens=0,
        system_tokens=20,
        context_tokens=100,
        estimated_input_tokens=120,
        estimated_total_tokens=420,
    )
    summary = ExcludedCandidateSummary(
        retrieval_candidate_count=1,
        retrieval_included_count=1,
        retrieval_excluded_count=0,
        memory_candidate_count=0,
        memory_included_count=0,
        memory_excluded_count=0,
        conversation_candidate_count=0,
        conversation_included_count=0,
        conversation_excluded_count=0,
    )
    return ref, section, budget, estimates, summary


def test_context_package_sections_reject_duplicate_reference_ids() -> None:
    ref, section, budget, estimates, summary = _section_inputs()
    duplicate = replace(ref, entity_id=uuid.uuid4())

    with pytest.raises(ContextPackageError, match="reference IDs must be unique"):
        ContextPackageService.build_from_sections(
            model_signature=_signature(),
            budget=budget,
            sections=(section,),
            included_refs=(ref, duplicate),
            excluded_candidate_summary=summary,
            token_estimates=estimates,
            snapshot_commit_seq=1,
        )


def test_context_package_sections_reject_unknown_section_reference() -> None:
    ref, section, budget, estimates, summary = _section_inputs()
    bad_section = replace(section, included_ref_ids=("UNKNOWN",))

    with pytest.raises(ContextPackageError, match="unknown included ref"):
        ContextPackageService.build_from_sections(
            model_signature=_signature(),
            budget=budget,
            sections=(bad_section,),
            included_refs=(ref,),
            excluded_candidate_summary=summary,
            token_estimates=estimates,
            snapshot_commit_seq=1,
        )


def test_context_package_sections_reject_budget_overflow() -> None:
    ref, section, budget, estimates, summary = _section_inputs()
    oversized = replace(
        estimates,
        estimated_total_tokens=budget.effective_context_limit + 1,
    )

    with pytest.raises(ContextPackageError, match="exceeds the effective context limit"):
        ContextPackageService.build_from_sections(
            model_signature=_signature(),
            budget=budget,
            sections=(section,),
            included_refs=(ref,),
            excluded_candidate_summary=summary,
            token_estimates=oversized,
            snapshot_commit_seq=1,
        )


def test_context_package_sections_reject_inconsistent_candidate_counts() -> None:
    ref, section, budget, estimates, summary = _section_inputs()
    inconsistent = replace(summary, retrieval_excluded_count=1)

    with pytest.raises(ContextPackageError, match="internally inconsistent"):
        ContextPackageService.build_from_sections(
            model_signature=_signature(),
            budget=budget,
            sections=(section,),
            included_refs=(ref,),
            excluded_candidate_summary=inconsistent,
            token_estimates=estimates,
            snapshot_commit_seq=1,
        )


@dataclass
class _MutatingEmbeddingProvider:
    callback: object
    mutated: bool = False

    def embed(self, *, model_id: str, texts):
        del model_id
        if not self.mutated:
            self.mutated = True
            callback = self.callback
            assert callable(callback)
            callback()
        return tuple((1.0, 0.5, 0.25) for _ in texts)


def test_semantic_rebuild_rejects_canonical_change_during_embedding_call(
    tmp_path: Path,
) -> None:
    database = SQLiteDatabase(tmp_path / "athena.db")
    database.start()
    try:
        app = AthenaApplication(settings=AthenaSettings(local_root=tmp_path / "app"))
        app.start()
        try:
            chat_id = app.chat.create_chat()
            message = app.chat.add_user_message(
                chat_id=chat_id,
                content="Original semantic snapshot text.",
            )
            revision = app.knowledge.promote_chat_message(
                chat_id=chat_id,
                sequence_no=message.sequence_no,
                knowledge_kind=KnowledgeKind.FACT,
            )

            provider = _MutatingEmbeddingProvider(
                callback=lambda: app.knowledge.revise(
                    knowledge_id=revision.knowledge_id,
                    body="Canonical state changed while embeddings were generated.",
                )
            )
            semantic = LocalSemanticSearchService(
                app.database,
                provider,  # type: ignore[arg-type]
                batch_size=100,
            )

            with pytest.raises(
                SemanticSearchError,
                match="Canonical state changed during embedding rebuild",
            ):
                semantic.rebuild("fake-embed")

            status = semantic.status("fake-embed")
            assert status is None or not status.current
        finally:
            app.stop()
    finally:
        database.stop()


@dataclass
class _RecordingEmbeddingProvider:
    inputs: list[tuple[str, ...]]

    def embed(self, *, model_id: str, texts):
        del model_id
        captured = tuple(texts)
        self.inputs.append(captured)
        return tuple((1.0, 0.5, 0.25) for _ in captured)


def test_semantic_rebuild_retries_if_canonical_changes_before_snapshot_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _app(tmp_path / "runtime")
    try:
        chat_id = app.chat.create_chat()
        message = app.chat.add_user_message(
            chat_id=chat_id,
            content="Original pre-snapshot race text.",
        )
        revision = app.knowledge.promote_chat_message(
            chat_id=chat_id,
            sequence_no=message.sequence_no,
            knowledge_kind=KnowledgeKind.FACT,
        )

        provider = _RecordingEmbeddingProvider(inputs=[])
        semantic = LocalSemanticSearchService(
            app.database,
            provider,  # type: ignore[arg-type]
            batch_size=100,
        )
        original_ensure = semantic._ensure_fts_current
        ensure_calls = 0

        def ensure_then_mutate_once() -> None:
            nonlocal ensure_calls
            original_ensure()
            ensure_calls += 1
            if ensure_calls == 1:
                app.knowledge.revise(
                    knowledge_id=revision.knowledge_id,
                    body="Updated pre-snapshot race text.",
                )

        monkeypatch.setattr(
            semantic,
            "_ensure_fts_current",
            ensure_then_mutate_once,
        )

        status = semantic.rebuild("fake-embed")

        assert ensure_calls >= 2
        assert status.current
        assert status.indexed_commit_seq == current_search_projection_commit_seq(
            app.database.connection
        )
        assert len(provider.inputs) == 1
        assert any(
            "Updated pre-snapshot race text." in text
            for text in provider.inputs[0]
        )
    finally:
        app.stop()


class _FakeResponse:
    def __init__(self, payload: object) -> None:
        self._bytes = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return self._bytes


def _controlled_payload(instance_id: str, *, stats: object | None = None) -> dict[str, object]:
    return {
        "model_instance_id": instance_id,
        "output": [{"type": "message", "content": '{"answer":42}'}],
        "stats": (
            {
                "input_tokens": 20,
                "total_output_tokens": 5,
                "reasoning_output_tokens": 0,
            }
            if stats is None
            else stats
        ),
    }


def _controlled_kwargs() -> dict[str, object]:
    return {
        "model_id": "example/model-q4",
        "messages": (
            ModelChatMessage(role="system", content="Return structured output."),
            ModelChatMessage(role="user", content="Give the answer."),
        ),
        "schema_id": "answer_v1",
        "json_schema": {"type": "object"},
        "reasoning_mode": "off",
        "context_length": 5300,
        "max_output_tokens": 2000,
        "temperature": 0.0,
        "top_p": 0.95,
        "top_k": 40,
        "min_p": 0.05,
        "repeat_penalty": 1.1,
    }


def test_lm_studio_controlled_runtime_rejects_instance_switch() -> None:
    provider = LMStudioProvider("http://127.0.0.1:1234")
    responses = iter(
        (
            _FakeResponse(_controlled_payload("example/model-q4:runtime-1")),
            _FakeResponse(_controlled_payload("example/model-q4:runtime-2")),
        )
    )

    with patch(
        "athena.model.adapters.lm_studio.urlopen",
        side_effect=lambda request, timeout: next(responses),
    ):
        assert provider.generate_controlled_structured(**_controlled_kwargs()) == {
            "answer": 42
        }
        with pytest.raises(ProviderProtocolError, match="switched model instances"):
            provider.generate_controlled_structured(**_controlled_kwargs())


def test_lm_studio_controlled_runtime_rejects_missing_stats() -> None:
    provider = LMStudioProvider("http://127.0.0.1:1234")
    payload = _controlled_payload("example/model-q4:runtime-1")
    payload.pop("stats")

    with patch(
        "athena.model.adapters.lm_studio.urlopen",
        return_value=_FakeResponse(payload),
    ):
        with pytest.raises(ProviderProtocolError, match="missing stats"):
            provider.generate_controlled_structured(**_controlled_kwargs())


@pytest.mark.parametrize(
    "payload",
    (
        {
            "data": [
                {"index": 0, "embedding": [1.0, 0.0]},
                {"index": 0, "embedding": [0.0, 1.0]},
            ]
        },
        {"data": [{"embedding": [1.0, 0.0]}]},
        {"data": [{"index": 0, "embedding": [1.0, float("nan")]}]},
    ),
)
def test_embedding_provider_malformed_payloads_fail_closed(
    payload: dict[str, object],
) -> None:
    provider = LMStudioEmbeddingProvider(
        LMStudioProvider(base_url="http://127.0.0.1:1234")
    )
    texts = ("first", "second") if len(payload["data"]) == 2 else ("first",)  # type: ignore[arg-type]

    with patch(
        "athena.model.adapters.lm_studio_embeddings.urlopen",
        return_value=_FakeResponse(payload),
    ):
        with pytest.raises(ProviderProtocolError):
            provider.embed(model_id="embed", texts=texts)
