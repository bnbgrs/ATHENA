"""Canonical persistence for hierarchical large-source analysis."""

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
from athena.source.analysis_models import (
    AnalysisInputKind,
    AnalysisStage,
    AnalysisWorkState,
    SourceAnalysisArtifact,
    SourceAnalysisRecord,
    SourceAnalysisState,
    SourceAnalysisWorkInput,
    SourceAnalysisWorkItem,
)
from athena.source.protected_semantic import (
    ANALYSIS_NEUTRAL_ARTIFACT_CONTENT_JSON,
    ANALYSIS_SEMANTIC_KIND,
    analysis_artifact_neutral_content_hash,
    analysis_neutral_question,
)
from athena.storage.database import SQLiteDatabase


class SourceAnalysisNotFoundError(LookupError):
    """Raised when an analysis or one of its durable work units is missing."""


class SourceAnalysisFenceError(RuntimeError):
    """Raised when a stale worker tries to commit semantic analysis state."""


class SourceAnalysisInvariantError(RuntimeError):
    """Raised when persistent analysis invariants would be violated."""


class SourceAnalysisRepository:
    """Persist analysis state, work graph, artifacts, and stable input references."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def get_or_create_analysis(
        self,
        *,
        job_id: uuid.UUID,
        source_id: uuid.UUID,
        representation_id: uuid.UUID,
        question: str,
        model_signature_id: uuid.UUID,
        pipeline_version: str,
        effective_context_limit: int,
        output_reserve: int,
        safety_margin: int,
        token_estimator: str,
        max_hierarchy_depth: int,
    ) -> SourceAnalysisRecord:
        normalized_question = question.strip()
        if not normalized_question:
            raise ValueError("Analysis question must not be empty.")
        with self.database.write_transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM source_analyses WHERE job_id = ?",
                (uuid_to_blob(job_id),),
            ).fetchone()
            if existing is not None:
                record = _analysis_from_row(existing)
                expected = (
                    source_id,
                    representation_id,
                    normalized_question,
                    model_signature_id,
                    pipeline_version,
                    effective_context_limit,
                    output_reserve,
                    safety_margin,
                    token_estimator,
                    max_hierarchy_depth,
                )
                actual = (
                    record.source_id,
                    record.representation_id,
                    record.question,
                    record.model_signature_id,
                    record.pipeline_version,
                    record.effective_context_limit,
                    record.output_reserve,
                    record.safety_margin,
                    record.token_estimator,
                    record.max_hierarchy_depth,
                )
                if actual != expected:
                    raise SourceAnalysisInvariantError(
                        "Existing source analysis disagrees with the pinned job configuration."
                    )
                return record

            now_us = utc_now_us()
            analysis_id = new_uuid7()
            connection.execute(
                """
                INSERT INTO source_analyses (
                    analysis_id, job_id, source_id, representation_id, question, state,
                    model_signature_id, pipeline_version, effective_context_limit,
                    output_reserve, safety_margin, token_estimator, max_hierarchy_depth,
                    total_map_units, completed_map_units, failed_map_units, coverage,
                    final_artifact_id, created_at_us, updated_at_us
                ) VALUES (?, ?, ?, ?, ?, 'running', ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 0.0,
                          NULL, ?, ?)
                """,
                (
                    uuid_to_blob(analysis_id),
                    uuid_to_blob(job_id),
                    uuid_to_blob(source_id),
                    uuid_to_blob(representation_id),
                    normalized_question,
                    uuid_to_blob(model_signature_id),
                    pipeline_version,
                    effective_context_limit,
                    output_reserve,
                    safety_margin,
                    token_estimator,
                    max_hierarchy_depth,
                    now_us,
                    now_us,
                ),
            )
            row = connection.execute(
                "SELECT * FROM source_analyses WHERE analysis_id = ?",
                (uuid_to_blob(analysis_id),),
            ).fetchone()
            assert row is not None
            return _analysis_from_row(row)

    def get_analysis(self, analysis_id: uuid.UUID) -> SourceAnalysisRecord:
        row = self.database.connection.execute(
            "SELECT * FROM source_analyses WHERE analysis_id = ?",
            (uuid_to_blob(analysis_id),),
        ).fetchone()
        if row is None:
            raise SourceAnalysisNotFoundError(f"Source analysis {analysis_id} not found.")
        return _analysis_from_row(row)

    def get_analysis_for_job(self, job_id: uuid.UUID) -> SourceAnalysisRecord | None:
        row = self.database.connection.execute(
            "SELECT * FROM source_analyses WHERE job_id = ?",
            (uuid_to_blob(job_id),),
        ).fetchone()
        return None if row is None else _analysis_from_row(row)

    def list_analyses_for_source(
        self, source_id: uuid.UUID, *, limit: int = 100
    ) -> tuple[SourceAnalysisRecord, ...]:
        if not 1 <= limit <= 1000:
            raise ValueError("Analysis list limit must be between 1 and 1000.")
        rows = self.database.connection.execute(
            """
            SELECT * FROM source_analyses
            WHERE source_id = ?
            ORDER BY created_at_us DESC, analysis_id DESC
            LIMIT ?
            """,
            (uuid_to_blob(source_id), limit),
        ).fetchall()
        return tuple(_analysis_from_row(row) for row in rows)

    def create_work_item(
        self,
        *,
        analysis_id: uuid.UUID,
        stage: AnalysisStage,
        level: int,
        ordinal: int,
        inputs: Sequence[tuple[AnalysisInputKind, uuid.UUID]],
        descriptor: Mapping[str, Any],
    ) -> SourceAnalysisWorkItem:
        """Create one idempotent work unit and immutable input refs atomically."""
        idempotency_key = _descriptor_hash(descriptor)
        with self.database.write_transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM source_analysis_work_items WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if existing is not None:
                item = _work_item_from_row(existing)
                if (
                    item.analysis_id != analysis_id
                    or item.stage is not stage
                    or item.level != level
                    or item.ordinal != ordinal
                ):
                    raise SourceAnalysisInvariantError(
                        "Analysis work idempotency key collided with a different descriptor."
                    )
                return item

            now_us = utc_now_us()
            work_item_id = new_uuid7()
            connection.execute(
                """
                INSERT INTO source_analysis_work_items (
                    work_item_id, analysis_id, stage, level, ordinal, state,
                    idempotency_key, attempt_count, created_at_us, updated_at_us
                ) VALUES (?, ?, ?, ?, ?, 'pending', ?, 0, ?, ?)
                """,
                (
                    uuid_to_blob(work_item_id),
                    uuid_to_blob(analysis_id),
                    stage.value,
                    level,
                    ordinal,
                    idempotency_key,
                    now_us,
                    now_us,
                ),
            )
            for input_ordinal, (kind, ref_id) in enumerate(inputs):
                source_anchor = uuid_to_blob(ref_id) if kind is AnalysisInputKind.SOURCE_ANCHOR else None
                artifact = uuid_to_blob(ref_id) if kind is AnalysisInputKind.ARTIFACT else None
                connection.execute(
                    """
                    INSERT INTO source_analysis_work_inputs (
                        work_item_id, ordinal, input_kind, source_anchor_id, artifact_id
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        uuid_to_blob(work_item_id),
                        input_ordinal,
                        kind.value,
                        source_anchor,
                        artifact,
                    ),
                )
            self._refresh_coverage(connection, analysis_id)
            row = connection.execute(
                "SELECT * FROM source_analysis_work_items WHERE work_item_id = ?",
                (uuid_to_blob(work_item_id),),
            ).fetchone()
            assert row is not None
            return _work_item_from_row(row)

    def get_work_item(self, work_item_id: uuid.UUID) -> SourceAnalysisWorkItem:
        row = self.database.connection.execute(
            "SELECT * FROM source_analysis_work_items WHERE work_item_id = ?",
            (uuid_to_blob(work_item_id),),
        ).fetchone()
        if row is None:
            raise SourceAnalysisNotFoundError(f"Analysis work item {work_item_id} not found.")
        return _work_item_from_row(row)

    def list_work_items(
        self,
        analysis_id: uuid.UUID,
        *,
        stage: AnalysisStage | None = None,
        state: AnalysisWorkState | None = None,
    ) -> tuple[SourceAnalysisWorkItem, ...]:
        clauses = ["analysis_id = ?"]
        params: list[object] = [uuid_to_blob(analysis_id)]
        if stage is not None:
            clauses.append("stage = ?")
            params.append(stage.value)
        if state is not None:
            clauses.append("state = ?")
            params.append(state.value)
        rows = self.database.connection.execute(
            "SELECT * FROM source_analysis_work_items WHERE "
            + " AND ".join(clauses)
            + " ORDER BY level, ordinal, work_item_id",
            tuple(params),
        ).fetchall()
        return tuple(_work_item_from_row(row) for row in rows)

    def next_pending(self, analysis_id: uuid.UUID) -> SourceAnalysisWorkItem | None:
        row = self.database.connection.execute(
            """
            SELECT * FROM source_analysis_work_items
            WHERE analysis_id = ? AND state = 'pending'
            ORDER BY CASE stage WHEN 'map' THEN 0 WHEN 'reduce' THEN 1 ELSE 2 END,
                     level, ordinal, work_item_id
            LIMIT 1
            """,
            (uuid_to_blob(analysis_id),),
        ).fetchone()
        return None if row is None else _work_item_from_row(row)

    def inputs_for_work_item(
        self, work_item_id: uuid.UUID
    ) -> tuple[SourceAnalysisWorkInput, ...]:
        rows = self.database.connection.execute(
            """
            SELECT * FROM source_analysis_work_inputs
            WHERE work_item_id = ? ORDER BY ordinal
            """,
            (uuid_to_blob(work_item_id),),
        ).fetchall()
        return tuple(_work_input_from_row(row) for row in rows)

    def begin_attempt(
        self,
        work_item_id: uuid.UUID,
        *,
        job_id: uuid.UUID,
        lease_token: bytes,
    ) -> SourceAnalysisWorkItem:
        with self.database.write_transaction() as connection:
            self._require_live_fence(connection, job_id, lease_token)
            cursor = connection.execute(
                """
                UPDATE source_analysis_work_items
                SET attempt_count = attempt_count + 1, updated_at_us = ?
                WHERE work_item_id = ? AND state = 'pending'
                """,
                (utc_now_us(), uuid_to_blob(work_item_id)),
            )
            if cursor.rowcount != 1:
                raise SourceAnalysisInvariantError(
                    "Analysis work item is no longer pending at attempt start."
                )
            row = connection.execute(
                "SELECT * FROM source_analysis_work_items WHERE work_item_id = ?",
                (uuid_to_blob(work_item_id),),
            ).fetchone()
            assert row is not None
            return _work_item_from_row(row)

    def split_work_item(
        self,
        work_item_id: uuid.UUID,
        *,
        job_id: uuid.UUID,
        lease_token: bytes,
        children: Sequence[
            tuple[AnalysisStage, int, int, Sequence[tuple[AnalysisInputKind, uuid.UUID]], Mapping[str, Any]]
        ],
    ) -> tuple[SourceAnalysisWorkItem, ...]:
        """Supersede one pending work unit with deterministic child work units."""
        if not children:
            raise ValueError("Analysis split requires at least one convergent child.")
        with self.database.write_transaction() as connection:
            self._require_live_fence(connection, job_id, lease_token)
            parent_row = connection.execute(
                "SELECT * FROM source_analysis_work_items WHERE work_item_id = ?",
                (uuid_to_blob(work_item_id),),
            ).fetchone()
            if parent_row is None:
                raise SourceAnalysisNotFoundError(f"Analysis work item {work_item_id} not found.")
            parent = _work_item_from_row(parent_row)
            if parent.state is AnalysisWorkState.SPLIT:
                return self._children_by_descriptor(connection, children)
            if parent.state is not AnalysisWorkState.PENDING:
                raise SourceAnalysisInvariantError("Only pending analysis work can be split.")

            now_us = utc_now_us()
            created: list[SourceAnalysisWorkItem] = []
            for child_stage, child_level, child_ordinal, inputs, descriptor in children:
                key = _descriptor_hash(descriptor)
                existing = connection.execute(
                    "SELECT * FROM source_analysis_work_items WHERE idempotency_key = ?",
                    (key,),
                ).fetchone()
                if existing is not None:
                    created.append(_work_item_from_row(existing))
                    continue
                child_id = new_uuid7()
                connection.execute(
                    """
                    INSERT INTO source_analysis_work_items (
                        work_item_id, analysis_id, stage, level, ordinal, state,
                        idempotency_key, attempt_count, created_at_us, updated_at_us
                    ) VALUES (?, ?, ?, ?, ?, 'pending', ?, 0, ?, ?)
                    """,
                    (
                        uuid_to_blob(child_id),
                        uuid_to_blob(parent.analysis_id),
                        child_stage.value,
                        child_level,
                        child_ordinal,
                        key,
                        now_us,
                        now_us,
                    ),
                )
                for input_ordinal, (kind, ref_id) in enumerate(inputs):
                    connection.execute(
                        """
                        INSERT INTO source_analysis_work_inputs (
                            work_item_id, ordinal, input_kind, source_anchor_id, artifact_id
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            uuid_to_blob(child_id),
                            input_ordinal,
                            kind.value,
                            uuid_to_blob(ref_id)
                            if kind is AnalysisInputKind.SOURCE_ANCHOR
                            else None,
                            uuid_to_blob(ref_id)
                            if kind is AnalysisInputKind.ARTIFACT
                            else None,
                        ),
                    )
                row = connection.execute(
                    "SELECT * FROM source_analysis_work_items WHERE work_item_id = ?",
                    (uuid_to_blob(child_id),),
                ).fetchone()
                assert row is not None
                created.append(_work_item_from_row(row))
            connection.execute(
                """
                UPDATE source_analysis_work_items
                SET state = 'split', updated_at_us = ?
                WHERE work_item_id = ?
                """,
                (now_us, uuid_to_blob(work_item_id)),
            )
            self._refresh_coverage(connection, parent.analysis_id)
            return tuple(created)

    @staticmethod
    def _children_by_descriptor(
        connection: sqlite3.Connection,
        children: Sequence[
            tuple[AnalysisStage, int, int, Sequence[tuple[AnalysisInputKind, uuid.UUID]], Mapping[str, Any]]
        ],
    ) -> tuple[SourceAnalysisWorkItem, ...]:
        result: list[SourceAnalysisWorkItem] = []
        for _stage, _level, _ordinal, _inputs, descriptor in children:
            row = connection.execute(
                "SELECT * FROM source_analysis_work_items WHERE idempotency_key = ?",
                (_descriptor_hash(descriptor),),
            ).fetchone()
            if row is None:
                raise SourceAnalysisInvariantError("Previously split work lost a deterministic child.")
            result.append(_work_item_from_row(row))
        return tuple(result)

    def commit_artifact(
        self,
        *,
        work_item_id: uuid.UUID,
        job_id: uuid.UUID,
        lease_token: bytes,
        content: Mapping[str, Any],
        processing_run_id: uuid.UUID,
    ) -> SourceAnalysisArtifact:
        """Fence and atomically commit one validated semantic artifact plus run status."""
        content_json = _canonical_json(content)
        content_hash = hashlib.sha256(content_json.encode("utf-8")).digest()
        with self.database.write_transaction() as connection:
            self._require_live_fence(connection, job_id, lease_token)
            row = connection.execute(
                "SELECT * FROM source_analysis_work_items WHERE work_item_id = ?",
                (uuid_to_blob(work_item_id),),
            ).fetchone()
            if row is None:
                raise SourceAnalysisNotFoundError(f"Analysis work item {work_item_id} not found.")
            item = _work_item_from_row(row)

            protected = connection.execute(
                """
                SELECT 1
                FROM source_protected_semantic_payloads
                WHERE semantic_kind = ?
                  AND entity_id = ?
                LIMIT 1
                """,
                (
                    ANALYSIS_SEMANTIC_KIND,
                    uuid_to_blob(item.analysis_id),
                ),
            ).fetchone()

            if protected is not None:
                raise SourceAnalysisInvariantError(
                    "Protected SourceAnalysis cannot accept new semantic artifacts."
                )

            existing = connection.execute(
                "SELECT * FROM source_analysis_artifacts WHERE work_item_id = ?",
                (uuid_to_blob(work_item_id),),
            ).fetchone()
            if existing is not None:
                artifact = _artifact_from_row(existing)
                if artifact.content_hash != content_hash:
                    raise SourceAnalysisInvariantError(
                        "Completed analysis work cannot be overwritten with different content."
                    )
                return artifact
            if item.state is not AnalysisWorkState.PENDING:
                raise SourceAnalysisInvariantError("Only pending analysis work can commit an artifact.")

            run = connection.execute(
                "SELECT status, model_signature_id FROM processing_runs WHERE processing_run_id = ?",
                (uuid_to_blob(processing_run_id),),
            ).fetchone()
            if run is None or str(run["status"]) != "running":
                raise SourceAnalysisInvariantError("Artifact ProcessingRun is not running.")
            analysis = connection.execute(
                "SELECT model_signature_id FROM source_analyses WHERE analysis_id = ?",
                (uuid_to_blob(item.analysis_id),),
            ).fetchone()
            if analysis is None:
                raise SourceAnalysisNotFoundError(f"Source analysis {item.analysis_id} not found.")
            if bytes(run["model_signature_id"]) != bytes(analysis["model_signature_id"]):
                raise SourceAnalysisInvariantError(
                    "Artifact ProcessingRun does not use the analysis's pinned ModelSignature."
                )

            now_us = utc_now_us()
            artifact_id = new_uuid7()
            connection.execute(
                """
                INSERT INTO source_analysis_artifacts (
                    artifact_id, analysis_id, work_item_id, artifact_kind, level, ordinal,
                    content_json, content_hash, processing_run_id, created_at_us
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid_to_blob(artifact_id),
                    uuid_to_blob(item.analysis_id),
                    uuid_to_blob(item.work_item_id),
                    item.stage.value,
                    item.level,
                    item.ordinal,
                    content_json,
                    content_hash,
                    uuid_to_blob(processing_run_id),
                    now_us,
                ),
            )
            connection.execute(
                """
                UPDATE source_analysis_work_items
                SET state = 'completed', updated_at_us = ?
                WHERE work_item_id = ? AND state = 'pending'
                """,
                (now_us, uuid_to_blob(item.work_item_id)),
            )
            connection.execute(
                """
                UPDATE processing_runs
                SET finished_at_us = ?, status = 'succeeded', error_detail = NULL
                WHERE processing_run_id = ? AND status = 'running'
                """,
                (now_us, uuid_to_blob(processing_run_id)),
            )
            self._refresh_coverage(connection, item.analysis_id)
            if item.stage is AnalysisStage.FINAL:
                self._complete_if_proven(connection, item.analysis_id, artifact_id, now_us)
            artifact_row = connection.execute(
                "SELECT * FROM source_analysis_artifacts WHERE artifact_id = ?",
                (uuid_to_blob(artifact_id),),
            ).fetchone()
            assert artifact_row is not None
            return _artifact_from_row(artifact_row)

    def mark_partial(
        self,
        analysis_id: uuid.UUID,
        *,
        job_id: uuid.UUID,
        lease_token: bytes,
    ) -> SourceAnalysisRecord:
        with self.database.write_transaction() as connection:
            self._require_live_fence(connection, job_id, lease_token)
            self._refresh_coverage(connection, analysis_id)
            connection.execute(
                """
                UPDATE source_analyses
                SET state = CASE WHEN state = 'completed' THEN state ELSE 'partial' END,
                    updated_at_us = ?
                WHERE analysis_id = ?
                """,
                (utc_now_us(), uuid_to_blob(analysis_id)),
            )
            row = connection.execute(
                "SELECT * FROM source_analyses WHERE analysis_id = ?",
                (uuid_to_blob(analysis_id),),
            ).fetchone()
            if row is None:
                raise SourceAnalysisNotFoundError(f"Source analysis {analysis_id} not found.")
            return _analysis_from_row(row)

    def get_artifact(self, artifact_id: uuid.UUID) -> SourceAnalysisArtifact:
        row = self.database.connection.execute(
            "SELECT * FROM source_analysis_artifacts WHERE artifact_id = ?",
            (uuid_to_blob(artifact_id),),
        ).fetchone()
        if row is None:
            raise SourceAnalysisNotFoundError(f"Analysis artifact {artifact_id} not found.")
        return _artifact_from_row(row)

    def artifact_for_work_item(
        self, work_item_id: uuid.UUID
    ) -> SourceAnalysisArtifact | None:
        row = self.database.connection.execute(
            "SELECT * FROM source_analysis_artifacts WHERE work_item_id = ?",
            (uuid_to_blob(work_item_id),),
        ).fetchone()
        return None if row is None else _artifact_from_row(row)

    def list_artifacts(
        self,
        analysis_id: uuid.UUID,
        *,
        kind: AnalysisStage | None = None,
    ) -> tuple[SourceAnalysisArtifact, ...]:
        if kind is None:
            rows = self.database.connection.execute(
                """
                SELECT * FROM source_analysis_artifacts
                WHERE analysis_id = ? ORDER BY level, ordinal, artifact_id
                """,
                (uuid_to_blob(analysis_id),),
            ).fetchall()
        else:
            rows = self.database.connection.execute(
                """
                SELECT * FROM source_analysis_artifacts
                WHERE analysis_id = ? AND artifact_kind = ?
                ORDER BY level, ordinal, artifact_id
                """,
                (uuid_to_blob(analysis_id), kind.value),
            ).fetchall()
        return tuple(_artifact_from_row(row) for row in rows)

    def leaf_artifacts(self, analysis_id: uuid.UUID) -> tuple[SourceAnalysisArtifact, ...]:
        """Return completed artifacts that are not inputs to another completed/split work item."""
        rows = self.database.connection.execute(
            """
            SELECT a.*
            FROM source_analysis_artifacts AS a
            WHERE a.analysis_id = ?
              AND a.artifact_kind != 'final'
              AND NOT EXISTS (
                  SELECT 1
                  FROM source_analysis_work_inputs AS i
                  JOIN source_analysis_work_items AS w ON w.work_item_id = i.work_item_id
                  WHERE i.artifact_id = a.artifact_id
                    AND w.analysis_id = a.analysis_id
                    AND w.stage = 'reduce'
                    AND w.state IN ('pending', 'completed')
              )
            ORDER BY a.level, a.ordinal, a.artifact_id
            """,
            (uuid_to_blob(analysis_id),),
        ).fetchall()
        return tuple(_artifact_from_row(row) for row in rows)

    def source_anchor_ids_for_artifact(self, artifact_id: uuid.UUID) -> tuple[uuid.UUID, ...]:
        """Traverse durable work-input backlinks to original SourceAnchors."""
        return self._source_anchor_ids_for_artifact(self.database.connection, artifact_id)

    @staticmethod
    def _source_anchor_ids_for_artifact(
        connection: sqlite3.Connection, artifact_id: uuid.UUID
    ) -> tuple[uuid.UUID, ...]:
        rows = connection.execute(
            """
            WITH RECURSIVE artifact_graph(artifact_id) AS (
                SELECT ?
                UNION
                SELECT i.artifact_id
                FROM source_analysis_work_inputs AS i
                JOIN source_analysis_artifacts AS parent_artifact
                  ON parent_artifact.work_item_id = i.work_item_id
                JOIN artifact_graph AS g ON parent_artifact.artifact_id = g.artifact_id
                WHERE i.input_kind = 'artifact' AND i.artifact_id IS NOT NULL
            )
            SELECT DISTINCT i.source_anchor_id
            FROM artifact_graph AS g
            JOIN source_analysis_artifacts AS a ON a.artifact_id = g.artifact_id
            JOIN source_analysis_work_inputs AS i ON i.work_item_id = a.work_item_id
            WHERE i.input_kind = 'source_anchor' AND i.source_anchor_id IS NOT NULL
            ORDER BY i.source_anchor_id
            """,
            (uuid_to_blob(artifact_id),),
        ).fetchall()
        return tuple(uuid_from_blob(bytes(row[0])) for row in rows)

    @staticmethod
    def _require_live_fence(
        connection: sqlite3.Connection,
        job_id: uuid.UUID,
        lease_token: bytes,
    ) -> None:
        row = connection.execute(
            """
            SELECT state, lease_token, lease_expires_at_us
            FROM jobs WHERE job_id = ?
            """,
            (uuid_to_blob(job_id),),
        ).fetchone()
        now_us = utc_now_us()
        if row is None:
            raise SourceAnalysisFenceError("Analysis job no longer exists.")
        stored = row["lease_token"]
        expires = row["lease_expires_at_us"]
        if (
            str(row["state"]) not in {"running", "cancel_requested"}
            or stored is None
            or not hmac.compare_digest(bytes(stored), lease_token)
            or expires is None
            or int(expires) <= now_us
        ):
            raise SourceAnalysisFenceError("Analysis semantic commit rejected by stale worker fence.")

    @staticmethod
    def _refresh_coverage(connection: sqlite3.Connection, analysis_id: uuid.UUID) -> None:
        counts = connection.execute(
            """
            SELECT
                SUM(CASE WHEN state != 'split' THEN 1 ELSE 0 END) AS total,
                SUM(CASE WHEN state = 'completed' THEN 1 ELSE 0 END) AS completed,
                SUM(CASE WHEN state = 'failed' THEN 1 ELSE 0 END) AS failed
            FROM source_analysis_work_items
            WHERE analysis_id = ? AND stage = 'map'
            """,
            (uuid_to_blob(analysis_id),),
        ).fetchone()
        total = int(counts["total"] or 0)
        completed = int(counts["completed"] or 0)
        failed = int(counts["failed"] or 0)
        coverage = 0.0 if total == 0 else completed / total
        connection.execute(
            """
            UPDATE source_analyses
            SET total_map_units = ?, completed_map_units = ?, failed_map_units = ?,
                coverage = ?, updated_at_us = ?
            WHERE analysis_id = ?
            """,
            (total, completed, failed, coverage, utc_now_us(), uuid_to_blob(analysis_id)),
        )

    @staticmethod
    def _complete_if_proven(
        connection: sqlite3.Connection,
        analysis_id: uuid.UUID,
        final_artifact_id: uuid.UUID,
        now_us: int,
    ) -> None:
        analysis = connection.execute(
            "SELECT * FROM source_analyses WHERE analysis_id = ?",
            (uuid_to_blob(analysis_id),),
        ).fetchone()
        if analysis is None:
            raise SourceAnalysisNotFoundError(f"Source analysis {analysis_id} not found.")
        pending = int(
            connection.execute(
                """
                SELECT COUNT(*) FROM source_analysis_work_items
                WHERE analysis_id = ? AND state = 'pending'
                """,
                (uuid_to_blob(analysis_id),),
            ).fetchone()[0]
        )
        total = int(analysis["total_map_units"])
        completed = int(analysis["completed_map_units"])
        failed = int(analysis["failed_map_units"])

        expected_rows = connection.execute(
            """
            SELECT DISTINCT i.source_anchor_id
            FROM source_analysis_work_items AS w
            JOIN source_analysis_work_inputs AS i ON i.work_item_id = w.work_item_id
            WHERE w.analysis_id = ?
              AND w.stage = 'map'
              AND w.state = 'completed'
              AND i.input_kind = 'source_anchor'
              AND i.source_anchor_id IS NOT NULL
            """,
            (uuid_to_blob(analysis_id),),
        ).fetchall()
        expected_anchors = {uuid_from_blob(bytes(row[0])) for row in expected_rows}
        final_anchors = set(
            SourceAnalysisRepository._source_anchor_ids_for_artifact(
                connection, final_artifact_id
            )
        )
        final_row = connection.execute(
            """
            SELECT analysis_id, artifact_kind
            FROM source_analysis_artifacts
            WHERE artifact_id = ?
            """,
            (uuid_to_blob(final_artifact_id),),
        ).fetchone()
        final_matches_analysis = (
            final_row is not None
            and bytes(final_row["analysis_id"]) == uuid_to_blob(analysis_id)
            and str(final_row["artifact_kind"]) == AnalysisStage.FINAL.value
        )
        provenance_complete = bool(expected_anchors) and final_anchors == expected_anchors

        if (
            total <= 0
            or completed != total
            or failed != 0
            or pending != 0
            or not final_matches_analysis
            or not provenance_complete
        ):
            connection.execute(
                """
                UPDATE source_analyses
                SET state = 'partial', final_artifact_id = NULL, updated_at_us = ?
                WHERE analysis_id = ?
                """,
                (now_us, uuid_to_blob(analysis_id)),
            )
            return
        connection.execute(
            """
            UPDATE source_analyses
            SET state = 'completed', coverage = 1.0, final_artifact_id = ?, updated_at_us = ?
            WHERE analysis_id = ?
            """,
            (uuid_to_blob(final_artifact_id), now_us, uuid_to_blob(analysis_id)),
        )


