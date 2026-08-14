"""Transactional persistence for Exhaustive Research scope and frozen candidates."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from collections.abc import Sequence

from athena.common.ids import new_uuid7, uuid_from_blob, uuid_to_blob
from athena.common.time import utc_now_us
from athena.research.models import (
    ResearchCandidateEligibility,
    ResearchCandidateRecord,
    ResearchCandidateSetRecord,
    ResearchCandidateSetState,
    ResearchCoverage,
    ResearchMode,
    ResearchScopeRecord,
    ResearchScopeState,
    ResearchWorkItemRecord,
    ResearchWorkState,
)
from athena.storage.database import SQLiteDatabase


class ResearchNotFoundError(LookupError):
    """Raised when durable Research state does not exist."""


class ResearchStateError(RuntimeError):
    """Raised when an invalid Research state transition is requested."""


class ResearchScopeUnsupportedError(ValueError):
    """Raised when foundation discovery cannot honestly honor a persisted scope."""


class ResearchSnapshotError(RuntimeError):
    """Raised when an explicit candidate cannot exist inside the pinned snapshot."""


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


def _scope_from_row(row: sqlite3.Row) -> ResearchScopeRecord:
    return ResearchScopeRecord(
        scope_id=uuid_from_blob(bytes(row["scope_id"])),
        job_id=uuid_from_blob(bytes(row["job_id"])),
        mode=ResearchMode(str(row["mode"])),
        query_text=str(row["query_text"]),
        domains_json=str(row["domains_json"]),
        project_ids_json=str(row["project_ids_json"]),
        source_types_json=str(row["source_types_json"]),
        explicit_source_ids_json=str(row["explicit_source_ids_json"]),
        time_start_us=(
            int(row["time_start_us"]) if row["time_start_us"] is not None else None
        ),
        time_end_us=(
            int(row["time_end_us"]) if row["time_end_us"] is not None else None
        ),
        internet_scope_json=(
            str(row["internet_scope_json"])
            if row["internet_scope_json"] is not None
            else None
        ),
        coverage_target=float(row["coverage_target"]),
        snapshot_commit_seq=int(row["snapshot_commit_seq"]),
        state=ResearchScopeState(str(row["state"])),
        candidate_total=int(row["candidate_total"]),
        processed_count=int(row["processed_count"]),
        successful_count=int(row["successful_count"]),
        irrelevant_count=int(row["irrelevant_count"]),
        failed_count=int(row["failed_count"]),
        unavailable_count=int(row["unavailable_count"]),
        excluded_count=int(row["excluded_count"]),
        coverage_ratio=float(row["coverage_ratio"]),
        created_at_us=int(row["created_at_us"]),
        updated_at_us=int(row["updated_at_us"]),
    )


def _candidate_set_from_row(row: sqlite3.Row) -> ResearchCandidateSetRecord:
    return ResearchCandidateSetRecord(
        candidate_set_id=uuid_from_blob(bytes(row["candidate_set_id"])),
        scope_id=uuid_from_blob(bytes(row["scope_id"])),
        snapshot_commit_seq=int(row["snapshot_commit_seq"]),
        state=ResearchCandidateSetState(str(row["state"])),
        candidate_total=int(row["candidate_total"]),
        eligible_count=int(row["eligible_count"]),
        excluded_count=int(row["excluded_count"]),
        created_at_us=int(row["created_at_us"]),
        frozen_at_us=(
            int(row["frozen_at_us"]) if row["frozen_at_us"] is not None else None
        ),
    )


def _candidate_from_row(row: sqlite3.Row) -> ResearchCandidateRecord:
    return ResearchCandidateRecord(
        candidate_id=uuid_from_blob(bytes(row["candidate_id"])),
        candidate_set_id=uuid_from_blob(bytes(row["candidate_set_id"])),
        source_id=uuid_from_blob(bytes(row["source_id"])),
        ordinal=int(row["ordinal"]),
        content_sha256=bytes(row["content_sha256"]),
        eligibility=ResearchCandidateEligibility(str(row["eligibility_state"])),
        duplicate_of_candidate_id=(
            uuid_from_blob(bytes(row["duplicate_of_candidate_id"]))
            if row["duplicate_of_candidate_id"] is not None
            else None
        ),
        created_at_us=int(row["created_at_us"]),
    )


def _work_item_from_row(row: sqlite3.Row) -> ResearchWorkItemRecord:
    return ResearchWorkItemRecord(
        work_item_id=uuid_from_blob(bytes(row["work_item_id"])),
        scope_id=uuid_from_blob(bytes(row["scope_id"])),
        candidate_id=uuid_from_blob(bytes(row["candidate_id"])),
        state=ResearchWorkState(str(row["state"])),
        idempotency_key=bytes(row["idempotency_key"]),
        source_analysis_job_id=(
            uuid_from_blob(bytes(row["source_analysis_job_id"]))
            if row["source_analysis_job_id"] is not None
            else None
        ),
        attempt_count=int(row["attempt_count"]),
        created_at_us=int(row["created_at_us"]),
        updated_at_us=int(row["updated_at_us"]),
    )


def _json_string_array(raw: str, field: str) -> tuple[str, ...]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ResearchStateError(f"{field} contains invalid JSON.") from exc
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ResearchStateError(f"{field} must be a JSON string array.")
    return tuple(value)


def _work_idempotency_key(
    *,
    scope_id: uuid.UUID,
    source_id: uuid.UUID,
    content_sha256: bytes,
) -> bytes:
    digest = hashlib.sha256()
    digest.update(b"athena.exhaustive-research.work.v1\0")
    digest.update(scope_id.bytes)
    digest.update(source_id.bytes)
    digest.update(content_sha256)
    return digest.digest()
