"""Transactional persistence for Exhaustive Research scope and frozen candidates."""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from athena.common.ids import new_uuid7, uuid_from_blob, uuid_to_blob
from athena.common.time import utc_now_us
from athena.research.errors import (
    ResearchFenceError as ResearchFenceError,
)
from athena.research.errors import (
    ResearchNotFoundError as ResearchNotFoundError,
)
from athena.research.errors import (
    ResearchScopeUnsupportedError as ResearchScopeUnsupportedError,
)
from athena.research.errors import (
    ResearchSnapshotError as ResearchSnapshotError,
)
from athena.research.errors import (
    ResearchStateError as ResearchStateError,
)
from athena.research.idempotency import (
    _synthesis_work_idempotency_key as _synthesis_work_idempotency_key,
)
from athena.research.idempotency import (
    _work_idempotency_key as _work_idempotency_key,
)
from athena.research.models import (
    ResearchCandidateEligibility,
    ResearchCandidateRecord,
    ResearchCandidateSetRecord,
    ResearchCandidateSetState,
    ResearchCoverage,
    ResearchMode,
    ResearchResultRecord,
    ResearchScopeRecord,
    ResearchScopeState,
    ResearchSynthesisArtifactRecord,
    ResearchSynthesisEvidenceRecord,
    ResearchSynthesisInputKind,
    ResearchSynthesisStage,
    ResearchSynthesisWorkInputRecord,
    ResearchSynthesisWorkItemRecord,
    ResearchSynthesisWorkState,
    ResearchWorkItemRecord,
    ResearchWorkState,
)
from athena.research.row_mapping import (
    _candidate_from_row,
    _candidate_set_from_row,
    _research_result_from_row,
    _scope_from_row,
    _synthesis_artifact_from_row,
    _synthesis_evidence_from_row,
    _synthesis_work_input_from_row,
    _synthesis_work_item_from_row,
    _work_item_from_row,
)
from athena.research.validation import (
    _canonical_json_object as _canonical_json_object,
)
from athena.research.validation import (
    _canonical_json_value as _canonical_json_value,
)
from athena.research.validation import (
    _json_string_array as _json_string_array,
)
from athena.research.validation import (
    _required_text as _required_text,
)
from athena.research.validation import (
    _validated_synthesis_evidence as _validated_synthesis_evidence,
)
from athena.research.validation import (
    _validated_synthesis_source_evidence as _validated_synthesis_source_evidence,
)
from athena.storage.database import SQLiteDatabase

PRECISE_SYNTHESIS_PROVENANCE_POLICY_ID = "terminal-source-output-v1"












