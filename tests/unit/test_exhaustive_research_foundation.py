from __future__ import annotations

from pathlib import Path

import pytest

from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.research.models import (
    ResearchCandidateEligibility,
    ResearchScopeState,
    ResearchWorkState,
)
from athena.research.repository import ResearchScopeUnsupportedError
from athena.source.models import SourceType


def _app(root: Path) -> AthenaApplication:
    app = AthenaApplication(settings=AthenaSettings(local_root=root))
    app.start()
    return app


def _capture(app: AthenaApplication, path: Path, text: str):
    path.write_text(text, encoding="utf-8", newline="")
    return app.sources.capture_file(path).source


def test_research_scope_pins_snapshot_and_excludes_later_sources(tmp_path: Path) -> None:
    app = _app(tmp_path / "runtime")
    before = _capture(app, tmp_path / "before.txt", "before snapshot unique")
    job = app.research.enqueue_local(query="Find all local evidence.")
    scope = app.research.initialize(job.job_id)
    after = _capture(app, tmp_path / "after.txt", "after snapshot unique")

    candidate_set = app.research.freeze_candidates(job.job_id)
    candidates = app.research_repository.list_candidates(scope.scope_id)

    assert candidate_set.snapshot_commit_seq == scope.snapshot_commit_seq
    assert [item.source_id for item in candidates] == [before.source_id]
    assert after.source_id not in {item.source_id for item in candidates}
    assert app.research_repository.get_scope(scope.scope_id).state is ResearchScopeState.FROZEN
    app.stop()


def test_byte_identical_sources_remain_visible_but_count_once_for_coverage(
    tmp_path: Path,
) -> None:
    app = _app(tmp_path / "runtime")
    path = tmp_path / "duplicate.txt"
    first = _capture(app, path, "identical source bytes")
    second = app.sources.capture_file(path).source
    assert first.source_id != second.source_id

    job = app.research.enqueue_local(query="Deduplicate coverage.")
    candidate_set = app.research.freeze_candidates(job.job_id)
    scope = app.research.initialize(job.job_id)
    candidates = app.research_repository.list_candidates(scope.scope_id)
    work = app.research.work_items(job.job_id)

    assert candidate_set.candidate_total == 2
    assert candidate_set.eligible_count == 1
    assert candidate_set.excluded_count == 1
    assert len(candidates) == 2
    assert len(work) == 1
    assert candidates[0].eligibility is ResearchCandidateEligibility.ELIGIBLE
    assert candidates[1].eligibility is ResearchCandidateEligibility.EXCLUDED_DUPLICATE
    assert candidates[1].duplicate_of_candidate_id == candidates[0].candidate_id

    coverage = app.research.coverage(job.job_id)
    assert coverage.candidate_total == 2
    assert coverage.eligible_count == 1
    assert coverage.excluded_count == 1
    assert coverage.coverage_ratio == 0.0
    app.stop()


def test_candidate_freeze_is_idempotent_and_never_absorbs_new_data(tmp_path: Path) -> None:
    app = _app(tmp_path / "runtime")
    first = _capture(app, tmp_path / "first.txt", "first unique source")
    job = app.research.enqueue_local(query="Freeze once.")
    initial = app.research.freeze_candidates(job.job_id)
    scope = app.research.initialize(job.job_id)
    initial_work = app.research.work_items(job.job_id)

    _capture(app, tmp_path / "later.txt", "later unique source")
    repeated = app.research.freeze_candidates(job.job_id)
    repeated_candidates = app.research_repository.list_candidates(scope.scope_id)
    repeated_work = app.research.work_items(job.job_id)

    assert repeated.candidate_set_id == initial.candidate_set_id
    assert [item.source_id for item in repeated_candidates] == [first.source_id]
    assert [item.work_item_id for item in repeated_work] == [
        item.work_item_id for item in initial_work
    ]
    assert [item.idempotency_key for item in repeated_work] == [
        item.idempotency_key for item in initial_work
    ]
    app.stop()