def _descriptor_hash(descriptor: Mapping[str, Any]) -> bytes:
    return hashlib.sha256(_canonical_json(descriptor).encode("utf-8")).digest()


def _canonical_json(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("Analysis payload must be finite canonical JSON.") from exc


def _analysis_from_row(row: sqlite3.Row) -> SourceAnalysisRecord:
    analysis_id = uuid_from_blob(bytes(row["analysis_id"]))
    question = str(row["question"])

    if question == analysis_neutral_question(analysis_id):
        raise SourceAnalysisInvariantError(
            "Protected SourceAnalysis semantics are unavailable through the public reader."
        )

    return SourceAnalysisRecord(
        analysis_id=analysis_id,
        job_id=uuid_from_blob(bytes(row["job_id"])),
        source_id=uuid_from_blob(bytes(row["source_id"])),
        representation_id=uuid_from_blob(bytes(row["representation_id"])),
        question=question,
        state=SourceAnalysisState(str(row["state"])),
        model_signature_id=uuid_from_blob(bytes(row["model_signature_id"])),
        pipeline_version=str(row["pipeline_version"]),
        effective_context_limit=int(row["effective_context_limit"]),
        output_reserve=int(row["output_reserve"]),
        safety_margin=int(row["safety_margin"]),
        token_estimator=str(row["token_estimator"]),
        max_hierarchy_depth=int(row["max_hierarchy_depth"]),
        total_map_units=int(row["total_map_units"]),
        completed_map_units=int(row["completed_map_units"]),
        failed_map_units=int(row["failed_map_units"]),
        coverage=float(row["coverage"]),
        final_artifact_id=(
            None
            if row["final_artifact_id"] is None
            else uuid_from_blob(bytes(row["final_artifact_id"]))
        ),
        created_at_us=int(row["created_at_us"]),
        updated_at_us=int(row["updated_at_us"]),
    )


def _work_item_from_row(row: sqlite3.Row) -> SourceAnalysisWorkItem:
    return SourceAnalysisWorkItem(
        work_item_id=uuid_from_blob(bytes(row["work_item_id"])),
        analysis_id=uuid_from_blob(bytes(row["analysis_id"])),
        stage=AnalysisStage(str(row["stage"])),
        level=int(row["level"]),
        ordinal=int(row["ordinal"]),
        state=AnalysisWorkState(str(row["state"])),
        idempotency_key=bytes(row["idempotency_key"]),
        attempt_count=int(row["attempt_count"]),
        created_at_us=int(row["created_at_us"]),
        updated_at_us=int(row["updated_at_us"]),
    )


def _artifact_from_row(row: sqlite3.Row) -> SourceAnalysisArtifact:
    artifact_id = uuid_from_blob(bytes(row["artifact_id"]))
    content_json = str(row["content_json"])
    content_hash = bytes(row["content_hash"])

    if (
        content_json == ANALYSIS_NEUTRAL_ARTIFACT_CONTENT_JSON
        and content_hash == analysis_artifact_neutral_content_hash(artifact_id)
    ):
        raise SourceAnalysisInvariantError(
            "Protected SourceAnalysis artifact semantics are unavailable "
            "through the public reader."
        )

    return SourceAnalysisArtifact(
        artifact_id=artifact_id,
        analysis_id=uuid_from_blob(bytes(row["analysis_id"])),
        work_item_id=uuid_from_blob(bytes(row["work_item_id"])),
        artifact_kind=AnalysisStage(str(row["artifact_kind"])),
        level=int(row["level"]),
        ordinal=int(row["ordinal"]),
        content_json=content_json,
        content_hash=content_hash,
        processing_run_id=uuid_from_blob(bytes(row["processing_run_id"])),
        created_at_us=int(row["created_at_us"]),
    )


def _work_input_from_row(row: sqlite3.Row) -> SourceAnalysisWorkInput:
    return SourceAnalysisWorkInput(
        work_item_id=uuid_from_blob(bytes(row["work_item_id"])),
        ordinal=int(row["ordinal"]),
        input_kind=AnalysisInputKind(str(row["input_kind"])),
        source_anchor_id=(
            None
            if row["source_anchor_id"] is None
            else uuid_from_blob(bytes(row["source_anchor_id"]))
        ),
        artifact_id=(
            None if row["artifact_id"] is None else uuid_from_blob(bytes(row["artifact_id"]))
        ),
    )
