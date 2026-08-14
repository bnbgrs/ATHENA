"""Application service for snapshot-frozen local Exhaustive Research."""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from athena.jobs.models import JobPriority, JobRecord, JobState
from athena.jobs.repository import JobTransitionError
from athena.jobs.service import DurableJobService
from athena.research.models import (
    ResearchCandidateSetRecord,
    ResearchCoverage,
    ResearchMode,
    ResearchScopeRecord,
    ResearchWorkItemRecord,
    ResearchWorkState,
)
from athena.research.repository import ResearchRepository
from athena.source.analysis_service import (
    DEFAULT_MAX_HIERARCHY_DEPTH,
    AnalysisPinnedConfiguration,
    SourceAnalysisService,
)
from athena.source.models import SourceType

LEGACY_PIPELINE_VERSION = "exhaustive-research-foundation-v1"
PIPELINE_VERSION = "exhaustive-research-orchestration-v2"
COVERAGE_FORMULA_ID = "eligible-success-or-irrelevant-v1"
CANDIDATE_DEDUP_ID = "source-content-sha256-v1"


class ResearchConfigurationError(ValueError):
    """Raised when a ResearchScope cannot be represented deterministically."""


class ResearchService:
    """Persist ResearchScope, freeze candidates, and pin one semantic model contract."""

    def __init__(
        self,
        *,
        repository: ResearchRepository,
        jobs: DurableJobService,
        source_analysis: SourceAnalysisService,
    ) -> None:
        self.repository = repository
        self.jobs = jobs
        self.source_analysis = source_analysis

    def enqueue_local(
        self,
        *,
        query: str,
        priority: JobPriority = JobPriority.NORMAL,
        domains: Sequence[str] = (),
        project_ids: Sequence[uuid.UUID] = (),
        source_types: Sequence[SourceType] = (),
        explicit_source_ids: Sequence[uuid.UUID] = (),
        time_start_us: int | None = None,
        time_end_us: int | None = None,
        coverage_target: float = 1.0,
        requested_model_id: str | None = None,
        context_limit: int | None = None,
        output_reserve: int | None = None,
        safety_margin: int | None = None,
        max_hierarchy_depth: int = DEFAULT_MAX_HIERARCHY_DEPTH,
    ) -> JobRecord:
        normalized_query = query.strip()
        if not normalized_query:
            raise ResearchConfigurationError("Research query must not be empty.")
        if not 0.0 < coverage_target <= 1.0:
            raise ResearchConfigurationError(
                "Research coverage_target must be in the interval (0, 1]."
            )
        if time_start_us is not None and time_start_us < 0:
            raise ResearchConfigurationError("time_start_us must not be negative.")
        if time_end_us is not None and time_end_us < 0:
            raise ResearchConfigurationError("time_end_us must not be negative.")
        if (
            time_start_us is not None
            and time_end_us is not None
            and time_end_us < time_start_us
        ):
            raise ResearchConfigurationError(
                "Research time_end_us must be >= time_start_us."
            )
        if context_limit is not None and context_limit < 1:
            raise ResearchConfigurationError("context_limit must be positive.")
        if output_reserve is not None and output_reserve < 1:
            raise ResearchConfigurationError("output_reserve must be positive.")
        if safety_margin is not None and safety_margin < 0:
            raise ResearchConfigurationError("safety_margin must not be negative.")
        if max_hierarchy_depth < 1:
            raise ResearchConfigurationError("max_hierarchy_depth must be positive.")

        normalized_domains = _stable_strings(domains, field="domains")
        normalized_projects = _stable_uuids(project_ids)
        normalized_source_types = tuple(sorted({item.value for item in source_types}))
        normalized_sources = _stable_uuids(explicit_source_ids)
        normalized_model = (
            requested_model_id.strip()
            if requested_model_id is not None and requested_model_id.strip()
            else None
        )

        # Actor setup can itself create canonical state; do it before the snapshot pin.
        self.jobs.chat.ensure_local_user()
        snapshot_commit_seq = self.repository.current_commit_seq()

        return self.jobs.create(
            job_type="research.exhaustive",
            priority=priority,
            requested_scope={
                "mode": ResearchMode.LOCAL_EXHAUSTIVE.value,
                "query": normalized_query,
                "domains": list(normalized_domains),
                "project_ids": [str(item) for item in normalized_projects],
                "source_types": list(normalized_source_types),
                "explicit_source_ids": [str(item) for item in normalized_sources],
                "time_start_us": time_start_us,
                "time_end_us": time_end_us,
                "internet_scope": None,
                "coverage_target": coverage_target,
            },
            pinned_configuration={
                "pipeline_version": PIPELINE_VERSION,
                "snapshot_commit_seq": snapshot_commit_seq,
                "coverage_formula_id": COVERAGE_FORMULA_ID,
                "candidate_dedup_id": CANDIDATE_DEDUP_ID,
                "requested_model_id": normalized_model,
                "context_limit": context_limit,
                "output_reserve": output_reserve,
                "safety_margin": safety_margin,
                "max_hierarchy_depth": max_hierarchy_depth,
            },
        )

    def initialize(self, job_id: uuid.UUID) -> ResearchScopeRecord:
        job = self.jobs.get(job_id)
        if job.job_type != "research.exhaustive":
            raise ResearchConfigurationError(
                f"Job {job_id} is {job.job_type!r}, not 'research.exhaustive'."
            )
        requested = _object(job.requested_scope_json, "requested_scope")
        pinned = _object(job.pinned_configuration_json, "pinned_configuration")

        expected_requested = {
            "mode",
            "query",
            "domains",
            "project_ids",
            "source_types",
            "explicit_source_ids",
            "time_start_us",
            "time_end_us",
            "internet_scope",
            "coverage_target",
        }
        legacy_pinned = {
            "pipeline_version",
            "snapshot_commit_seq",
            "coverage_formula_id",
            "candidate_dedup_id",
        }
        current_pinned = {
            *legacy_pinned,
            "requested_model_id",
            "context_limit",
            "output_reserve",
            "safety_margin",
            "max_hierarchy_depth",
        }
        if set(requested) != expected_requested:
            raise ResearchConfigurationError(
                "research.exhaustive requested_scope has unexpected fields."
            )
        pipeline = pinned.get("pipeline_version")
        if pipeline == LEGACY_PIPELINE_VERSION:
            if set(pinned) != legacy_pinned:
                raise ResearchConfigurationError(
                    "Legacy research.exhaustive pinned_configuration has unexpected fields."
                )
        elif pipeline == PIPELINE_VERSION:
            if set(pinned) != current_pinned:
                raise ResearchConfigurationError(
                    "research.exhaustive pinned_configuration has unexpected fields."
                )
        else:
            raise ResearchConfigurationError("Research pipeline version drifted.")
        if pinned.get("coverage_formula_id") != COVERAGE_FORMULA_ID:
            raise ResearchConfigurationError("Research coverage formula drifted.")
        if pinned.get("candidate_dedup_id") != CANDIDATE_DEDUP_ID:
            raise ResearchConfigurationError("Research candidate dedup policy drifted.")

        mode = ResearchMode(_string(requested, "mode"))
        query_text = _string(requested, "query")
        coverage_target = _float(requested, "coverage_target")
        snapshot_commit_seq = _int(pinned, "snapshot_commit_seq", minimum=0)
        current_commit_seq = self.repository.current_commit_seq()
        if snapshot_commit_seq > current_commit_seq:
            raise ResearchConfigurationError(
                "Research snapshot_commit_seq is ahead of current canonical state."
            )

        return self.repository.create_scope(
            job_id=job_id,
            mode=mode,
            query_text=query_text,
            domains_json=_canonical_json_array(_string_array(requested, "domains")),
            project_ids_json=_canonical_json_array(
                _uuid_string_array(requested, "project_ids")
            ),
            source_types_json=_canonical_json_array(
                _source_type_array(requested, "source_types")
            ),
            explicit_source_ids_json=_canonical_json_array(
                _uuid_string_array(requested, "explicit_source_ids")
            ),
            time_start_us=_optional_int(requested, "time_start_us", minimum=0),
            time_end_us=_optional_int(requested, "time_end_us", minimum=0),
            internet_scope_json=_optional_json_object(requested, "internet_scope"),
            coverage_target=coverage_target,
            snapshot_commit_seq=snapshot_commit_seq,
        )

    def freeze_candidates(self, job_id: uuid.UUID) -> ResearchCandidateSetRecord:
        scope = self.initialize(job_id)
        return self.repository.freeze_local_candidates(scope.scope_id)

    def ensure_model_contract(
        self,
        job_id: uuid.UUID,
        *,
        parent_job_id: uuid.UUID,
        lease_token: bytes,
    ) -> AnalysisPinnedConfiguration:
        scope = self.initialize(job_id)
        if scope.model_id is not None:
            config = _analysis_config_from_scope(scope)
            self.source_analysis.assert_pinned_configuration_unchanged(config)
            verified = self.repository.pin_model_contract_fenced(
                scope.scope_id,
                parent_job_id=parent_job_id,
                lease_token=lease_token,
                model_id=config.model_id,
                model_signature_id=config.model_signature_id,
                model_signature_sha256=config.model_signature_hash,
                effective_context_limit=config.effective_context_limit,
                output_reserve=config.output_reserve,
                safety_margin=config.safety_margin,
                token_estimator=config.token_estimator,
                max_hierarchy_depth=config.max_hierarchy_depth,
            )
            return _analysis_config_from_scope(verified)

        job = self.jobs.get(job_id)
        pinned = _object(job.pinned_configuration_json, "pinned_configuration")
        if pinned.get("pipeline_version") == LEGACY_PIPELINE_VERSION:
            requested_model_id = None
            context_limit = None
            output_reserve = None
            safety_margin = None
            max_hierarchy_depth = DEFAULT_MAX_HIERARCHY_DEPTH
        else:
            requested_model_id = _optional_string(pinned, "requested_model_id")
            context_limit = _optional_int(pinned, "context_limit", minimum=1)
            output_reserve = _optional_int(pinned, "output_reserve", minimum=1)
            safety_margin = _optional_int(pinned, "safety_margin", minimum=0)
            max_hierarchy_depth = _int(
                pinned, "max_hierarchy_depth", minimum=1
            )

        config = self.source_analysis.pin_configuration(
            requested_model_id=requested_model_id,
            context_limit=context_limit,
            output_reserve=output_reserve,
            safety_margin=safety_margin,
            max_hierarchy_depth=max_hierarchy_depth,
        )
        pinned_scope = self.repository.pin_model_contract_fenced(
            scope.scope_id,
            parent_job_id=parent_job_id,
            lease_token=lease_token,
            model_id=config.model_id,
            model_signature_id=config.model_signature_id,
            model_signature_sha256=config.model_signature_hash,
            effective_context_limit=config.effective_context_limit,
            output_reserve=config.output_reserve,
            safety_margin=config.safety_margin,
            token_estimator=config.token_estimator,
            max_hierarchy_depth=config.max_hierarchy_depth,
        )
        return _analysis_config_from_scope(pinned_scope)

    def coverage(self, job_id: uuid.UUID) -> ResearchCoverage:
        scope = self.initialize(job_id)
        return self.repository.coverage(scope.scope_id)

    def work_items(self, job_id: uuid.UUID) -> tuple[ResearchWorkItemRecord, ...]:
        scope = self.initialize(job_id)
        return self.repository.list_work_items(scope.scope_id)

    def mark_work_state(
        self,
        work_item_id: uuid.UUID,
        *,
        state: ResearchWorkState,
    ) -> ResearchWorkItemRecord:
        return self.repository.mark_work_state(work_item_id, state=state)

    def cancel(self, job_id: uuid.UUID) -> JobRecord:
        job = self.jobs.get(job_id)
        if job.job_type != "research.exhaustive":
            raise ResearchConfigurationError(
                f"Job {job_id} is not a research.exhaustive job."
            )
        scope = self.repository.get_scope_for_job(job_id)
        if scope is not None and job.state in {
            JobState.QUEUED,
            JobState.WAITING,
            JobState.PAUSED,
        }:
            self.repository.mark_scope_partial_unleased(scope.scope_id)
            self._cancel_linked_children(scope.scope_id)
        return self.jobs.request_cancel(job_id)

    def _cancel_linked_children(self, scope_id: uuid.UUID) -> None:
        for work in self.repository.list_work_items(scope_id):
            for child_id in (
                work.source_processing_job_id,
                work.source_analysis_job_id,
            ):
                if child_id is None:
                    continue
                child = self.jobs.get(child_id)
                if child.state.terminal:
                    continue
                try:
                    self.jobs.request_cancel(child_id)
                except JobTransitionError:
                    # Parent cancellation must remain monotonic even if a child
                    # raced to terminal state between get() and request_cancel().
                    current = self.jobs.get(child_id)
                    if not current.state.terminal:
                        raise