def test_failed_work_unit_prevents_false_full_coverage(tmp_path: Path) -> None:
    app = _app(tmp_path / "runtime")
    _capture(app, tmp_path / "a.txt", "unique alpha")
    _capture(app, tmp_path / "b.txt", "unique beta")
    job = app.research.enqueue_local(query="Coverage must be honest.")
    app.research.freeze_candidates(job.job_id)
    work = app.research.work_items(job.job_id)
    assert len(work) == 2

    app.research.mark_work_state(
        work[0].work_item_id,
        state=ResearchWorkState.SUCCESSFUL,
    )
    app.research.mark_work_state(
        work[1].work_item_id,
        state=ResearchWorkState.FAILED,
    )
    coverage = app.research.coverage(job.job_id)

    assert coverage.candidate_total == 2
    assert coverage.eligible_count == 2
    assert coverage.processed_count == 2
    assert coverage.successful_count == 1
    assert coverage.failed_count == 1
    assert coverage.coverage_ratio == 0.5
    assert coverage.coverage_ratio < 1.0
    app.stop()


def test_irrelevant_is_processed_and_covered_but_unavailable_is_not(
    tmp_path: Path,
) -> None:
    app = _app(tmp_path / "runtime")
    _capture(app, tmp_path / "a.txt", "unique alpha")
    _capture(app, tmp_path / "b.txt", "unique beta")
    _capture(app, tmp_path / "c.txt", "unique gamma")
    job = app.research.enqueue_local(query="Classify evidence.")
    app.research.freeze_candidates(job.job_id)
    work = app.research.work_items(job.job_id)
    assert len(work) == 3

    app.research.mark_work_state(
        work[0].work_item_id,
        state=ResearchWorkState.SUCCESSFUL,
    )
    app.research.mark_work_state(
        work[1].work_item_id,
        state=ResearchWorkState.IRRELEVANT,
    )
    app.research.mark_work_state(
        work[2].work_item_id,
        state=ResearchWorkState.UNAVAILABLE,
    )
    coverage = app.research.coverage(job.job_id)

    assert coverage.processed_count == 3
    assert coverage.successful_count == 1
    assert coverage.irrelevant_count == 1
    assert coverage.unavailable_count == 1
    assert coverage.coverage_ratio == pytest.approx(2 / 3)
    app.stop()


def test_foundation_discovery_fails_closed_on_unimplemented_scope_filters(
    tmp_path: Path,
) -> None:
    app = _app(tmp_path / "runtime")
    _capture(app, tmp_path / "source.txt", "domain scoped evidence")
    job = app.research.enqueue_local(
        query="Do not silently broaden scope.",
        domains=("example-domain",),
    )
    scope = app.research.initialize(job.job_id)

    with pytest.raises(
        ResearchScopeUnsupportedError,
        match="cannot yet apply domain/project filters",
    ):
        app.research.freeze_candidates(job.job_id)

    assert app.research_repository.list_candidates(scope.scope_id) == ()
    assert app.research_repository.list_work_items(scope.scope_id) == ()
    assert app.research_repository.get_scope(scope.scope_id).state is ResearchScopeState.DISCOVERING
    app.stop()


def test_explicit_source_and_type_filters_are_honored(tmp_path: Path) -> None:
    app = _app(tmp_path / "runtime")
    selected = _capture(app, tmp_path / "selected.txt", "selected evidence")
    _capture(app, tmp_path / "other.txt", "other evidence")
    job = app.research.enqueue_local(
        query="Only explicit file source.",
        source_types=(SourceType.FILE,),
        explicit_source_ids=(selected.source_id,),
    )
    app.research.freeze_candidates(job.job_id)
    scope = app.research.initialize(job.job_id)
    candidates = app.research_repository.list_candidates(scope.scope_id)

    assert [item.source_id for item in candidates] == [selected.source_id]
    assert len(app.research.work_items(job.job_id)) == 1
    app.stop()


def test_research_foundation_survives_restart_with_same_frozen_identity(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runtime"
    first = _app(root)
    _capture(first, tmp_path / "source.txt", "restart durable evidence")
    job = first.research.enqueue_local(query="Resume durable Research state.")
    candidate_set = first.research.freeze_candidates(job.job_id)
    scope = first.research.initialize(job.job_id)
    work = first.research.work_items(job.job_id)
    assert len(work) == 1
    first.stop()

    second = _app(root)
    loaded_scope = second.research.initialize(job.job_id)
    loaded_set = second.research.freeze_candidates(job.job_id)
    loaded_work = second.research.work_items(job.job_id)

    assert loaded_scope.scope_id == scope.scope_id
    assert loaded_scope.snapshot_commit_seq == scope.snapshot_commit_seq
    assert loaded_set.candidate_set_id == candidate_set.candidate_set_id
    assert [item.work_item_id for item in loaded_work] == [item.work_item_id for item in work]
    assert [item.idempotency_key for item in loaded_work] == [
        item.idempotency_key for item in work
    ]
    second.stop()