class ResearchRepository:
    """Own snapshot-frozen local CandidateSets and honest persisted coverage counters."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def current_commit_seq(self) -> int:
        row = self.database.connection.execute(
            "SELECT COALESCE(MAX(commit_seq), 0) AS commit_seq FROM commit_records"
        ).fetchone()
        return 0 if row is None else int(row["commit_seq"])

    def create_scope(
        self,
        *,
        job_id: uuid.UUID,
        mode: ResearchMode,
        query_text: str,
        domains_json: str,
        project_ids_json: str,
        source_types_json: str,
        explicit_source_ids_json: str,
        time_start_us: int | None,
        time_end_us: int | None,
        internet_scope_json: str | None,
        coverage_target: float,
        snapshot_commit_seq: int,
    ) -> ResearchScopeRecord:
        now_us = utc_now_us()
        scope_id = new_uuid7()
        with self.database.write_transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM research_scopes WHERE job_id = ?",
                (uuid_to_blob(job_id),),
            ).fetchone()
            if existing is not None:
                return _scope_from_row(existing)

            job = connection.execute(
                "SELECT job_type FROM jobs WHERE job_id = ?",
                (uuid_to_blob(job_id),),
            ).fetchone()
            if job is None:
                raise ResearchNotFoundError(f"Research job {job_id} does not exist.")
            if str(job["job_type"]) != "research.exhaustive":
                raise ResearchStateError(
                    f"Job {job_id} is not a research.exhaustive job."
                )
            connection.execute(
                """
                INSERT INTO research_scopes (
                    scope_id, job_id, mode, query_text,
                    domains_json, project_ids_json, source_types_json,
                    explicit_source_ids_json, time_start_us, time_end_us,
                    internet_scope_json, coverage_target, snapshot_commit_seq,
                    state, candidate_total, processed_count, successful_count,
                    irrelevant_count, failed_count, unavailable_count,
                    excluded_count, coverage_ratio, created_at_us, updated_at_us
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    'discovering', 0, 0, 0, 0, 0, 0, 0, 0.0, ?, ?
                )
                """,
                (
                    uuid_to_blob(scope_id),
                    uuid_to_blob(job_id),
                    mode.value,
                    query_text,
                    domains_json,
                    project_ids_json,
                    source_types_json,
                    explicit_source_ids_json,
                    time_start_us,
                    time_end_us,
                    internet_scope_json,
                    coverage_target,
                    snapshot_commit_seq,
                    now_us,
                    now_us,
                ),
            )
        return self.get_scope(scope_id)

    def get_scope(self, scope_id: uuid.UUID) -> ResearchScopeRecord:
        row = self.database.connection.execute(
            "SELECT * FROM research_scopes WHERE scope_id = ?",
            (uuid_to_blob(scope_id),),
        ).fetchone()
        if row is None:
            raise ResearchNotFoundError(str(scope_id))
        return _scope_from_row(row)

    def get_scope_for_job(self, job_id: uuid.UUID) -> ResearchScopeRecord | None:
        row = self.database.connection.execute(
            "SELECT * FROM research_scopes WHERE job_id = ?",
            (uuid_to_blob(job_id),),
        ).fetchone()
        return None if row is None else _scope_from_row(row)

    def get_candidate_set(self, scope_id: uuid.UUID) -> ResearchCandidateSetRecord:
        row = self.database.connection.execute(
            "SELECT * FROM research_candidate_sets WHERE scope_id = ?",
            (uuid_to_blob(scope_id),),
        ).fetchone()
        if row is None:
            raise ResearchNotFoundError(
                f"Research scope {scope_id} has no CandidateSet."
            )
        return _candidate_set_from_row(row)

    def freeze_local_candidates(
        self,
        scope_id: uuid.UUID,
    ) -> ResearchCandidateSetRecord:
        now_us = utc_now_us()
        with self.database.write_transaction() as connection:
            scope_row = connection.execute(
                "SELECT * FROM research_scopes WHERE scope_id = ?",
                (uuid_to_blob(scope_id),),
            ).fetchone()
            if scope_row is None:
                raise ResearchNotFoundError(str(scope_id))
            scope = _scope_from_row(scope_row)

            existing = connection.execute(
                "SELECT * FROM research_candidate_sets WHERE scope_id = ?",
                (uuid_to_blob(scope_id),),
            ).fetchone()
            if existing is not None:
                candidate_set = _candidate_set_from_row(existing)
                if candidate_set.state is not ResearchCandidateSetState.FROZEN:
                    raise ResearchStateError(
                        "Existing CandidateSet is not in a recoverable frozen state."
                    )
                return candidate_set

            if scope.state is not ResearchScopeState.DISCOVERING:
                raise ResearchStateError(
                    f"Research scope cannot freeze candidates from {scope.state.value!r}."
                )

            domains = _json_string_array(scope.domains_json, "domains_json")
            projects = _json_string_array(scope.project_ids_json, "project_ids_json")
            if domains or projects:
                raise ResearchScopeUnsupportedError(
                    "Foundation local discovery cannot yet apply domain/project filters; "
                    "refusing to silently broaden the ResearchScope."
                )
            if scope.internet_scope_json is not None:
                raise ResearchScopeUnsupportedError(
                    "Foundation local discovery does not support internet_scope."
                )
            if scope.mode is not ResearchMode.LOCAL_EXHAUSTIVE:
                raise ResearchScopeUnsupportedError(
                    f"Foundation discovery does not support Research mode {scope.mode.value!r}."
                )

            source_types = _json_string_array(
                scope.source_types_json,
                "source_types_json",
            )
            explicit_source_ids = tuple(
                uuid.UUID(value)
                for value in _json_string_array(
                    scope.explicit_source_ids_json,
                    "explicit_source_ids_json",
                )
            )
            rows = self._select_sources_as_of(
                connection,
                snapshot_commit_seq=scope.snapshot_commit_seq,
                source_types=source_types,
                explicit_source_ids=explicit_source_ids,
                time_start_us=scope.time_start_us,
                time_end_us=scope.time_end_us,
            )

            if explicit_source_ids:
                found = {uuid_from_blob(bytes(row["source_id"])) for row in rows}
                missing = tuple(
                    source_id
                    for source_id in explicit_source_ids
                    if source_id not in found
                )
                if missing:
                    missing_text = ", ".join(str(item) for item in missing)
                    raise ResearchSnapshotError(
                        "Explicit Research sources are absent/inactive at the pinned "
                        f"snapshot: {missing_text}"
                    )

            candidate_set_id = new_uuid7()
            connection.execute(
                """
                INSERT INTO research_candidate_sets (
                    candidate_set_id, scope_id, snapshot_commit_seq, state,
                    candidate_total, eligible_count, excluded_count,
                    created_at_us, frozen_at_us
                ) VALUES (?, ?, ?, 'building', 0, 0, 0, ?, NULL)
                """,
                (
                    uuid_to_blob(candidate_set_id),
                    uuid_to_blob(scope_id),
                    scope.snapshot_commit_seq,
                    now_us,
                ),
            )

            first_candidate_by_hash: dict[bytes, uuid.UUID] = {}
            eligible_count = 0
            excluded_count = 0
            for ordinal, row in enumerate(rows):
                source_id = uuid_from_blob(bytes(row["source_id"]))
                content_sha256 = bytes(row["content_sha256"])
                candidate_id = new_uuid7()
                duplicate_of = first_candidate_by_hash.get(content_sha256)
                if duplicate_of is None:
                    eligibility = ResearchCandidateEligibility.ELIGIBLE
                    first_candidate_by_hash[content_sha256] = candidate_id
                    eligible_count += 1
                else:
                    eligibility = ResearchCandidateEligibility.EXCLUDED_DUPLICATE
                    excluded_count += 1

                connection.execute(
                    """
                    INSERT INTO research_candidates (
                        candidate_id, candidate_set_id, source_id, ordinal,
                        content_sha256, eligibility_state,
                        duplicate_of_candidate_id, created_at_us
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        uuid_to_blob(candidate_id),
                        uuid_to_blob(candidate_set_id),
                        uuid_to_blob(source_id),
                        ordinal,
                        content_sha256,
                        eligibility.value,
                        (
                            uuid_to_blob(duplicate_of)
                            if duplicate_of is not None
                            else None
                        ),
                        now_us,
                    ),
                )
                if eligibility is ResearchCandidateEligibility.ELIGIBLE:
                    work_item_id = new_uuid7()
                    idempotency_key = _work_idempotency_key(
                        scope_id=scope_id,
                        source_id=source_id,
                        content_sha256=content_sha256,
                    )
                    connection.execute(
                        """
                        INSERT INTO research_work_items (
                            work_item_id, scope_id, candidate_id, state,
                            idempotency_key, source_analysis_job_id,
                            attempt_count, created_at_us, updated_at_us
                        ) VALUES (?, ?, ?, 'pending', ?, NULL, 0, ?, ?)
                        """,
                        (
                            uuid_to_blob(work_item_id),
                            uuid_to_blob(scope_id),
                            uuid_to_blob(candidate_id),
                            idempotency_key,
                            now_us,
                            now_us,
                        ),
                    )

            candidate_total = len(rows)
            connection.execute(
                """
                UPDATE research_candidate_sets
                SET state = 'frozen',
                    candidate_total = ?,
                    eligible_count = ?,
                    excluded_count = ?,
                    frozen_at_us = ?
                WHERE candidate_set_id = ?
                """,
                (
                    candidate_total,
                    eligible_count,
                    excluded_count,
                    now_us,
                    uuid_to_blob(candidate_set_id),
                ),
            )
            connection.execute(
                """
                UPDATE research_scopes
                SET state = 'frozen',
                    candidate_total = ?,
                    processed_count = 0,
                    successful_count = 0,
                    irrelevant_count = 0,
                    failed_count = 0,
                    unavailable_count = 0,
                    excluded_count = ?,
                    coverage_ratio = 0.0,
                    updated_at_us = ?
                WHERE scope_id = ?
                """,
                (
                    candidate_total,
                    excluded_count,
                    now_us,
                    uuid_to_blob(scope_id),
                ),
            )

        return self.get_candidate_set(scope_id)

    def pin_model_contract_fenced(
        self,
        scope_id: uuid.UUID,
        *,
        parent_job_id: uuid.UUID,
        lease_token: bytes,
        model_id: str,
        model_signature_id: uuid.UUID,
        model_signature_sha256: bytes,
        effective_context_limit: int,
        output_reserve: int,
        safety_margin: int,
        token_estimator: str,
        max_hierarchy_depth: int,
    ) -> ResearchScopeRecord:
        if len(model_signature_sha256) != 32:
            raise ResearchStateError("Research ModelSignature hash must be SHA-256.")
        expected = (
            model_id,
            model_signature_id,
            model_signature_sha256,
            effective_context_limit,
            output_reserve,
            safety_margin,
            token_estimator,
            max_hierarchy_depth,
        )
        with self.database.write_transaction() as connection:
            self._require_live_fence(connection, parent_job_id, lease_token)
            row = connection.execute(
                "SELECT * FROM research_scopes WHERE scope_id = ?",
                (uuid_to_blob(scope_id),),
            ).fetchone()
            if row is None:
                raise ResearchNotFoundError(str(scope_id))
            current = _scope_from_row(row)
            actual = (
                current.model_id,
                current.model_signature_id,
                current.model_signature_sha256,
                current.effective_context_limit,
                current.output_reserve,
                current.safety_margin,
                current.token_estimator,
                current.max_hierarchy_depth,
            )
            if any(item is not None for item in actual):
                if actual != expected:
                    raise ResearchStateError(
                        "ResearchScope already pins a different model contract."
                    )
                return current
            if output_reserve + safety_margin >= effective_context_limit:
                raise ResearchStateError(
                    "Research model contract leaves no effective input budget."
                )
            connection.execute(
                """
                UPDATE research_scopes
                SET model_id = ?,
                    model_signature_id = ?,
                    model_signature_sha256 = ?,
                    effective_context_limit = ?,
                    output_reserve = ?,
                    safety_margin = ?,
                    token_estimator = ?,
                    max_hierarchy_depth = ?,
                    updated_at_us = ?
                WHERE scope_id = ?
                """,
                (
                    model_id,
                    uuid_to_blob(model_signature_id),
                    model_signature_sha256,
                    effective_context_limit,
                    output_reserve,
                    safety_margin,
                    token_estimator,
                    max_hierarchy_depth,
                    utc_now_us(),
                    uuid_to_blob(scope_id),
                ),
            )
        return self.get_scope(scope_id)

    def mark_scope_state_fenced(
        self,
        scope_id: uuid.UUID,
        *,
        parent_job_id: uuid.UUID,
        lease_token: bytes,
        state: ResearchScopeState,
    ) -> ResearchScopeRecord:
        if state not in {ResearchScopeState.RUNNING, ResearchScopeState.PARTIAL}:
            raise ResearchStateError(
                f"Fenced orchestration cannot set ResearchScope to {state.value!r}."
            )
        with self.database.write_transaction() as connection:
            self._require_live_fence(connection, parent_job_id, lease_token)
            row = connection.execute(
                "SELECT state FROM research_scopes WHERE scope_id = ?",
                (uuid_to_blob(scope_id),),
            ).fetchone()
            if row is None:
                raise ResearchNotFoundError(str(scope_id))
            current = ResearchScopeState(str(row["state"]))
            if current is state:
                return self.get_scope(scope_id)
            allowed = (
                state is ResearchScopeState.RUNNING
                and current is ResearchScopeState.FROZEN
            ) or (
                state is ResearchScopeState.PARTIAL
                and current in {ResearchScopeState.FROZEN, ResearchScopeState.RUNNING}
            )
            if not allowed:
                raise ResearchStateError(
                    f"ResearchScope cannot transition {current.value!r} -> {state.value!r}."
                )
            connection.execute(
                "UPDATE research_scopes SET state = ?, updated_at_us = ? WHERE scope_id = ?",
                (state.value, utc_now_us(), uuid_to_blob(scope_id)),
            )
        return self.get_scope(scope_id)

    def mark_scope_partial_unleased(
        self,
        scope_id: uuid.UUID,
    ) -> ResearchScopeRecord:
        with self.database.write_transaction() as connection:
            row = connection.execute(
                """
                SELECT rs.state AS scope_state, j.state AS job_state
                FROM research_scopes AS rs
                JOIN jobs AS j ON j.job_id = rs.job_id
                WHERE rs.scope_id = ?
                """,
                (uuid_to_blob(scope_id),),
            ).fetchone()
            if row is None:
                raise ResearchNotFoundError(str(scope_id))
            if str(row["job_state"]) in {"running", "cancel_requested"}:
                raise ResearchStateError(
                    "Running ResearchScope must be made partial by its fenced worker."
                )
            current = ResearchScopeState(str(row["scope_state"]))
            if current is ResearchScopeState.PARTIAL:
                return self.get_scope(scope_id)
            if current not in {ResearchScopeState.FROZEN, ResearchScopeState.RUNNING}:
                raise ResearchStateError(
                    f"ResearchScope cannot become partial from {current.value!r}."
                )
            connection.execute(
                "UPDATE research_scopes SET state = 'partial', updated_at_us = ? "
                "WHERE scope_id = ?",
                (utc_now_us(), uuid_to_blob(scope_id)),
            )
        return self.get_scope(scope_id)

    def next_pending_work(
        self,
        scope_id: uuid.UUID,
    ) -> ResearchWorkItemRecord | None:
        row = self.database.connection.execute(
            """
            SELECT rw.*
            FROM research_work_items AS rw
            JOIN research_candidates AS rc ON rc.candidate_id = rw.candidate_id
            WHERE rw.scope_id = ? AND rw.state = 'pending'
            ORDER BY rc.ordinal ASC, rw.work_item_id ASC
            LIMIT 1
            """,
            (uuid_to_blob(scope_id),),
        ).fetchone()
        return None if row is None else _work_item_from_row(row)

    def get_candidate(
        self,
        candidate_id: uuid.UUID,
    ) -> ResearchCandidateRecord:
        row = self.database.connection.execute(
            "SELECT * FROM research_candidates WHERE candidate_id = ?",
            (uuid_to_blob(candidate_id),),
        ).fetchone()
        if row is None:
            raise ResearchNotFoundError(str(candidate_id))
        return _candidate_from_row(row)

    def find_child_job_for_work_item(
        self,
        work_item_id: uuid.UUID,
        *,
        job_type: str,
    ) -> uuid.UUID | None:
        if job_type not in {"source.process", "source.analyze"}:
            raise ResearchStateError(f"Unsupported Research child type {job_type!r}.")
        rows = self.database.connection.execute(
            """
            SELECT job_id
            FROM jobs
            WHERE job_type = ?
              AND json_extract(
                    requested_scope_json,
                    '$.research_work_item_id'
                  ) = ?
            ORDER BY created_at_us ASC, job_id ASC
            """,
            (job_type, str(work_item_id)),
        ).fetchall()
        if len(rows) > 1:
            raise ResearchStateError(
                f"Research work {work_item_id} has duplicate {job_type} children."
            )
        if not rows:
            return None
        return uuid_from_blob(bytes(rows[0]["job_id"]))

    def link_source_processing_job_fenced(
        self,
        work_item_id: uuid.UUID,
        *,
        parent_job_id: uuid.UUID,
        lease_token: bytes,
        child_job_id: uuid.UUID,
    ) -> ResearchWorkItemRecord:
        return self._link_child_job_fenced(
            work_item_id,
            parent_job_id=parent_job_id,
            lease_token=lease_token,
            child_job_id=child_job_id,
            column="source_processing_job_id",
            expected_job_type="source.process",
        )

    def link_source_analysis_job_fenced(
        self,
        work_item_id: uuid.UUID,
        *,
        parent_job_id: uuid.UUID,
        lease_token: bytes,
        child_job_id: uuid.UUID,
    ) -> ResearchWorkItemRecord:
        return self._link_child_job_fenced(
            work_item_id,
            parent_job_id=parent_job_id,
            lease_token=lease_token,
            child_job_id=child_job_id,
            column="source_analysis_job_id",
            expected_job_type="source.analyze",
        )

    def _link_child_job_fenced(
        self,
        work_item_id: uuid.UUID,
        *,
        parent_job_id: uuid.UUID,
        lease_token: bytes,
        child_job_id: uuid.UUID,
        column: str,
        expected_job_type: str,
    ) -> ResearchWorkItemRecord:
        if column not in {"source_processing_job_id", "source_analysis_job_id"}:
            raise ResearchStateError("Invalid Research child-link column.")
        with self.database.write_transaction() as connection:
            self._require_live_fence(connection, parent_job_id, lease_token)
            row = connection.execute(
                """
                SELECT rw.*, rc.source_id, rs.job_id AS parent_job_id
                FROM research_work_items AS rw
                JOIN research_candidates AS rc ON rc.candidate_id = rw.candidate_id
                JOIN research_scopes AS rs ON rs.scope_id = rw.scope_id
                WHERE rw.work_item_id = ?
                """,
                (uuid_to_blob(work_item_id),),
            ).fetchone()
            if row is None:
                raise ResearchNotFoundError(str(work_item_id))
            if bytes(row["parent_job_id"]) != parent_job_id.bytes:
                raise ResearchStateError("Research work belongs to another parent job.")
            existing = row[column]
            if existing is not None:
                existing_id = uuid_from_blob(bytes(existing))
                if existing_id != child_job_id:
                    raise ResearchStateError(
                        "Research work is already linked to a different child."
                    )
                return self.get_work_item(work_item_id)

            child = connection.execute(
                "SELECT job_type, requested_scope_json FROM jobs WHERE job_id = ?",
                (uuid_to_blob(child_job_id),),
            ).fetchone()
            if child is None or str(child["job_type"]) != expected_job_type:
                raise ResearchStateError(
                    f"Research child {child_job_id} is not {expected_job_type!r}."
                )
            try:
                child_scope = json.loads(str(child["requested_scope_json"]))
            except json.JSONDecodeError as exc:
                raise ResearchStateError("Research child scope is invalid JSON.") from exc
            if not isinstance(child_scope, dict):
                raise ResearchStateError("Research child scope must be an object.")
            if child_scope.get("research_work_item_id") != str(work_item_id):
                raise ResearchStateError("Research child lost its work identity.")
            source_id = uuid_from_blob(bytes(row["source_id"]))
            if child_scope.get("source_id") != str(source_id):
                raise ResearchStateError("Research child points at the wrong Source.")

            connection.execute(
                f"UPDATE research_work_items SET {column} = ?, updated_at_us = ? "
                "WHERE work_item_id = ?",
                (
                    uuid_to_blob(child_job_id),
                    utc_now_us(),
                    uuid_to_blob(work_item_id),
                ),
            )
        return self.get_work_item(work_item_id)

    def mark_work_state_fenced(
        self,
        work_item_id: uuid.UUID,
        *,
        parent_job_id: uuid.UUID,
        lease_token: bytes,
        state: ResearchWorkState,
    ) -> ResearchWorkItemRecord:
        if state is ResearchWorkState.PENDING:
            raise ResearchStateError("Fenced work commit requires a terminal state.")
        with self.database.write_transaction() as connection:
            self._require_live_fence(connection, parent_job_id, lease_token)
            row = connection.execute(
                """
                SELECT rw.*, rs.job_id AS parent_job_id
                FROM research_work_items AS rw
                JOIN research_scopes AS rs ON rs.scope_id = rw.scope_id
                WHERE rw.work_item_id = ?
                """,
                (uuid_to_blob(work_item_id),),
            ).fetchone()
            if row is None:
                raise ResearchNotFoundError(str(work_item_id))
            if bytes(row["parent_job_id"]) != parent_job_id.bytes:
                raise ResearchStateError("Research work belongs to another parent job.")
            current = _work_item_from_row(row)
            if current.state is state:
                return current
            if current.state is not ResearchWorkState.PENDING:
                raise ResearchStateError(
                    f"Research work {work_item_id} is already terminal "
                    f"({current.state.value!r})."
                )
            now_us = utc_now_us()
            connection.execute(
                """
                UPDATE research_work_items
                SET state = ?, attempt_count = attempt_count + 1, updated_at_us = ?
                WHERE work_item_id = ? AND state = 'pending'
                """,
                (state.value, now_us, uuid_to_blob(work_item_id)),
            )
            self._recompute_scope_counters(
                connection,
                scope_id=current.scope_id,
                now_us=now_us,
            )
        return self.get_work_item(work_item_id)

    def list_candidates(
        self,
        scope_id: uuid.UUID,
    ) -> tuple[ResearchCandidateRecord, ...]:
        rows = self.database.connection.execute(
            """
            SELECT c.*
            FROM research_candidates AS c
            JOIN research_candidate_sets AS cs
              ON cs.candidate_set_id = c.candidate_set_id
            WHERE cs.scope_id = ?
            ORDER BY c.ordinal ASC
            """,
            (uuid_to_blob(scope_id),),
        ).fetchall()
        return tuple(_candidate_from_row(row) for row in rows)

    def list_work_items(
        self,
        scope_id: uuid.UUID,
    ) -> tuple[ResearchWorkItemRecord, ...]:
        rows = self.database.connection.execute(
            """
            SELECT *
            FROM research_work_items
            WHERE scope_id = ?
            ORDER BY created_at_us ASC, work_item_id ASC
            """,
            (uuid_to_blob(scope_id),),
        ).fetchall()
        return tuple(_work_item_from_row(row) for row in rows)

    def mark_work_state(
        self,
        work_item_id: uuid.UUID,
        *,
        state: ResearchWorkState,
    ) -> ResearchWorkItemRecord:
        if state is ResearchWorkState.PENDING:
            raise ResearchStateError("mark_work_state requires a terminal state.")
        now_us = utc_now_us()
        scope_id: uuid.UUID
        with self.database.write_transaction() as connection:
            row = connection.execute(
                "SELECT * FROM research_work_items WHERE work_item_id = ?",
                (uuid_to_blob(work_item_id),),
            ).fetchone()
            if row is None:
                raise ResearchNotFoundError(str(work_item_id))
            current = _work_item_from_row(row)
            scope_id = current.scope_id
            if current.state is state:
                return current
            if current.state is not ResearchWorkState.PENDING:
                raise ResearchStateError(
                    f"Research work {work_item_id} is already terminal "
                    f"({current.state.value!r})."
                )
            connection.execute(
                """
                UPDATE research_work_items
                SET state = ?, attempt_count = attempt_count + 1, updated_at_us = ?
                WHERE work_item_id = ?
                """,
                (state.value, now_us, uuid_to_blob(work_item_id)),
            )
            self._recompute_scope_counters(
                connection,
                scope_id=scope_id,
                now_us=now_us,
            )
        return self.get_work_item(work_item_id)

    def get_work_item(self, work_item_id: uuid.UUID) -> ResearchWorkItemRecord:
        row = self.database.connection.execute(
            "SELECT * FROM research_work_items WHERE work_item_id = ?",
            (uuid_to_blob(work_item_id),),
        ).fetchone()
        if row is None:
            raise ResearchNotFoundError(str(work_item_id))
        return _work_item_from_row(row)


    def successful_source_analysis_final_artifact_ids(
        self,
        scope_id: uuid.UUID,
    ) -> tuple[uuid.UUID, ...]:
        """Return successful SourceAnalysis FINAL artifacts in frozen candidate order."""
        return self._successful_source_analysis_final_artifact_ids(
            self.database.connection,
            scope_id,
        )

    @staticmethod
    def _successful_source_analysis_final_artifact_ids(
        connection: sqlite3.Connection,
        scope_id: uuid.UUID,
    ) -> tuple[uuid.UUID, ...]:
        scope = connection.execute(
            "SELECT successful_count FROM research_scopes WHERE scope_id = ?",
            (uuid_to_blob(scope_id),),
        ).fetchone()
        if scope is None:
            raise ResearchNotFoundError(str(scope_id))
        rows = connection.execute(
            """
            SELECT sa.final_artifact_id
            FROM research_work_items AS rw
            JOIN research_candidates AS rc ON rc.candidate_id = rw.candidate_id
            JOIN source_analyses AS sa ON sa.job_id = rw.source_analysis_job_id
            JOIN source_analysis_artifacts AS artifact
              ON artifact.artifact_id = sa.final_artifact_id
             AND artifact.analysis_id = sa.analysis_id
             AND artifact.artifact_kind = 'final'
            WHERE rw.scope_id = ?
              AND rw.state = 'successful'
              AND sa.state = 'completed'
              AND sa.coverage = 1.0
              AND sa.final_artifact_id IS NOT NULL
            ORDER BY rc.ordinal ASC, artifact.artifact_id ASC
            """,
            (uuid_to_blob(scope_id),),
        ).fetchall()
        result = tuple(uuid_from_blob(bytes(row[0])) for row in rows)
        if len(result) != int(scope["successful_count"]):
            raise ResearchStateError(
                "Successful Research work does not resolve to exactly one completed "
                "SourceAnalysis FINAL artifact per source."
            )
        return result

    def create_synthesis_work_item_fenced(
        self,
        scope_id: uuid.UUID,
        *,
        parent_job_id: uuid.UUID,
        lease_token: bytes,
        stage: ResearchSynthesisStage,
        level: int,
        ordinal: int,
        inputs: Sequence[tuple[ResearchSynthesisInputKind, uuid.UUID]],
        descriptor: Mapping[str, Any],
        pipeline_version: str,
        prompt_template_id: str,
        prompt_template_version: str,
    ) -> ResearchSynthesisWorkItemRecord:
        if level < 0 or ordinal < 0:
            raise ResearchStateError(
                "Research synthesis level and ordinal must not be negative."
            )
        if not inputs:
            raise ResearchStateError(
                "Research synthesis work requires at least one immutable input."
            )
        normalized_pipeline = _required_text(
            pipeline_version,
            "Research synthesis pipeline_version",
        )
        normalized_prompt = _required_text(
            prompt_template_id,
            "Research synthesis prompt_template_id",
        )
        normalized_prompt_version = _required_text(
            prompt_template_version,
            "Research synthesis prompt_template_version",
        )
        key = _synthesis_work_idempotency_key(
            scope_id=scope_id,
            stage=stage,
            level=level,
            ordinal=ordinal,
            inputs=inputs,
            descriptor=descriptor,
            pipeline_version=normalized_pipeline,
            prompt_template_id=normalized_prompt,
            prompt_template_version=normalized_prompt_version,
        )
        with self.database.write_transaction() as connection:
            self._require_running_fence(
                connection,
                parent_job_id,
                lease_token,
            )
            scope_row = connection.execute(
                "SELECT job_id, state FROM research_scopes WHERE scope_id = ?",
                (uuid_to_blob(scope_id),),
            ).fetchone()
            if scope_row is None:
                raise ResearchNotFoundError(str(scope_id))
            if bytes(scope_row["job_id"]) != parent_job_id.bytes:
                raise ResearchStateError(
                    "Research synthesis scope belongs to another parent job."
                )
            if ResearchScopeState(str(scope_row["state"])) is not ResearchScopeState.RUNNING:
                raise ResearchStateError(
                    "Research synthesis can only be planned for a running scope."
                )
            pending = connection.execute(
                "SELECT COUNT(*) FROM research_work_items "
                "WHERE scope_id = ? AND state = 'pending'",
                (uuid_to_blob(scope_id),),
            ).fetchone()
            if pending is None or int(pending[0]) != 0:
                raise ResearchStateError(
                    "Research synthesis cannot start before all source work is terminal."
                )

            existing = connection.execute(
                "SELECT * FROM research_synthesis_work_items "
                "WHERE idempotency_key = ?",
                (key,),
            ).fetchone()
            if existing is not None:
                item = _synthesis_work_item_from_row(existing)
                expected = (
                    scope_id,
                    stage,
                    level,
                    ordinal,
                    normalized_pipeline,
                    normalized_prompt,
                    normalized_prompt_version,
                )
                actual = (
                    item.scope_id,
                    item.stage,
                    item.level,
                    item.ordinal,
                    item.pipeline_version,
                    item.prompt_template_id,
                    item.prompt_template_version,
                )
                if actual != expected:
                    raise ResearchStateError(
                        "Research synthesis idempotency key collided with different work."
                    )
                persisted_inputs = self._synthesis_inputs_for_work_item(
                    connection,
                    item.work_item_id,
                )
                expected_inputs = tuple(inputs)
                actual_inputs = tuple(
                    (
                        persisted.input_kind,
                        persisted.source_analysis_artifact_id
                        if persisted.input_kind
                        is ResearchSynthesisInputKind.SOURCE_ANALYSIS_ARTIFACT
                        else persisted.research_synthesis_artifact_id,
                    )
                    for persisted in persisted_inputs
                )
                if actual_inputs != expected_inputs:
                    raise ResearchStateError(
                        "Idempotent Research synthesis work disagrees on immutable inputs."
                    )
                return item

            self._validate_synthesis_inputs(
                connection,
                scope_id=scope_id,
                inputs=inputs,
            )
            now_us = utc_now_us()
            work_item_id = new_uuid7()
            connection.execute(
                """
                INSERT INTO research_synthesis_work_items (
                    work_item_id, scope_id, stage, level, ordinal, state,
                    idempotency_key, pipeline_version, prompt_template_id,
                    prompt_template_version, attempt_count, created_at_us, updated_at_us
                ) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, 0, ?, ?)
                """,
                (
                    uuid_to_blob(work_item_id),
                    uuid_to_blob(scope_id),
                    stage.value,
                    level,
                    ordinal,
                    key,
                    normalized_pipeline,
                    normalized_prompt,
                    normalized_prompt_version,
                    now_us,
                    now_us,
                ),
            )
            for input_ordinal, (kind, ref_id) in enumerate(inputs):
                connection.execute(
                    """
                    INSERT INTO research_synthesis_work_inputs (
                        work_item_id, ordinal, input_kind,
                        source_analysis_artifact_id,
                        research_synthesis_artifact_id
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        uuid_to_blob(work_item_id),
                        input_ordinal,
                        kind.value,
                        (
                            uuid_to_blob(ref_id)
                            if kind
                            is ResearchSynthesisInputKind.SOURCE_ANALYSIS_ARTIFACT
                            else None
                        ),
                        (
                            uuid_to_blob(ref_id)
                            if kind
                            is ResearchSynthesisInputKind.RESEARCH_SYNTHESIS_ARTIFACT
                            else None
                        ),
                    ),
                )
            row = connection.execute(
                "SELECT * FROM research_synthesis_work_items WHERE work_item_id = ?",
                (uuid_to_blob(work_item_id),),
            ).fetchone()
            assert row is not None
            return _synthesis_work_item_from_row(row)

    @staticmethod
    def _validate_synthesis_inputs(
        connection: sqlite3.Connection,
        *,
        scope_id: uuid.UUID,
        inputs: Sequence[tuple[ResearchSynthesisInputKind, uuid.UUID]],
    ) -> None:
        seen: set[tuple[ResearchSynthesisInputKind, uuid.UUID]] = set()
        successful_final_ids = set(
            ResearchRepository._successful_source_analysis_final_artifact_ids(
                connection,
                scope_id,
            )
        )
        for kind, ref_id in inputs:
            identity = (kind, ref_id)
            if identity in seen:
                raise ResearchStateError(
                    "Research synthesis work cannot repeat the same immutable input."
                )
            seen.add(identity)
            if kind is ResearchSynthesisInputKind.SOURCE_ANALYSIS_ARTIFACT:
                if ref_id not in successful_final_ids:
                    raise ResearchStateError(
                        "Research synthesis SourceAnalysis input is not the completed "
                        "FINAL artifact of SUCCESSFUL source work in this scope."
                    )
                continue
            if kind is ResearchSynthesisInputKind.RESEARCH_SYNTHESIS_ARTIFACT:
                row = connection.execute(
                    """
                    SELECT work.state
                    FROM research_synthesis_artifacts AS artifact
                    JOIN research_synthesis_work_items AS work
                      ON work.work_item_id = artifact.work_item_id
                    WHERE artifact.artifact_id = ?
                      AND artifact.scope_id = ?
                    """,
                    (uuid_to_blob(ref_id), uuid_to_blob(scope_id)),
                ).fetchone()
                if row is None or str(row["state"]) != "completed":
                    raise ResearchStateError(
                        "Research synthesis artifact input is absent, cross-scope, "
                        "or not durably completed."
                    )
                continue
            raise ResearchStateError(
                f"Unsupported Research synthesis input kind {kind!r}."
            )

    def get_synthesis_work_item(
        self,
        work_item_id: uuid.UUID,
    ) -> ResearchSynthesisWorkItemRecord:
        row = self.database.connection.execute(
            "SELECT * FROM research_synthesis_work_items WHERE work_item_id = ?",
            (uuid_to_blob(work_item_id),),
        ).fetchone()
        if row is None:
            raise ResearchNotFoundError(
                f"Research synthesis work {work_item_id} does not exist."
            )
        return _synthesis_work_item_from_row(row)

    def list_synthesis_work_items(
        self,
        scope_id: uuid.UUID,
        *,
        stage: ResearchSynthesisStage | None = None,
        state: ResearchSynthesisWorkState | None = None,
    ) -> tuple[ResearchSynthesisWorkItemRecord, ...]:
        clauses = ["scope_id = ?"]
        params: list[object] = [uuid_to_blob(scope_id)]
        if stage is not None:
            clauses.append("stage = ?")
            params.append(stage.value)
        if state is not None:
            clauses.append("state = ?")
            params.append(state.value)
        rows = self.database.connection.execute(
            "SELECT * FROM research_synthesis_work_items WHERE "
            + " AND ".join(clauses)
            + " ORDER BY level, ordinal, work_item_id",
            tuple(params),
        ).fetchall()
        return tuple(_synthesis_work_item_from_row(row) for row in rows)

    def next_pending_synthesis(
        self,
        scope_id: uuid.UUID,
    ) -> ResearchSynthesisWorkItemRecord | None:
        row = self.database.connection.execute(
            """
            SELECT * FROM research_synthesis_work_items
            WHERE scope_id = ? AND state = 'pending'
            ORDER BY level, ordinal, work_item_id
            LIMIT 1
            """,
            (uuid_to_blob(scope_id),),
        ).fetchone()
        return None if row is None else _synthesis_work_item_from_row(row)

    def synthesis_inputs_for_work_item(
        self,
        work_item_id: uuid.UUID,
    ) -> tuple[ResearchSynthesisWorkInputRecord, ...]:
        return self._synthesis_inputs_for_work_item(
            self.database.connection,
            work_item_id,
        )

    @staticmethod
    def _synthesis_inputs_for_work_item(
        connection: sqlite3.Connection,
        work_item_id: uuid.UUID,
    ) -> tuple[ResearchSynthesisWorkInputRecord, ...]:
        rows = connection.execute(
            """
            SELECT * FROM research_synthesis_work_inputs
            WHERE work_item_id = ?
            ORDER BY ordinal
            """,
            (uuid_to_blob(work_item_id),),
        ).fetchall()
        return tuple(_synthesis_work_input_from_row(row) for row in rows)


    def split_synthesis_work_item_fenced(
        self,
        work_item_id: uuid.UUID,
        *,
        parent_job_id: uuid.UUID,
        lease_token: bytes,
        children: Sequence[
            tuple[
                int,
                int,
                Sequence[tuple[ResearchSynthesisInputKind, uuid.UUID]],
                Mapping[str, Any],
            ]
        ],
    ) -> tuple[ResearchSynthesisWorkItemRecord, ...]:
        """Atomically supersede pending synthesis work with convergent REDUCE children."""
        if not children:
            raise ResearchStateError(
                "Research synthesis split requires at least one convergent child."
            )

        with self.database.write_transaction() as connection:
            self._require_running_fence(
                connection,
                parent_job_id,
                lease_token,
            )
            parent_row = connection.execute(
                """
                SELECT work.*, scope.job_id AS parent_job_id,
                       scope.state AS scope_state
                FROM research_synthesis_work_items AS work
                JOIN research_scopes AS scope ON scope.scope_id = work.scope_id
                WHERE work.work_item_id = ?
                """,
                (uuid_to_blob(work_item_id),),
            ).fetchone()
            if parent_row is None:
                raise ResearchNotFoundError(
                    f"Research synthesis work {work_item_id} does not exist."
                )
            if bytes(parent_row["parent_job_id"]) != parent_job_id.bytes:
                raise ResearchStateError(
                    "Research synthesis work belongs to another parent job."
                )
            if str(parent_row["scope_state"]) != ResearchScopeState.RUNNING.value:
                raise ResearchStateError(
                    "Research synthesis split requires a running scope."
                )

            parent = _synthesis_work_item_from_row(parent_row)
            if parent.stage not in {
                ResearchSynthesisStage.REDUCE,
                ResearchSynthesisStage.FINAL,
            }:
                raise ResearchStateError(
                    "Only reduce/final Research synthesis work can be split."
                )

            parent_inputs = self._synthesis_inputs_for_work_item(
                connection,
                work_item_id,
            )
            parent_refs = tuple(
                (
                    item.input_kind,
                    item.source_analysis_artifact_id
                    if item.input_kind
                    is ResearchSynthesisInputKind.SOURCE_ANALYSIS_ARTIFACT
                    else item.research_synthesis_artifact_id,
                )
                for item in parent_inputs
            )
            if any(ref_id is None for _kind, ref_id in parent_refs):
                raise ResearchStateError(
                    "Research synthesis parent has an incomplete immutable input."
                )
            if len(set(parent_refs)) != len(parent_refs):
                raise ResearchStateError(
                    "Research synthesis split cannot disambiguate duplicate parent inputs."
                )
            allowed_refs = set(parent_refs)
            used_refs: set[tuple[ResearchSynthesisInputKind, uuid.UUID | None]] = set()

            normalized_children: list[
                tuple[
                    bytes,
                    int,
                    int,
                    tuple[tuple[ResearchSynthesisInputKind, uuid.UUID], ...],
                ]
            ] = []
            for child_level, child_ordinal, child_inputs_raw, descriptor in children:
                child_inputs = tuple(child_inputs_raw)
                if child_level != parent.level + 1:
                    raise ResearchStateError(
                        "Research synthesis split child level must be parent level + 1."
                    )
                if child_ordinal < 0:
                    raise ResearchStateError(
                        "Research synthesis split child ordinal must not be negative."
                    )
                if not child_inputs:
                    raise ResearchStateError(
                        "Research synthesis REDUCE child requires at least one input."
                    )
                if len(set(child_inputs)) != len(child_inputs):
                    raise ResearchStateError(
                        "Research synthesis REDUCE child contains duplicate inputs."
                    )
                for child_ref in child_inputs:
                    if child_ref not in allowed_refs:
                        raise ResearchStateError(
                            "Research synthesis split child references an input "
                            "outside its parent."
                        )
                    if child_ref in used_refs:
                        raise ResearchStateError(
                            "Research synthesis split children must not overlap inputs."
                        )
                    used_refs.add(child_ref)

                key = _synthesis_work_idempotency_key(
                    scope_id=parent.scope_id,
                    stage=ResearchSynthesisStage.REDUCE,
                    level=child_level,
                    ordinal=child_ordinal,
                    inputs=child_inputs,
                    descriptor={
                        "split_parent_work_item_id": str(work_item_id),
                        "child": descriptor,
                    },
                    pipeline_version=parent.pipeline_version,
                    prompt_template_id=parent.prompt_template_id,
                    prompt_template_version=parent.prompt_template_version,
                )
                normalized_children.append(
                    (
                        key,
                        child_level,
                        child_ordinal,
                        child_inputs,
                    )
                )

            def persisted_child(
                key: bytes,
                child_level: int,
                child_ordinal: int,
                child_inputs: tuple[
                    tuple[ResearchSynthesisInputKind, uuid.UUID], ...
                ],
            ) -> ResearchSynthesisWorkItemRecord:
                row = connection.execute(
                    """
                    SELECT *
                    FROM research_synthesis_work_items
                    WHERE idempotency_key = ?
                    """,
                    (key,),
                ).fetchone()
                if row is None:
                    raise ResearchStateError(
                        "Previously split Research synthesis work lost a "
                        "deterministic child."
                    )
                item = _synthesis_work_item_from_row(row)
                identity = (
                    item.scope_id,
                    item.stage,
                    item.level,
                    item.ordinal,
                    item.pipeline_version,
                    item.prompt_template_id,
                    item.prompt_template_version,
                )
                expected_identity = (
                    parent.scope_id,
                    ResearchSynthesisStage.REDUCE,
                    child_level,
                    child_ordinal,
                    parent.pipeline_version,
                    parent.prompt_template_id,
                    parent.prompt_template_version,
                )
                if identity != expected_identity:
                    raise ResearchStateError(
                        "Research synthesis split child identity drifted."
                    )
                persisted_inputs = self._synthesis_inputs_for_work_item(
                    connection,
                    item.work_item_id,
                )
                actual_inputs = tuple(
                    (
                        persisted.input_kind,
                        persisted.source_analysis_artifact_id
                        if persisted.input_kind
                        is ResearchSynthesisInputKind.SOURCE_ANALYSIS_ARTIFACT
                        else persisted.research_synthesis_artifact_id,
                    )
                    for persisted in persisted_inputs
                )
                if actual_inputs != child_inputs:
                    raise ResearchStateError(
                        "Research synthesis split child immutable inputs drifted."
                    )
                return item

            if parent.state is ResearchSynthesisWorkState.SPLIT:
                return tuple(
                    persisted_child(
                        key,
                        child_level,
                        child_ordinal,
                        child_inputs,
                    )
                    for key, child_level, child_ordinal, child_inputs
                    in normalized_children
                )
            if parent.state is not ResearchSynthesisWorkState.PENDING:
                raise ResearchStateError(
                    "Only pending Research synthesis work can be split."
                )

            now_us = utc_now_us()
            created: list[ResearchSynthesisWorkItemRecord] = []
            for key, child_level, child_ordinal, child_inputs in normalized_children:
                existing = connection.execute(
                    """
                    SELECT *
                    FROM research_synthesis_work_items
                    WHERE idempotency_key = ?
                    """,
                    (key,),
                ).fetchone()
                if existing is not None:
                    created.append(
                        persisted_child(
                            key,
                            child_level,
                            child_ordinal,
                            child_inputs,
                        )
                    )
                    continue

                self._validate_synthesis_inputs(
                    connection,
                    scope_id=parent.scope_id,
                    inputs=child_inputs,
                )
                child_id = new_uuid7()
                connection.execute(
                    """
                    INSERT INTO research_synthesis_work_items (
                        work_item_id, scope_id, stage, level, ordinal, state,
                        idempotency_key, pipeline_version, prompt_template_id,
                        prompt_template_version, attempt_count,
                        created_at_us, updated_at_us
                    ) VALUES (
                        ?, ?, 'reduce', ?, ?, 'pending',
                        ?, ?, ?, ?, 0, ?, ?
                    )
                    """,
                    (
                        uuid_to_blob(child_id),
                        uuid_to_blob(parent.scope_id),
                        child_level,
                        child_ordinal,
                        key,
                        parent.pipeline_version,
                        parent.prompt_template_id,
                        parent.prompt_template_version,
                        now_us,
                        now_us,
                    ),
                )
                for input_ordinal, (kind, ref_id) in enumerate(child_inputs):
                    connection.execute(
                        """
                        INSERT INTO research_synthesis_work_inputs (
                            work_item_id, ordinal, input_kind,
                            source_analysis_artifact_id,
                            research_synthesis_artifact_id
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            uuid_to_blob(child_id),
                            input_ordinal,
                            kind.value,
                            (
                                uuid_to_blob(ref_id)
                                if kind
                                is ResearchSynthesisInputKind.SOURCE_ANALYSIS_ARTIFACT
                                else None
                            ),
                            (
                                uuid_to_blob(ref_id)
                                if kind
                                is ResearchSynthesisInputKind.RESEARCH_SYNTHESIS_ARTIFACT
                                else None
                            ),
                        ),
                    )
                row = connection.execute(
                    """
                    SELECT *
                    FROM research_synthesis_work_items
                    WHERE work_item_id = ?
                    """,
                    (uuid_to_blob(child_id),),
                ).fetchone()
                assert row is not None
                created.append(_synthesis_work_item_from_row(row))

            cursor = connection.execute(
                """
                UPDATE research_synthesis_work_items
                SET state = 'split', updated_at_us = ?
                WHERE work_item_id = ? AND state = 'pending'
                """,
                (now_us, uuid_to_blob(work_item_id)),
            )
            if cursor.rowcount != 1:
                raise ResearchStateError(
                    "Research synthesis parent lost its pending state during split."
                )
            return tuple(created)


    def begin_synthesis_attempt_fenced(
        self,
        work_item_id: uuid.UUID,
        *,
        parent_job_id: uuid.UUID,
        lease_token: bytes,
    ) -> ResearchSynthesisWorkItemRecord:
        with self.database.write_transaction() as connection:
            self._require_running_fence(
                connection,
                parent_job_id,
                lease_token,
            )
            row = connection.execute(
                """
                SELECT work.*, scope.job_id AS parent_job_id, scope.state AS scope_state
                FROM research_synthesis_work_items AS work
                JOIN research_scopes AS scope ON scope.scope_id = work.scope_id
                WHERE work.work_item_id = ?
                """,
                (uuid_to_blob(work_item_id),),
            ).fetchone()
            if row is None:
                raise ResearchNotFoundError(
                    f"Research synthesis work {work_item_id} does not exist."
                )
            if bytes(row["parent_job_id"]) != parent_job_id.bytes:
                raise ResearchStateError(
                    "Research synthesis work belongs to another parent job."
                )
            if str(row["scope_state"]) != ResearchScopeState.RUNNING.value:
                raise ResearchStateError(
                    "Research synthesis attempt requires a running scope."
                )
            item = _synthesis_work_item_from_row(row)
            if item.state is not ResearchSynthesisWorkState.PENDING:
                raise ResearchStateError(
                    "Only pending Research synthesis work can begin an attempt."
                )
            cursor = connection.execute(
                """
                UPDATE research_synthesis_work_items
                SET attempt_count = attempt_count + 1, updated_at_us = ?
                WHERE work_item_id = ? AND state = 'pending'
                """,
                (utc_now_us(), uuid_to_blob(work_item_id)),
            )
            if cursor.rowcount != 1:
                raise ResearchStateError(
                    "Research synthesis work lost its pending state at attempt start."
                )
            updated = connection.execute(
                "SELECT * FROM research_synthesis_work_items WHERE work_item_id = ?",
                (uuid_to_blob(work_item_id),),
            ).fetchone()
            assert updated is not None
            return _synthesis_work_item_from_row(updated)

    def commit_synthesis_artifact_fenced(
        self,
        *,
        work_item_id: uuid.UUID,
        parent_job_id: uuid.UUID,
        lease_token: bytes,
        content: Mapping[str, Any],
        processing_run_id: uuid.UUID,
        evidence: Sequence[tuple[str, int, int]],
        source_evidence: (
            Sequence[tuple[str, int, uuid.UUID]] | None
        ) = None,
    ) -> ResearchSynthesisArtifactRecord:
        content_json = _canonical_json_object(content)
        content_hash = hashlib.sha256(content_json.encode("utf-8")).digest()
        evidence_rows = _validated_synthesis_evidence(content, evidence)
        requested_source_evidence_rows = (
            None
            if source_evidence is None
            else _validated_synthesis_source_evidence(
                content,
                source_evidence,
            )
        )

        with self.database.write_transaction() as connection:
            self._require_running_fence(
                connection,
                parent_job_id,
                lease_token,
            )
            row = connection.execute(
                """
                SELECT work.*, scope.job_id AS parent_job_id,
                       scope.state AS scope_state,
                       scope.model_signature_id
                FROM research_synthesis_work_items AS work
                JOIN research_scopes AS scope ON scope.scope_id = work.scope_id
                WHERE work.work_item_id = ?
                """,
                (uuid_to_blob(work_item_id),),
            ).fetchone()
            if row is None:
                raise ResearchNotFoundError(
                    f"Research synthesis work {work_item_id} does not exist."
                )
            if bytes(row["parent_job_id"]) != parent_job_id.bytes:
                raise ResearchStateError(
                    "Research synthesis work belongs to another parent job."
                )
            if str(row["scope_state"]) != ResearchScopeState.RUNNING.value:
                raise ResearchStateError(
                    "Research synthesis artifact commit requires a running scope."
                )
            item = _synthesis_work_item_from_row(row)

            work_inputs = {
                input_item.ordinal: input_item
                for input_item in self._synthesis_inputs_for_work_item(
                    connection,
                    work_item_id,
                )
            }
            input_ordinals = set(work_inputs)

            if any(
                input_ordinal not in input_ordinals
                for _kind, _output_ordinal, input_ordinal
                in evidence_rows
            ):
                raise ResearchStateError(
                    "Research synthesis output evidence references "
                    "a missing work input."
                )

            allowed_sources_by_output: dict[
                tuple[str, int],
                set[uuid.UUID],
            ] = {}
            nested_input_was_cited = False

            for kind, output_ordinal, input_ordinal in evidence_rows:
                input_item = work_inputs[input_ordinal]
                reachable: tuple[uuid.UUID, ...]

                if (
                    input_item.input_kind
                    is ResearchSynthesisInputKind.SOURCE_ANALYSIS_ARTIFACT
                ):
                    if input_item.source_analysis_artifact_id is None:
                        raise ResearchStateError(
                            "Research synthesis direct source input "
                            "lost its artifact ID."
                        )
                    reachable = (
                        input_item.source_analysis_artifact_id,
                    )
                else:
                    nested_input_was_cited = True
                    if (
                        input_item.research_synthesis_artifact_id
                        is None
                    ):
                        raise ResearchStateError(
                            "Research synthesis nested input "
                            "lost its artifact ID."
                        )
                    reachable = (
                        self._source_analysis_artifact_ids_for_synthesis_artifact(
                            connection,
                            input_item.research_synthesis_artifact_id,
                        )
                    )

                allowed_sources_by_output.setdefault(
                    (kind, output_ordinal),
                    set(),
                ).update(reachable)

            if requested_source_evidence_rows is None:
                if nested_input_was_cited:
                    raise ResearchStateError(
                        "Nested Research synthesis commits require "
                        "explicit precise terminal source evidence."
                    )

                derived_source_evidence = tuple(
                    (
                        kind,
                        output_ordinal,
                        source_id,
                    )
                    for (kind, output_ordinal), source_ids
                    in allowed_sources_by_output.items()
                    for source_id in source_ids
                )

                source_evidence_rows = (
                    _validated_synthesis_source_evidence(
                        content,
                        derived_source_evidence,
                    )
                )
            else:
                source_evidence_rows = (
                    requested_source_evidence_rows
                )

            expected_source_outputs = {
                (kind, output_ordinal)
                for kind, output_ordinal, _input_ordinal
                in evidence_rows
            }
            actual_source_outputs = {
                (kind, output_ordinal)
                for kind, output_ordinal, _source_id
                in source_evidence_rows
            }

            if actual_source_outputs != expected_source_outputs:
                raise ResearchStateError(
                    "Research synthesis terminal source backlinks "
                    "do not cover exactly the synthesized outputs."
                )

            for (
                kind,
                output_ordinal,
                source_artifact_id,
            ) in source_evidence_rows:
                allowed = allowed_sources_by_output.get(
                    (kind, output_ordinal),
                    set(),
                )
                if source_artifact_id not in allowed:
                    raise ResearchStateError(
                        "Research synthesis terminal source backlink "
                        "escapes the cited input provenance graph."
                    )

            existing = connection.execute(
                "SELECT * FROM research_synthesis_artifacts WHERE work_item_id = ?",
                (uuid_to_blob(work_item_id),),
            ).fetchone()
            if existing is not None:
                artifact = _synthesis_artifact_from_row(existing)
                if artifact.content_hash != content_hash:
                    raise ResearchStateError(
                        "Completed Research synthesis work cannot be overwritten."
                    )
                persisted_evidence = self._synthesis_evidence_for_artifact(
                    connection,
                    artifact.artifact_id,
                )
                expected_evidence = tuple(
                    ResearchSynthesisEvidenceRecord(
                        artifact_id=artifact.artifact_id,
                        work_item_id=work_item_id,
                        output_kind=kind,
                        output_ordinal=output_ordinal,
                        input_ordinal=input_ordinal,
                    )
                    for kind, output_ordinal, input_ordinal in evidence_rows
                )
                if persisted_evidence != expected_evidence:
                    raise ResearchStateError(
                        "Idempotent Research synthesis artifact "
                        "disagrees on evidence."
                    )

                persisted_source_rows = connection.execute(
                    """
                    SELECT output_kind, output_ordinal,
                           source_analysis_artifact_id
                    FROM research_synthesis_output_source_evidence
                    WHERE artifact_id = ?
                    ORDER BY output_kind, output_ordinal,
                             source_analysis_artifact_id
                    """,
                    (uuid_to_blob(artifact.artifact_id),),
                ).fetchall()

                persisted_source_evidence = tuple(
                    (
                        str(source_row["output_kind"]),
                        int(source_row["output_ordinal"]),
                        uuid_from_blob(
                            bytes(
                                source_row[
                                    "source_analysis_artifact_id"
                                ]
                            )
                        ),
                    )
                    for source_row in persisted_source_rows
                )

                if (
                    persisted_source_evidence
                    != source_evidence_rows
                ):
                    raise ResearchStateError(
                        "Idempotent Research synthesis artifact "
                        "disagrees on terminal source evidence."
                    )

                return artifact

            if item.state is not ResearchSynthesisWorkState.PENDING:
                raise ResearchStateError(
                    "Only pending Research synthesis work can commit an artifact."
                )
            signature_blob = row["model_signature_id"]
            if signature_blob is None:
                raise ResearchStateError(
                    "Research synthesis work has no pinned ModelSignature."
                )
            run = connection.execute(
                """
                SELECT status, model_signature_id, pipeline_version,
                       prompt_template_id, prompt_template_version
                FROM processing_runs
                WHERE processing_run_id = ?
                """,
                (uuid_to_blob(processing_run_id),),
            ).fetchone()
            if run is None or str(run["status"]) != "running":
                raise ResearchStateError(
                    "Research synthesis artifact ProcessingRun is not running."
                )
            run_signature_blob = run["model_signature_id"]
            if run_signature_blob is None:
                raise ResearchStateError(
                    "Research synthesis ProcessingRun lost its ModelSignature."
                )

            if bytes(run_signature_blob) != bytes(signature_blob):
                scope_signature = connection.execute(
                    """
                    SELECT provider, model_identifier, model_revision,
                           quantization, generation_parameters_json,
                           context_configuration_json
                    FROM model_signatures
                    WHERE model_signature_id = ?
                    """,
                    (bytes(signature_blob),),
                ).fetchone()
                derived_signature = connection.execute(
                    """
                    SELECT provider, model_identifier, model_revision,
                           quantization, generation_parameters_json,
                           context_configuration_json
                    FROM model_signatures
                    WHERE model_signature_id = ?
                    """,
                    (bytes(run_signature_blob),),
                ).fetchone()

                if scope_signature is None or derived_signature is None:
                    raise ResearchStateError(
                        "Research synthesis ProcessingRun references an "
                        "unknown ModelSignature lineage."
                    )

                identity_fields = (
                    "provider",
                    "model_identifier",
                    "model_revision",
                    "quantization",
                )
                if any(
                    derived_signature[field] != scope_signature[field]
                    for field in identity_fields
                ):
                    raise ResearchStateError(
                        "Research synthesis derived ModelSignature changed "
                        "the pinned model identity."
                    )

                try:
                    derived_context = json.loads(
                        str(
                            derived_signature[
                                "context_configuration_json"
                            ]
                        )
                    )
                    derived_generation = json.loads(
                        str(
                            derived_signature[
                                "generation_parameters_json"
                            ]
                        )
                    )
                except (TypeError, ValueError, json.JSONDecodeError) as exc:
                    raise ResearchStateError(
                        "Research synthesis derived ModelSignature has "
                        "invalid configuration JSON."
                    ) from exc

                if (
                    not isinstance(derived_context, Mapping)
                    or not isinstance(derived_generation, Mapping)
                ):
                    raise ResearchStateError(
                        "Research synthesis derived ModelSignature "
                        "configuration must be JSON objects."
                    )

                expected_base_signature_id = str(
                    uuid_from_blob(bytes(signature_blob))
                )
                base_signature_id = derived_context.get(
                    "base_model_signature_id"
                )
                capacity_policy_id = derived_context.get(
                    "capacity_policy_id"
                )
                base_output_reserve = derived_context.get(
                    "base_output_reserve"
                )
                output_reserve = derived_context.get(
                    "output_reserve"
                )
                generation_output_reserve = (
                    derived_generation.get("max_output_tokens")
                )

                valid_capacity_derivation = (
                    base_signature_id == expected_base_signature_id
                    and isinstance(capacity_policy_id, str)
                    and bool(capacity_policy_id.strip())
                    and isinstance(base_output_reserve, int)
                    and not isinstance(base_output_reserve, bool)
                    and base_output_reserve > 0
                    and isinstance(output_reserve, int)
                    and not isinstance(output_reserve, bool)
                    and output_reserve > base_output_reserve
                    and isinstance(generation_output_reserve, int)
                    and not isinstance(
                        generation_output_reserve,
                        bool,
                    )
                    and generation_output_reserve
                    == output_reserve
                    and derived_generation.get("structured_output")
                    is True
                )
                if not valid_capacity_derivation:
                    raise ResearchStateError(
                        "Research synthesis ProcessingRun has an "
                        "unauthorized derived ModelSignature."
                    )
            if (
                str(run["pipeline_version"]) != item.pipeline_version
                or run["prompt_template_id"] is None
                or str(run["prompt_template_id"]) != item.prompt_template_id
                or run["prompt_template_version"] is None
                or str(run["prompt_template_version"])
                != item.prompt_template_version
            ):
                raise ResearchStateError(
                    "Research synthesis ProcessingRun prompt/pipeline provenance drifted."
                )

            now_us = utc_now_us()
            artifact_id = new_uuid7()
            connection.execute(
                """
                INSERT INTO research_synthesis_artifacts (
                    artifact_id, scope_id, work_item_id, artifact_kind,
                    level, ordinal, content_json, content_hash,
                    processing_run_id, created_at_us
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid_to_blob(artifact_id),
                    uuid_to_blob(item.scope_id),
                    uuid_to_blob(work_item_id),
                    item.stage.value,
                    item.level,
                    item.ordinal,
                    content_json,
                    content_hash,
                    uuid_to_blob(processing_run_id),
                    now_us,
                ),
            )
            for kind, output_ordinal, input_ordinal in evidence_rows:
                connection.execute(
                    """
                    INSERT INTO research_synthesis_output_evidence (
                        artifact_id, work_item_id, output_kind,
                        output_ordinal, input_ordinal
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        uuid_to_blob(artifact_id),
                        uuid_to_blob(work_item_id),
                        kind,
                        output_ordinal,
                        input_ordinal,
                    ),
                )
            for (
                kind,
                output_ordinal,
                source_artifact_id,
            ) in source_evidence_rows:
                connection.execute(
                    """
                    INSERT INTO research_synthesis_output_source_evidence (
                        artifact_id,
                        output_kind,
                        output_ordinal,
                        source_analysis_artifact_id
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        uuid_to_blob(artifact_id),
                        kind,
                        output_ordinal,
                        uuid_to_blob(source_artifact_id),
                    ),
                )

            connection.execute(
                """
                UPDATE research_synthesis_work_items
                SET state = 'completed', updated_at_us = ?
                WHERE work_item_id = ? AND state = 'pending'
                """,
                (now_us, uuid_to_blob(work_item_id)),
            )
            connection.execute(
                """
                UPDATE processing_runs
                SET finished_at_us = ?, status = 'succeeded', error_detail = NULL
                WHERE processing_run_id = ? AND status = 'running'
                """,
                (now_us, uuid_to_blob(processing_run_id)),
            )
            artifact_row = connection.execute(
                "SELECT * FROM research_synthesis_artifacts WHERE artifact_id = ?",
                (uuid_to_blob(artifact_id),),
            ).fetchone()
            assert artifact_row is not None
            return _synthesis_artifact_from_row(artifact_row)

    def get_synthesis_artifact(
        self,
        artifact_id: uuid.UUID,
    ) -> ResearchSynthesisArtifactRecord:
        row = self.database.connection.execute(
            "SELECT * FROM research_synthesis_artifacts WHERE artifact_id = ?",
            (uuid_to_blob(artifact_id),),
        ).fetchone()
        if row is None:
            raise ResearchNotFoundError(
                f"Research synthesis artifact {artifact_id} does not exist."
            )
        return _synthesis_artifact_from_row(row)

    def synthesis_artifact_for_work_item(
        self,
        work_item_id: uuid.UUID,
    ) -> ResearchSynthesisArtifactRecord | None:
        row = self.database.connection.execute(
            "SELECT * FROM research_synthesis_artifacts WHERE work_item_id = ?",
            (uuid_to_blob(work_item_id),),
        ).fetchone()
        return None if row is None else _synthesis_artifact_from_row(row)

    def synthesis_evidence_for_artifact(
        self,
        artifact_id: uuid.UUID,
    ) -> tuple[ResearchSynthesisEvidenceRecord, ...]:
        return self._synthesis_evidence_for_artifact(
            self.database.connection,
            artifact_id,
        )

    @staticmethod
    def _synthesis_evidence_for_artifact(
        connection: sqlite3.Connection,
        artifact_id: uuid.UUID,
    ) -> tuple[ResearchSynthesisEvidenceRecord, ...]:
        rows = connection.execute(
            """
            SELECT * FROM research_synthesis_output_evidence
            WHERE artifact_id = ?
            ORDER BY output_kind, output_ordinal, input_ordinal
            """,
            (uuid_to_blob(artifact_id),),
        ).fetchall()
        return tuple(_synthesis_evidence_from_row(row) for row in rows)

    def source_analysis_artifact_ids_for_synthesis_artifact(
        self,
        artifact_id: uuid.UUID,
    ) -> tuple[uuid.UUID, ...]:
        return self._source_analysis_artifact_ids_for_synthesis_artifact(
            self.database.connection,
            artifact_id,
        )

    @staticmethod
    def _source_analysis_artifact_ids_for_synthesis_artifact(
        connection: sqlite3.Connection,
        artifact_id: uuid.UUID,
    ) -> tuple[uuid.UUID, ...]:
        exists = connection.execute(
            "SELECT 1 FROM research_synthesis_artifacts WHERE artifact_id = ?",
            (uuid_to_blob(artifact_id),),
        ).fetchone()
        if exists is None:
            raise ResearchNotFoundError(
                f"Research synthesis artifact {artifact_id} does not exist."
            )
        rows = connection.execute(
            """
            WITH RECURSIVE research_graph(artifact_id) AS (
                SELECT ?
                UNION
                SELECT input.research_synthesis_artifact_id
                FROM research_graph AS graph
                JOIN research_synthesis_artifacts AS artifact
                  ON artifact.artifact_id = graph.artifact_id
                JOIN research_synthesis_work_inputs AS input
                  ON input.work_item_id = artifact.work_item_id
                WHERE input.input_kind = 'research_synthesis_artifact'
                  AND input.research_synthesis_artifact_id IS NOT NULL
            )
            SELECT DISTINCT input.source_analysis_artifact_id
            FROM research_graph AS graph
            JOIN research_synthesis_artifacts AS artifact
              ON artifact.artifact_id = graph.artifact_id
            JOIN research_synthesis_work_inputs AS input
              ON input.work_item_id = artifact.work_item_id
            WHERE input.input_kind = 'source_analysis_artifact'
              AND input.source_analysis_artifact_id IS NOT NULL
            ORDER BY input.source_analysis_artifact_id
            """,
            (uuid_to_blob(artifact_id),),
        ).fetchall()
        return tuple(uuid_from_blob(bytes(row[0])) for row in rows)

    def _precise_source_analysis_artifact_ids_for_synthesis_output(
        self,
        artifact_id: uuid.UUID,
        *,
        output_kind: str,
        output_ordinal: int,
    ) -> tuple[uuid.UUID, ...] | None:
        if (
            output_kind not in {"finding", "contradiction"}
            or output_ordinal < 0
        ):
            raise ResearchStateError(
                "Research synthesis output identity is invalid."
            )

        rows = self.database.connection.execute(
            """
            SELECT source_analysis_artifact_id
            FROM research_synthesis_output_source_evidence
            WHERE artifact_id = ?
              AND output_kind = ?
              AND output_ordinal = ?
            ORDER BY source_analysis_artifact_id
            """,
            (
                uuid_to_blob(artifact_id),
                output_kind,
                output_ordinal,
            ),
        ).fetchall()

        if not rows:
            return None

        return tuple(
            uuid_from_blob(
                bytes(row["source_analysis_artifact_id"])
            )
            for row in rows
        )

    def precise_source_analysis_artifact_ids_for_synthesis_output(
        self,
        artifact_id: uuid.UUID,
        *,
        output_kind: str,
        output_ordinal: int,
    ) -> tuple[uuid.UUID, ...]:
        resolved = (
            self._precise_source_analysis_artifact_ids_for_synthesis_output(
                artifact_id,
                output_kind=output_kind,
                output_ordinal=output_ordinal,
            )
        )

        if resolved is None:
            raise ResearchStateError(
                "Research synthesis output has no precise terminal "
                "SourceAnalysis backlinks. Restart synthesis from "
                "SourceAnalysis leaves instead of nesting this "
                "legacy artifact."
            )

        return resolved

    def source_analysis_artifact_ids_for_synthesis_output(
        self,
        artifact_id: uuid.UUID,
        *,
        output_kind: str,
        output_ordinal: int,
    ) -> tuple[uuid.UUID, ...]:
        precise = (
            self._precise_source_analysis_artifact_ids_for_synthesis_output(
                artifact_id,
                output_kind=output_kind,
                output_ordinal=output_ordinal,
            )
        )

        if precise is not None:
            return precise

        artifact = self.get_synthesis_artifact(artifact_id)

        run_row = self.database.connection.execute(
            """
            SELECT input_snapshot_json
            FROM processing_runs
            WHERE processing_run_id = ?
            """,
            (uuid_to_blob(artifact.processing_run_id),),
        ).fetchone()

        if run_row is None:
            raise ResearchStateError(
                "Research synthesis artifact lost its ProcessingRun."
            )

        try:
            run_snapshot = json.loads(
                str(run_row["input_snapshot_json"])
            )
        except json.JSONDecodeError as exc:
            raise ResearchStateError(
                "Research synthesis ProcessingRun snapshot "
                "contains invalid JSON."
            ) from exc

        if (
            isinstance(run_snapshot, Mapping)
            and run_snapshot.get(
                "precise_provenance_policy_id"
            )
            == PRECISE_SYNTHESIS_PROVENANCE_POLICY_ID
        ):
            raise ResearchStateError(
                "A precise-provenance Research synthesis artifact "
                "lost its terminal SourceAnalysis backlinks."
            )

        # Explicit legacy fallback for pre-v29 / pre-policy artifacts.
        evidence = tuple(
            item
            for item in self.synthesis_evidence_for_artifact(
                artifact_id
            )
            if item.output_kind == output_kind
            and item.output_ordinal == output_ordinal
        )

        if not evidence:
            raise ResearchStateError(
                "Research synthesis output has no durable "
                "evidence backlinks."
            )

        inputs = {
            input_item.ordinal: input_item
            for input_item
            in self.synthesis_inputs_for_work_item(
                artifact.work_item_id
            )
        }

        resolved: set[uuid.UUID] = set()

        for link in evidence:
            input_item = inputs.get(link.input_ordinal)

            if input_item is None:
                raise ResearchStateError(
                    "Research synthesis evidence points "
                    "at a missing input."
                )

            if (
                input_item.input_kind
                is ResearchSynthesisInputKind.SOURCE_ANALYSIS_ARTIFACT
            ):
                assert (
                    input_item.source_analysis_artifact_id
                    is not None
                )
                resolved.add(
                    input_item.source_analysis_artifact_id
                )
            else:
                assert (
                    input_item.research_synthesis_artifact_id
                    is not None
                )
                resolved.update(
                    self.source_analysis_artifact_ids_for_synthesis_artifact(
                        input_item.research_synthesis_artifact_id
                    )
                )

        return tuple(
            sorted(
                resolved,
                key=lambda item: item.bytes,
            )
        )


    def get_result_for_scope(
        self,
        scope_id: uuid.UUID,
    ) -> ResearchResultRecord | None:
        row = self.database.connection.execute(
            "SELECT * FROM research_results WHERE scope_id = ?",
            (uuid_to_blob(scope_id),),
        ).fetchone()
        return None if row is None else _research_result_from_row(row)

    def finalize_result_fenced(
        self,
        scope_id: uuid.UUID,
        *,
        parent_job_id: uuid.UUID,
        lease_token: bytes,
        semantic_content: Mapping[str, Any],
        final_artifact_id: uuid.UUID | None,
        synthesis_pipeline_version: str,
    ) -> ResearchResultRecord:
        normalized_pipeline = _required_text(
            synthesis_pipeline_version,
            "ResearchResult synthesis_pipeline_version",
        )
        reserved = {"coverage", "problem_sources", "snapshot_commit_seq"}
        if reserved.intersection(semantic_content):
            raise ResearchStateError(
                "ResearchResult semantic content contains Core-owned coverage fields."
            )

        with self.database.write_transaction() as connection:
            self._require_running_fence(
                connection,
                parent_job_id,
                lease_token,
            )
            existing = connection.execute(
                "SELECT * FROM research_results WHERE scope_id = ?",
                (uuid_to_blob(scope_id),),
            ).fetchone()
            if existing is not None:
                record = _research_result_from_row(existing)
                if (
                    record.final_artifact_id != final_artifact_id
                    or record.synthesis_pipeline_version != normalized_pipeline
                ):
                    raise ResearchStateError(
                        "Existing ResearchResult disagrees with finalization identity."
                    )
                return record

            scope_row = connection.execute(
                "SELECT * FROM research_scopes WHERE scope_id = ?",
                (uuid_to_blob(scope_id),),
            ).fetchone()
            if scope_row is None:
                raise ResearchNotFoundError(str(scope_id))
            if bytes(scope_row["job_id"]) != parent_job_id.bytes:
                raise ResearchStateError(
                    "ResearchResult scope belongs to another parent job."
                )
            if str(scope_row["state"]) != ResearchScopeState.RUNNING.value:
                raise ResearchStateError(
                    "ResearchResult can only finalize a running scope."
                )

            now_us = utc_now_us()
            self._recompute_scope_counters(
                connection,
                scope_id=scope_id,
                now_us=now_us,
            )
            refreshed = connection.execute(
                "SELECT * FROM research_scopes WHERE scope_id = ?",
                (uuid_to_blob(scope_id),),
            ).fetchone()
            assert refreshed is not None
            scope = _scope_from_row(refreshed)
            eligible_count = scope.candidate_total - scope.excluded_count
            if scope.processed_count != eligible_count:
                raise ResearchStateError(
                    "ResearchResult cannot finalize while eligible source work is nonterminal."
                )

            expected_source_artifacts = set(
                self._successful_source_analysis_final_artifact_ids(
                    connection,
                    scope_id,
                )
            )
            if scope.successful_count > 0:
                if final_artifact_id is None:
                    raise ResearchStateError(
                        "Successful Research requires a FINAL synthesis artifact."
                    )
                final_row = connection.execute(
                    """
                    SELECT artifact.artifact_kind, work.state
                    FROM research_synthesis_artifacts AS artifact
                    JOIN research_synthesis_work_items AS work
                      ON work.work_item_id = artifact.work_item_id
                    WHERE artifact.artifact_id = ?
                      AND artifact.scope_id = ?
                    """,
                    (
                        uuid_to_blob(final_artifact_id),
                        uuid_to_blob(scope_id),
                    ),
                ).fetchone()
                if (
                    final_row is None
                    or str(final_row["artifact_kind"])
                    != ResearchSynthesisStage.FINAL.value
                    or str(final_row["state"])
                    != ResearchSynthesisWorkState.COMPLETED.value
                ):
                    raise ResearchStateError(
                        "ResearchResult final artifact is absent, cross-scope, "
                        "or not a completed FINAL synthesis artifact."
                    )
                actual_source_artifacts = set(
                    self._source_analysis_artifact_ids_for_synthesis_artifact(
                        connection,
                        final_artifact_id,
                    )
                )
                if actual_source_artifacts != expected_source_artifacts:
                    raise ResearchStateError(
                        "ResearchResult FINAL artifact does not cover exactly every "
                        "SUCCESSFUL SourceAnalysis FINAL artifact."
                    )
            elif final_artifact_id is not None:
                raise ResearchStateError(
                    "Research with no successful source evidence must not invent "
                    "a semantic FINAL artifact."
                )

            problem_rows = connection.execute(
                """
                SELECT rc.ordinal, rc.source_id, rw.state
                FROM research_work_items AS rw
                JOIN research_candidates AS rc ON rc.candidate_id = rw.candidate_id
                WHERE rw.scope_id = ?
                  AND rw.state IN ('failed', 'unavailable')
                ORDER BY rc.ordinal ASC, rc.source_id ASC
                """,
                (uuid_to_blob(scope_id),),
            ).fetchall()
            problems = [
                {
                    "candidate_ordinal": int(row["ordinal"]),
                    "source_id": str(uuid_from_blob(bytes(row["source_id"]))),
                    "state": str(row["state"]),
                }
                for row in problem_rows
            ]
            coverage_payload = {
                "candidate_total": scope.candidate_total,
                "processed_count": scope.processed_count,
                "successful_count": scope.successful_count,
                "irrelevant_count": scope.irrelevant_count,
                "failed_count": scope.failed_count,
                "unavailable_count": scope.unavailable_count,
                "excluded_count": scope.excluded_count,
                "eligible_count": eligible_count,
                "coverage_ratio": scope.coverage_ratio,
            }
            payload = dict(semantic_content)
            payload["coverage"] = coverage_payload
            payload["problem_sources"] = problems
            payload["snapshot_commit_seq"] = scope.snapshot_commit_seq
            content_json = _canonical_json_object(payload)
            content_hash = hashlib.sha256(
                content_json.encode("utf-8")
            ).digest()
            problems_json = _canonical_json_value(problems)
            result_id = new_uuid7()

            connection.execute(
                """
                INSERT INTO research_results (
                    result_id, scope_id, final_artifact_id,
                    content_json, content_hash, snapshot_commit_seq,
                    model_signature_id, synthesis_pipeline_version,
                    candidate_total, processed_count, successful_count,
                    irrelevant_count, failed_count, unavailable_count,
                    excluded_count, coverage_ratio, problem_sources_json,
                    created_at_us
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid_to_blob(result_id),
                    uuid_to_blob(scope_id),
                    (
                        uuid_to_blob(final_artifact_id)
                        if final_artifact_id is not None
                        else None
                    ),
                    content_json,
                    content_hash,
                    scope.snapshot_commit_seq,
                    (
                        uuid_to_blob(scope.model_signature_id)
                        if scope.model_signature_id is not None
                        else None
                    ),
                    normalized_pipeline,
                    scope.candidate_total,
                    scope.processed_count,
                    scope.successful_count,
                    scope.irrelevant_count,
                    scope.failed_count,
                    scope.unavailable_count,
                    scope.excluded_count,
                    scope.coverage_ratio,
                    problems_json,
                    now_us,
                ),
            )
            cursor = connection.execute(
                """
                UPDATE research_scopes
                SET state = 'completed', updated_at_us = ?
                WHERE scope_id = ? AND state = 'running'
                """,
                (now_us, uuid_to_blob(scope_id)),
            )
            if cursor.rowcount != 1:
                raise ResearchStateError(
                    "Research scope lost its running state during finalization."
                )
            result_row = connection.execute(
                "SELECT * FROM research_results WHERE result_id = ?",
                (uuid_to_blob(result_id),),
            ).fetchone()
            assert result_row is not None
            return _research_result_from_row(result_row)

    @staticmethod
    def _require_running_fence(
        connection: sqlite3.Connection,
        job_id: uuid.UUID,
        lease_token: bytes,
    ) -> None:
        ResearchRepository._require_live_fence(
            connection,
            job_id,
            lease_token,
        )
        row = connection.execute(
            "SELECT state FROM jobs WHERE job_id = ?",
            (uuid_to_blob(job_id),),
        ).fetchone()
        if row is None or str(row["state"]) != "running":
            raise ResearchFenceError(
                "Research semantic commit requires an actively running parent; "
                "cancel_requested is not commit-capable."
            )

    def coverage(self, scope_id: uuid.UUID) -> ResearchCoverage:
        scope = self.get_scope(scope_id)
        eligible_count = scope.candidate_total - scope.excluded_count
        return ResearchCoverage(
            candidate_total=scope.candidate_total,
            processed_count=scope.processed_count,
            successful_count=scope.successful_count,
            irrelevant_count=scope.irrelevant_count,
            failed_count=scope.failed_count,
            unavailable_count=scope.unavailable_count,
            excluded_count=scope.excluded_count,
            eligible_count=eligible_count,
            coverage_ratio=scope.coverage_ratio,
        )

    @staticmethod
    def _require_live_fence(
        connection: sqlite3.Connection,
        job_id: uuid.UUID,
        lease_token: bytes,
    ) -> None:
        row = connection.execute(
            """
            SELECT state, lease_token, lease_expires_at_us
            FROM jobs
            WHERE job_id = ?
            """,
            (uuid_to_blob(job_id),),
        ).fetchone()
        if row is None:
            raise ResearchFenceError(f"Research parent job {job_id} does not exist.")
        if str(row["state"]) not in {"running", "cancel_requested"}:
            raise ResearchFenceError(
                "Research parent does not own a live running fence."
            )
        persisted = row["lease_token"]
        expires = row["lease_expires_at_us"]
        if (
            persisted is None
            or not hmac.compare_digest(bytes(persisted), lease_token)
            or expires is None
            or int(expires) <= utc_now_us()
        ):
            raise ResearchFenceError(
                "Research parent lease is stale or mismatched."
            )

    @staticmethod
    def _select_sources_as_of(
        connection: sqlite3.Connection,
        *,
        snapshot_commit_seq: int,
        source_types: Sequence[str],
        explicit_source_ids: Sequence[uuid.UUID],
        time_start_us: int | None,
        time_end_us: int | None,
    ) -> tuple[sqlite3.Row, ...]:
        clauses = [
            "esh.valid_from_commit_seq <= ?",
            "(esh.valid_to_commit_seq IS NULL OR esh.valid_to_commit_seq > ?)",
            "esh.lifecycle_state = 'active'",
        ]
        params: list[object] = [snapshot_commit_seq, snapshot_commit_seq]

        if source_types:
            placeholders = ", ".join("?" for _ in source_types)
            clauses.append(f"s.source_type IN ({placeholders})")
            params.extend(source_types)
        if explicit_source_ids:
            placeholders = ", ".join("?" for _ in explicit_source_ids)
            clauses.append(f"s.source_id IN ({placeholders})")
            params.extend(uuid_to_blob(item) for item in explicit_source_ids)
        if time_start_us is not None:
            clauses.append("s.acquired_at_us >= ?")
            params.append(time_start_us)
        if time_end_us is not None:
            clauses.append("s.acquired_at_us <= ?")
            params.append(time_end_us)

        where = " AND ".join(clauses)
        rows = connection.execute(
            f"""
            SELECT s.source_id, s.source_type, s.acquired_at_us, s.content_sha256
            FROM sources AS s
            JOIN entity_state_history AS esh
              ON esh.entity_id = s.source_id
            WHERE {where}
            ORDER BY s.acquired_at_us ASC, s.source_id ASC
            """,
            tuple(params),
        ).fetchall()
        return tuple(rows)

    @staticmethod
    def _recompute_scope_counters(
        connection: sqlite3.Connection,
        *,
        scope_id: uuid.UUID,
        now_us: int,
    ) -> None:
        candidate_row = connection.execute(
            """
            SELECT
                COUNT(*) AS candidate_total,
                SUM(CASE WHEN eligibility_state = 'excluded_duplicate' THEN 1 ELSE 0 END)
                    AS excluded_count
            FROM research_candidates AS c
            JOIN research_candidate_sets AS cs
              ON cs.candidate_set_id = c.candidate_set_id
            WHERE cs.scope_id = ?
            """,
            (uuid_to_blob(scope_id),),
        ).fetchone()
        work_row = connection.execute(
            """
            SELECT
                SUM(CASE WHEN state != 'pending' THEN 1 ELSE 0 END) AS processed_count,
                SUM(CASE WHEN state = 'successful' THEN 1 ELSE 0 END) AS successful_count,
                SUM(CASE WHEN state = 'irrelevant' THEN 1 ELSE 0 END) AS irrelevant_count,
                SUM(CASE WHEN state = 'failed' THEN 1 ELSE 0 END) AS failed_count,
                SUM(CASE WHEN state = 'unavailable' THEN 1 ELSE 0 END) AS unavailable_count
            FROM research_work_items
            WHERE scope_id = ?
            """,
            (uuid_to_blob(scope_id),),
        ).fetchone()

        candidate_total = int(candidate_row["candidate_total"] or 0)
        excluded_count = int(candidate_row["excluded_count"] or 0)
        processed_count = int(work_row["processed_count"] or 0)
        successful_count = int(work_row["successful_count"] or 0)
        irrelevant_count = int(work_row["irrelevant_count"] or 0)
        failed_count = int(work_row["failed_count"] or 0)
        unavailable_count = int(work_row["unavailable_count"] or 0)
        eligible_count = candidate_total - excluded_count
        covered = successful_count + irrelevant_count
        coverage_ratio = covered / eligible_count if eligible_count > 0 else 0.0

        connection.execute(
            """
            UPDATE research_scopes
            SET candidate_total = ?,
                processed_count = ?,
                successful_count = ?,
                irrelevant_count = ?,
                failed_count = ?,
                unavailable_count = ?,
                excluded_count = ?,
                coverage_ratio = ?,
                updated_at_us = ?
            WHERE scope_id = ?
            """,
            (
                candidate_total,
                processed_count,
                successful_count,
                irrelevant_count,
                failed_count,
                unavailable_count,
                excluded_count,
                coverage_ratio,
                now_us,
                uuid_to_blob(scope_id),
            ),
        )