def _analysis_config_from_scope(
    scope: ResearchScopeRecord,
) -> AnalysisPinnedConfiguration:
    fields = (
        scope.model_id,
        scope.model_signature_id,
        scope.model_signature_sha256,
        scope.effective_context_limit,
        scope.output_reserve,
        scope.safety_margin,
        scope.token_estimator,
        scope.max_hierarchy_depth,
    )
    if any(item is None for item in fields):
        raise ResearchConfigurationError(
            "ResearchScope has an incomplete pinned model contract."
        )
    assert scope.model_id is not None
    assert scope.model_signature_id is not None
    assert scope.model_signature_sha256 is not None
    assert scope.effective_context_limit is not None
    assert scope.output_reserve is not None
    assert scope.safety_margin is not None
    assert scope.token_estimator is not None
    assert scope.max_hierarchy_depth is not None
    return AnalysisPinnedConfiguration(
        model_id=scope.model_id,
        model_signature_id=scope.model_signature_id,
        model_signature_hash=scope.model_signature_sha256,
        effective_context_limit=scope.effective_context_limit,
        output_reserve=scope.output_reserve,
        safety_margin=scope.safety_margin,
        token_estimator=scope.token_estimator,
        max_hierarchy_depth=scope.max_hierarchy_depth,
    )


def _stable_strings(values: Sequence[str], *, field: str) -> tuple[str, ...]:
    normalized = []
    for value in values:
        item = value.strip()
        if not item:
            raise ResearchConfigurationError(f"{field} must not contain blank values.")
        normalized.append(item)
    return tuple(sorted(set(normalized)))


def _stable_uuids(values: Sequence[uuid.UUID]) -> tuple[uuid.UUID, ...]:
    return tuple(sorted(set(values), key=lambda item: item.bytes))


def _object(raw: str | None, field: str) -> Mapping[str, Any]:
    if raw is None:
        raise ResearchConfigurationError(f"Research {field} is missing.")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ResearchConfigurationError(f"Research {field} is invalid JSON.") from exc
    if not isinstance(value, Mapping):
        raise ResearchConfigurationError(f"Research {field} must be a JSON object.")
    return value


def _string(value: Mapping[str, Any], field: str) -> str:
    item = value.get(field)
    if not isinstance(item, str) or not item.strip():
        raise ResearchConfigurationError(f"Research field {field!r} must be text.")
    return item.strip()


def _optional_string(value: Mapping[str, Any], field: str) -> str | None:
    item = value.get(field)
    if item is None:
        return None
    if not isinstance(item, str) or not item.strip():
        raise ResearchConfigurationError(
            f"Research field {field!r} must be null or non-empty text."
        )
    return item.strip()


def _int(
    value: Mapping[str, Any],
    field: str,
    *,
    minimum: int,
) -> int:
    item = value.get(field)
    if not isinstance(item, int) or isinstance(item, bool) or item < minimum:
        raise ResearchConfigurationError(
            f"Research field {field!r} must be an integer >= {minimum}."
        )
    return item


def _optional_int(
    value: Mapping[str, Any],
    field: str,
    *,
    minimum: int,
) -> int | None:
    item = value.get(field)
    if item is None:
        return None
    if not isinstance(item, int) or isinstance(item, bool) or item < minimum:
        raise ResearchConfigurationError(
            f"Research field {field!r} must be null or integer >= {minimum}."
        )
    return item


def _float(value: Mapping[str, Any], field: str) -> float:
    item = value.get(field)
    if not isinstance(item, (int, float)) or isinstance(item, bool):
        raise ResearchConfigurationError(
            f"Research field {field!r} must be numeric."
        )
    result = float(item)
    if not 0.0 < result <= 1.0:
        raise ResearchConfigurationError(
            f"Research field {field!r} must be in (0, 1]."
        )
    return result


def _string_array(
    value: Mapping[str, Any],
    field: str,
) -> tuple[str, ...]:
    item = value.get(field)
    if not isinstance(item, list) or any(not isinstance(part, str) for part in item):
        raise ResearchConfigurationError(
            f"Research field {field!r} must be a string array."
        )
    return tuple(item)


def _uuid_string_array(
    value: Mapping[str, Any],
    field: str,
) -> tuple[str, ...]:
    items = _string_array(value, field)
    try:
        parsed = tuple(uuid.UUID(item) for item in items)
    except ValueError as exc:
        raise ResearchConfigurationError(
            f"Research field {field!r} contains an invalid UUID."
        ) from exc
    return tuple(str(item) for item in sorted(set(parsed), key=lambda item: item.bytes))


def _source_type_array(
    value: Mapping[str, Any],
    field: str,
) -> tuple[str, ...]:
    items = _string_array(value, field)
    try:
        source_types = tuple(SourceType(item) for item in items)
    except ValueError as exc:
        raise ResearchConfigurationError(
            f"Research field {field!r} contains an unknown SourceType."
        ) from exc
    return tuple(sorted({item.value for item in source_types}))


def _optional_json_object(
    value: Mapping[str, Any],
    field: str,
) -> str | None:
    item = value.get(field)
    if item is None:
        return None
    if not isinstance(item, Mapping):
        raise ResearchConfigurationError(
            f"Research field {field!r} must be null or an object."
        )
    return json.dumps(
        dict(item),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _canonical_json_array(values: Sequence[str]) -> str:
    return json.dumps(
        list(values),
        ensure_ascii=False,
        sort_keys=False,
        separators=(",", ":"),
        allow_nan=False,
    )
