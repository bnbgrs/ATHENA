"""Durable persistence for hierarchical source Knowledge extraction."""

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
from athena.knowledge.source_hierarchical_models import (
    SourceExtractionInputKind,
    SourceExtractionStage,
    SourceExtractionWorkState,
    SourceHierarchicalExtractionArtifact,
    SourceHierarchicalExtractionEvidence,
    SourceHierarchicalExtractionRecord,
    SourceHierarchicalExtractionState,
    SourceHierarchicalExtractionWorkInput,
    SourceHierarchicalExtractionWorkItem,
)
from athena.source.protected_semantic import (
    EXTRACTION_ARTIFACT_SEMANTIC_KIND,
    EXTRACTION_NEUTRAL_ARTIFACT_CONTENT_JSON,
    extraction_artifact_neutral_content_hash,
)
from athena.storage.database import SQLiteDatabase


class SourceHierarchicalExtractionNotFoundError(LookupError):
    """Raised when hierarchical extraction state is missing."""


class SourceHierarchicalExtractionFenceError(RuntimeError):
    """Raised when a stale worker tries to commit extraction state."""


class SourceHierarchicalExtractionInvariantError(RuntimeError):
    """Raised when durable extraction invariants would be violated."""


class SourceHierarchicalExtractionRepository:
    """Persist extraction state, immutable evidence, work graph, and artifacts."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def get_or_create_extraction(
        self,
        *,
        job_id: uuid.UUID,
        analysis_id: uuid.UUID,
        final_artifact_id: uuid.UUID,
        model_signature_id: uuid.UUID,
        pipeline_version: str,
        effective_context_limit: int,
        output_reserve: int,
        safety_margin: int,
        token_estimator: str,
        prompt_template_id: str,
        prompt_template_version: str,
        max_hierarchy_depth: int,
        evidence: Sequence[tuple[int, uuid.UUID, bytes]],
    ) -> SourceHierarchicalExtractionRecord:
        if not evidence:
            raise ValueError("Hierarchical extraction requires at least one evidence anchor.")
        expected_sequences = list(range(1, len(evidence) + 1))
        actual_sequences = [item[0] for item in evidence]
        if actual_sequences != expected_sequences:
            raise ValueError("Hierarchical extraction evidence must be contiguous and ordered.")
        if len({item[1] for item in evidence}) != len(evidence):
            raise ValueError("Hierarchical extraction evidence contains duplicate SourceAnchors.")
        if any(len(item[2]) != 32 for item in evidence):
            raise ValueError("Hierarchical extraction evidence hash must be SHA-256.")

        with self.database.write_transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM source_extractions WHERE job_id = ?",
                (uuid_to_blob(job_id),),
            ).fetchone()
            if existing is not None:
                record = _extraction_from_row(existing)
                expected = (
                    analysis_id,
                    final_artifact_id,
                    model_signature_id,
                    pipeline_version,
                    effective_context_limit,
                    output_reserve,
                    safety_margin,
                    token_estimator,
                    prompt_template_id,
                    prompt_template_version,
                    max_hierarchy_depth,
                )
                actual = (
                    record.analysis_id,
                    record.final_artifact_id,
                    record.model_signature_id,
                    record.pipeline_version,
                    record.effective_context_limit,
                    record.output_reserve,
                    record.safety_margin,
                    record.token_estimator,
                    record.prompt_template_id,
                    record.prompt_template_version,
                    record.max_hierarchy_depth,
                )
                if actual != expected:
                    raise SourceHierarchicalExtractionInvariantError(
                        "Existing hierarchical extraction disagrees with pinned job configuration."
                    )
                self._validate_evidence_rows(connection, record.extraction_id, evidence)
                return record

            analysis = connection.execute(
                "SELECT state, final_artifact_id FROM source_analyses WHERE analysis_id = ?",
                (uuid_to_blob(analysis_id),),
            ).fetchone()
            if (
                analysis is None
                or str(analysis["state"]) != "completed"
                or analysis["final_artifact_id"] is None
                or uuid_from_blob(analysis["final_artifact_id"]) != final_artifact_id
            ):
                raise SourceHierarchicalExtractionInvariantError(
                    "Hierarchical extraction requires the pinned completed analysis Final Artifact."
                )

            now_us = utc_now_us()
            extraction_id = new_uuid7()
            connection.execute(
                """
                INSERT INTO source_extractions (
                    extraction_id, job_id, analysis_id, final_artifact_id, state,
                    model_signature_id, pipeline_version, effective_context_limit,
                    output_reserve, safety_margin, token_estimator, prompt_template_id,
                    prompt_template_version, max_hierarchy_depth, total_batches,
                    completed_batches, failed_batches, final_work_artifact_id,
                    created_at_us, updated_at_us
                ) VALUES (?, ?, ?, ?, 'running', ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, NULL, ?, ?)
                """,
                (
                    uuid_to_blob(extraction_id),
                    uuid_to_blob(job_id),
                    uuid_to_blob(analysis_id),
                    uuid_to_blob(final_artifact_id),
                    uuid_to_blob(model_signature_id),
                    pipeline_version,
                    effective_context_limit,
                    output_reserve,
                    safety_margin,
                    token_estimator,
                    prompt_template_id,
                    prompt_template_version,
                    max_hierarchy_depth,
                    now_us,
                    now_us,
                ),
            )
            for sequence_no, anchor_id, quoted_hash in evidence:
                connection.execute(
                    """
                    INSERT INTO source_extraction_evidence (
                        extraction_id, sequence_no, source_anchor_id, quoted_hash
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        uuid_to_blob(extraction_id),
                        sequence_no,
                        uuid_to_blob(anchor_id),
                        quoted_hash,
                    ),
                )
            row = connection.execute(
                "SELECT * FROM source_extractions WHERE extraction_id = ?",
                (uuid_to_blob(extraction_id),),
            ).fetchone()
            assert row is not None
            return _extraction_from_row(row)

    def get_extraction(self, extraction_id: uuid.UUID) -> SourceHierarchicalExtractionRecord:
        row = self.database.connection.execute(
            "SELECT * FROM source_extractions WHERE extraction_id = ?",
            (uuid_to_blob(extraction_id),),
        ).fetchone()
        if row is None:
            raise SourceHierarchicalExtractionNotFoundError(
                f"Hierarchical source extraction {extraction_id} not found."
            )
        return _extraction_from_row(row)

    def get_extraction_for_job(
        self, job_id: uuid.UUID
    ) -> SourceHierarchicalExtractionRecord | None:
        row = self.database.connection.execute(
            "SELECT * FROM source_extractions WHERE job_id = ?",
            (uuid_to_blob(job_id),),
        ).fetchone()
        return None if row is None else _extraction_from_row(row)

    def evidence(
        self, extraction_id: uuid.UUID
    ) -> tuple[SourceHierarchicalExtractionEvidence, ...]:
        rows = self.database.connection.execute(
            """
            SELECT * FROM source_extraction_evidence
            WHERE extraction_id = ?
            ORDER BY sequence_no
            """,
            (uuid_to_blob(extraction_id),),
        ).fetchall()
        return tuple(_evidence_from_row(row) for row in rows)

    def create_work_item(
        self,
        *,
        extraction_id: uuid.UUID,
        stage: SourceExtractionStage,
        level: int,
        ordinal: int,
        inputs: Sequence[tuple[SourceExtractionInputKind, uuid.UUID]],
        descriptor: Mapping[str, Any],
    ) -> SourceHierarchicalExtractionWorkItem:
        if level < 0 or ordinal < 0:
            raise ValueError("Extraction work level/ordinal must not be negative.")
        if not inputs and stage is not SourceExtractionStage.FINAL:
            raise ValueError("Non-final extraction work requires immutable inputs.")
        idempotency_key = _descriptor_hash(descriptor)
        with self.database.write_transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM source_extraction_work_items WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if existing is not None:
                item = _work_item_from_row(existing)
                if (
                    item.extraction_id != extraction_id
                    or item.stage is not stage
                    or item.level != level
                    or item.ordinal != ordinal
                ):
                    raise SourceHierarchicalExtractionInvariantError(
                        "Extraction work idempotency descriptor collided with different identity."
                    )
                self._validate_inputs(connection, item.work_item_id, inputs)
                return item

            duplicate_slot = connection.execute(
                """
                SELECT * FROM source_extraction_work_items
                WHERE extraction_id = ? AND stage = ? AND level = ? AND ordinal = ?
                """,
                (uuid_to_blob(extraction_id), stage.value, level, ordinal),
            ).fetchone()
            if duplicate_slot is not None:
                raise SourceHierarchicalExtractionInvariantError(
                    "Extraction work slot already exists with another idempotency descriptor."
                )
            if connection.execute(
                "SELECT 1 FROM source_extractions WHERE extraction_id = ?",
                (uuid_to_blob(extraction_id),),
            ).fetchone() is None:
                raise SourceHierarchicalExtractionNotFoundError(
                    f"Hierarchical source extraction {extraction_id} not found."
                )

            now_us = utc_now_us()
            work_item_id = new_uuid7()
            connection.execute(
                """
                INSERT INTO source_extraction_work_items (
                    work_item_id, extraction_id, stage, level, ordinal, state,
                    idempotency_key, attempt_count, created_at_us, updated_at_us
                ) VALUES (?, ?, ?, ?, ?, 'pending', ?, 0, ?, ?)
                """,
                (
                    uuid_to_blob(work_item_id),
                    uuid_to_blob(extraction_id),
                    stage.value,
                    level,
                    ordinal,
                    idempotency_key,
                    now_us,
                    now_us,
                ),
            )
            for input_ordinal, (kind, ref_id) in enumerate(inputs):
                self._insert_input(connection, work_item_id, input_ordinal, kind, ref_id)
            if stage is SourceExtractionStage.BATCH:
                connection.execute(
                    """
                    UPDATE source_extractions
                    SET total_batches = total_batches + 1, updated_at_us = ?
                    WHERE extraction_id = ?
                    """,
                    (now_us, uuid_to_blob(extraction_id)),
                )
            row = connection.execute(
                "SELECT * FROM source_extraction_work_items WHERE work_item_id = ?",
                (uuid_to_blob(work_item_id),),
            ).fetchone()
            assert row is not None
            return _work_item_from_row(row)

    def get_work_item(
        self, work_item_id: uuid.UUID
    ) -> SourceHierarchicalExtractionWorkItem:
        row = self.database.connection.execute(
            "SELECT * FROM source_extraction_work_items WHERE work_item_id = ?",
            (uuid_to_blob(work_item_id),),
        ).fetchone()
        if row is None:
            raise SourceHierarchicalExtractionNotFoundError(
                f"Hierarchical extraction work item {work_item_id} not found."
            )
        return _work_item_from_row(row)

    def list_work_items(
        self,
        extraction_id: uuid.UUID,
        *,
        stage: SourceExtractionStage | None = None,
    ) -> tuple[SourceHierarchicalExtractionWorkItem, ...]:
        if stage is None:
            rows = self.database.connection.execute(
                """
                SELECT * FROM source_extraction_work_items
                WHERE extraction_id = ?
                ORDER BY level, ordinal, work_item_id
                """,
                (uuid_to_blob(extraction_id),),
            ).fetchall()
        else:
            rows = self.database.connection.execute(
                """
                SELECT * FROM source_extraction_work_items
                WHERE extraction_id = ? AND stage = ?
                ORDER BY level, ordinal, work_item_id
                """,
                (uuid_to_blob(extraction_id), stage.value),
            ).fetchall()
        return tuple(_work_item_from_row(row) for row in rows)

    def next_pending(
        self, extraction_id: uuid.UUID
    ) -> SourceHierarchicalExtractionWorkItem | None:
        row = self.database.connection.execute(
            """
            SELECT * FROM source_extraction_work_items
            WHERE extraction_id = ? AND state = 'pending'
            ORDER BY
                CASE stage WHEN 'batch' THEN 0 WHEN 'merge' THEN 1 WHEN 'audit' THEN 2 ELSE 3 END,
                level, ordinal, work_item_id
            LIMIT 1
            """,
            (uuid_to_blob(extraction_id),),
        ).fetchone()
        return None if row is None else _work_item_from_row(row)

    def inputs_for_work_item(
        self, work_item_id: uuid.UUID
    ) -> tuple[SourceHierarchicalExtractionWorkInput, ...]:
        rows = self.database.connection.execute(
            """
            SELECT * FROM source_extraction_work_inputs
            WHERE work_item_id = ?
            ORDER BY ordinal
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
    ) -> SourceHierarchicalExtractionWorkItem:
        with self.database.write_transaction() as connection:
            self._require_live_fence(connection, job_id, lease_token)
            cursor = connection.execute(
                """
                UPDATE source_extraction_work_items
                SET attempt_count = attempt_count + 1, updated_at_us = ?
                WHERE work_item_id = ? AND state = 'pending'
                """,
                (utc_now_us(), uuid_to_blob(work_item_id)),
            )
            if cursor.rowcount != 1:
                raise SourceHierarchicalExtractionInvariantError(
                    "Only pending hierarchical extraction work can begin an attempt."
                )
            row = connection.execute(
                "SELECT * FROM source_extraction_work_items WHERE work_item_id = ?",
                (uuid_to_blob(work_item_id),),
            ).fetchone()
            assert row is not None
            return _work_item_from_row(row)

    def commit_artifact(
        self,
        *,
        work_item_id: uuid.UUID,
        job_id: uuid.UUID,
        lease_token: bytes,
        content: Mapping[str, Any],
        processing_run_id: uuid.UUID,
    ) -> SourceHierarchicalExtractionArtifact:
        """Fence and atomically commit one validated intermediate semantic artifact."""
        content_json = _canonical_json(content)
        content_hash = hashlib.sha256(content_json.encode("utf-8")).digest()
        with self.database.write_transaction() as connection:
            self._require_live_fence(connection, job_id, lease_token)
            row = connection.execute(
                "SELECT * FROM source_extraction_work_items WHERE work_item_id = ?",
                (uuid_to_blob(work_item_id),),
            ).fetchone()
            if row is None:
                raise SourceHierarchicalExtractionNotFoundError(
                    f"Hierarchical extraction work item {work_item_id} not found."
                )
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
                    EXTRACTION_ARTIFACT_SEMANTIC_KIND,
                    uuid_to_blob(item.extraction_id),
                ),
            ).fetchone()

            if protected is not None:
                raise SourceHierarchicalExtractionInvariantError(
                    "Protected SourceExtraction cannot accept new semantic artifacts."
                )

            existing = connection.execute(
                "SELECT * FROM source_extraction_artifacts WHERE work_item_id = ?",
                (uuid_to_blob(work_item_id),),
            ).fetchone()
            if existing is not None:
                artifact = _artifact_from_row(existing)
                if artifact.content_hash != content_hash:
                    raise SourceHierarchicalExtractionInvariantError(
                        "Completed extraction work cannot be overwritten with different content."
                    )
                return artifact
            if item.state is not SourceExtractionWorkState.PENDING:
                raise SourceHierarchicalExtractionInvariantError(
                    "Only pending hierarchical extraction work can commit an artifact."
                )

            run = connection.execute(
                "SELECT status, model_signature_id FROM processing_runs WHERE processing_run_id = ?",
                (uuid_to_blob(processing_run_id),),
            ).fetchone()
            if run is None or str(run["status"]) != "running":
                raise SourceHierarchicalExtractionInvariantError(
                    "Extraction artifact ProcessingRun is not running."
                )
            extraction = connection.execute(
                "SELECT model_signature_id FROM source_extractions WHERE extraction_id = ?",
                (uuid_to_blob(item.extraction_id),),
            ).fetchone()
            if extraction is None:
                raise SourceHierarchicalExtractionNotFoundError(
                    f"Hierarchical source extraction {item.extraction_id} not found."
                )
            if run["model_signature_id"] is None or bytes(run["model_signature_id"]) != bytes(
                extraction["model_signature_id"]
            ):
                raise SourceHierarchicalExtractionInvariantError(
                    "Extraction artifact ProcessingRun does not use the pinned ModelSignature."
                )

            now_us = utc_now_us()
            artifact_id = new_uuid7()
            connection.execute(
                """
                INSERT INTO source_extraction_artifacts (
                    artifact_id, extraction_id, work_item_id, artifact_kind, level, ordinal,
                    content_json, content_hash, processing_run_id, created_at_us
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid_to_blob(artifact_id),
                    uuid_to_blob(item.extraction_id),
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
                UPDATE source_extraction_work_items
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
            if item.stage is SourceExtractionStage.BATCH:
                connection.execute(
                    """
                    UPDATE source_extractions
                    SET completed_batches = completed_batches + 1,
                        state = CASE WHEN state = 'completed' THEN state ELSE 'partial' END,
                        updated_at_us = ?
                    WHERE extraction_id = ?
                    """,
                    (now_us, uuid_to_blob(item.extraction_id)),
                )
            else:
                connection.execute(
                    """
                    UPDATE source_extractions
                    SET state = CASE WHEN state = 'completed' THEN state ELSE 'partial' END,
                        updated_at_us = ?
                    WHERE extraction_id = ?
                    """,
                    (now_us, uuid_to_blob(item.extraction_id)),
                )
            artifact_row = connection.execute(
                "SELECT * FROM source_extraction_artifacts WHERE artifact_id = ?",
                (uuid_to_blob(artifact_id),),
            ).fetchone()
            assert artifact_row is not None
            return _artifact_from_row(artifact_row)

    def get_artifact(
        self, artifact_id: uuid.UUID
    ) -> SourceHierarchicalExtractionArtifact:
        row = self.database.connection.execute(
            "SELECT * FROM source_extraction_artifacts WHERE artifact_id = ?",
            (uuid_to_blob(artifact_id),),
        ).fetchone()
        if row is None:
            raise SourceHierarchicalExtractionNotFoundError(
                f"Hierarchical extraction artifact {artifact_id} not found."
            )
        return _artifact_from_row(row)

    def artifact_for_work_item(
        self, work_item_id: uuid.UUID
    ) -> SourceHierarchicalExtractionArtifact | None:
        row = self.database.connection.execute(
            "SELECT * FROM source_extraction_artifacts WHERE work_item_id = ?",
            (uuid_to_blob(work_item_id),),
        ).fetchone()
        return None if row is None else _artifact_from_row(row)

    def list_artifacts(
        self,
        extraction_id: uuid.UUID,
        *,
        artifact_kind: SourceExtractionStage | None = None,
    ) -> tuple[SourceHierarchicalExtractionArtifact, ...]:
        if artifact_kind is None:
            rows = self.database.connection.execute(
                """
                SELECT * FROM source_extraction_artifacts
                WHERE extraction_id = ?
                ORDER BY level, ordinal, artifact_id
                """,
                (uuid_to_blob(extraction_id),),
            ).fetchall()
        else:
            rows = self.database.connection.execute(
                """
                SELECT * FROM source_extraction_artifacts
                WHERE extraction_id = ? AND artifact_kind = ?
                ORDER BY level, ordinal, artifact_id
                """,
                (uuid_to_blob(extraction_id), artifact_kind.value),
            ).fetchall()
        return tuple(_artifact_from_row(row) for row in rows)

    def leaf_proposal_artifacts(
        self, extraction_id: uuid.UUID
    ) -> tuple[SourceHierarchicalExtractionArtifact, ...]:
        """Return batch/merge proposal artifacts not consumed by a later merge."""
        rows = self.database.connection.execute(
            """
            SELECT a.*
            FROM source_extraction_artifacts AS a
            WHERE a.extraction_id = ?
              AND a.artifact_kind IN ('batch', 'merge')
              AND NOT EXISTS (
                  SELECT 1
                  FROM source_extraction_work_inputs AS i
                  JOIN source_extraction_work_items AS w ON w.work_item_id = i.work_item_id
                  WHERE i.artifact_id = a.artifact_id
                    AND w.stage = 'merge'
                    AND w.state = 'completed'
              )
            ORDER BY a.level, a.ordinal, a.artifact_id
            """,
            (uuid_to_blob(extraction_id),),
        ).fetchall()
        return tuple(_artifact_from_row(row) for row in rows)

    def mark_completed(
        self,
        extraction_id: uuid.UUID,
        *,
        final_work_artifact_id: uuid.UUID,
        job_id: uuid.UUID,
        lease_token: bytes,
    ) -> SourceHierarchicalExtractionRecord:
        """Mark extraction complete only after a valid final work artifact is durably present."""
        with self.database.write_transaction() as connection:
            self._require_live_fence(connection, job_id, lease_token)
            final = connection.execute(
                """
                SELECT artifact_kind, extraction_id
                FROM source_extraction_artifacts WHERE artifact_id = ?
                """,
                (uuid_to_blob(final_work_artifact_id),),
            ).fetchone()
            if (
                final is None
                or str(final["artifact_kind"]) != SourceExtractionStage.FINAL.value
                or uuid_from_blob(final["extraction_id"]) != extraction_id
            ):
                raise SourceHierarchicalExtractionInvariantError(
                    "Extraction completion requires its own durable Final artifact."
                )
            counts = connection.execute(
                """
                SELECT total_batches, completed_batches, failed_batches
                FROM source_extractions WHERE extraction_id = ?
                """,
                (uuid_to_blob(extraction_id),),
            ).fetchone()
            if counts is None:
                raise SourceHierarchicalExtractionNotFoundError(
                    f"Hierarchical source extraction {extraction_id} not found."
                )
            if (
                int(counts["total_batches"]) <= 0
                or int(counts["completed_batches"]) != int(counts["total_batches"])
                or int(counts["failed_batches"]) != 0
            ):
                raise SourceHierarchicalExtractionInvariantError(
                    "Extraction cannot complete before every planned evidence batch completed."
                )
            pending = connection.execute(
                """
                SELECT COUNT(*) AS count FROM source_extraction_work_items
                WHERE extraction_id = ? AND state = 'pending'
                """,
                (uuid_to_blob(extraction_id),),
            ).fetchone()
            assert pending is not None
            if int(pending["count"]) != 0:
                raise SourceHierarchicalExtractionInvariantError(
                    "Extraction cannot complete while durable work remains pending."
                )
            now_us = utc_now_us()
            connection.execute(
                """
                UPDATE source_extractions
                SET state = 'completed', final_work_artifact_id = ?, updated_at_us = ?
                WHERE extraction_id = ?
                """,
                (uuid_to_blob(final_work_artifact_id), now_us, uuid_to_blob(extraction_id)),
            )
            row = connection.execute(
                "SELECT * FROM source_extractions WHERE extraction_id = ?",
                (uuid_to_blob(extraction_id),),
            ).fetchone()
            assert row is not None
            return _extraction_from_row(row)

    @staticmethod
    def _validate_evidence_rows(
        connection: sqlite3.Connection,
        extraction_id: uuid.UUID,
        evidence: Sequence[tuple[int, uuid.UUID, bytes]],
    ) -> None:
        rows = connection.execute(
            """
            SELECT sequence_no, source_anchor_id, quoted_hash
            FROM source_extraction_evidence
            WHERE extraction_id = ? ORDER BY sequence_no
            """,
            (uuid_to_blob(extraction_id),),
        ).fetchall()
        actual = [
            (int(row["sequence_no"]), uuid_from_blob(row["source_anchor_id"]), bytes(row["quoted_hash"]))
            for row in rows
        ]
        if actual != list(evidence):
            raise SourceHierarchicalExtractionInvariantError(
                "Existing hierarchical extraction evidence changed from its frozen global slots."
            )

    @staticmethod
    def _validate_inputs(
        connection: sqlite3.Connection,
        work_item_id: uuid.UUID,
        inputs: Sequence[tuple[SourceExtractionInputKind, uuid.UUID]],
    ) -> None:
        rows = connection.execute(
            """
            SELECT input_kind, source_anchor_id, artifact_id
            FROM source_extraction_work_inputs WHERE work_item_id = ? ORDER BY ordinal
            """,
            (uuid_to_blob(work_item_id),),
        ).fetchall()
        actual: list[tuple[SourceExtractionInputKind, uuid.UUID]] = []
        for row in rows:
            kind = SourceExtractionInputKind(str(row["input_kind"]))
            ref = row["source_anchor_id"] if kind is SourceExtractionInputKind.SOURCE_ANCHOR else row["artifact_id"]
            assert ref is not None
            actual.append((kind, uuid_from_blob(ref)))
        if actual != list(inputs):
            raise SourceHierarchicalExtractionInvariantError(
                "Existing extraction work item disagrees with immutable input references."
            )

    @staticmethod
    def _insert_input(
        connection: sqlite3.Connection,
        work_item_id: uuid.UUID,
        ordinal: int,
        kind: SourceExtractionInputKind,
        ref_id: uuid.UUID,
    ) -> None:
        connection.execute(
            """
            INSERT INTO source_extraction_work_inputs (
                work_item_id, ordinal, input_kind, source_anchor_id, artifact_id
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                uuid_to_blob(work_item_id),
                ordinal,
                kind.value,
                uuid_to_blob(ref_id) if kind is SourceExtractionInputKind.SOURCE_ANCHOR else None,
                uuid_to_blob(ref_id) if kind is SourceExtractionInputKind.ARTIFACT else None,
            ),
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
            FROM jobs WHERE job_id = ?
            """,
            (uuid_to_blob(job_id),),
        ).fetchone()
        if (
            row is None
            or str(row["state"]) not in {"running", "cancel_requested"}
            or row["lease_token"] is None
            or row["lease_expires_at_us"] is None
            or not hmac.compare_digest(bytes(row["lease_token"]), lease_token)
            or int(row["lease_expires_at_us"]) <= utc_now_us()
        ):
            raise SourceHierarchicalExtractionFenceError(
                "Hierarchical extraction commit rejected by durable job fencing."
            )


def _descriptor_hash(descriptor: Mapping[str, Any]) -> bytes:
    return hashlib.sha256(_canonical_json(descriptor).encode("utf-8")).digest()


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _extraction_from_row(row: Any) -> SourceHierarchicalExtractionRecord:
    return SourceHierarchicalExtractionRecord(
        extraction_id=uuid_from_blob(row["extraction_id"]),
        job_id=uuid_from_blob(row["job_id"]),
        analysis_id=uuid_from_blob(row["analysis_id"]),
        final_artifact_id=uuid_from_blob(row["final_artifact_id"]),
        state=SourceHierarchicalExtractionState(str(row["state"])),
        model_signature_id=uuid_from_blob(row["model_signature_id"]),
        pipeline_version=str(row["pipeline_version"]),
        effective_context_limit=int(row["effective_context_limit"]),
        output_reserve=int(row["output_reserve"]),
        safety_margin=int(row["safety_margin"]),
        token_estimator=str(row["token_estimator"]),
        prompt_template_id=str(row["prompt_template_id"]),
        prompt_template_version=str(row["prompt_template_version"]),
        max_hierarchy_depth=int(row["max_hierarchy_depth"]),
        total_batches=int(row["total_batches"]),
        completed_batches=int(row["completed_batches"]),
        failed_batches=int(row["failed_batches"]),
        final_work_artifact_id=(
            uuid_from_blob(row["final_work_artifact_id"])
            if row["final_work_artifact_id"] is not None
            else None
        ),
        created_at_us=int(row["created_at_us"]),
        updated_at_us=int(row["updated_at_us"]),
    )


def _evidence_from_row(row: Any) -> SourceHierarchicalExtractionEvidence:
    return SourceHierarchicalExtractionEvidence(
        extraction_id=uuid_from_blob(row["extraction_id"]),
        sequence_no=int(row["sequence_no"]),
        source_anchor_id=uuid_from_blob(row["source_anchor_id"]),
        quoted_hash=bytes(row["quoted_hash"]),
    )


def _work_item_from_row(row: Any) -> SourceHierarchicalExtractionWorkItem:
    return SourceHierarchicalExtractionWorkItem(
        work_item_id=uuid_from_blob(row["work_item_id"]),
        extraction_id=uuid_from_blob(row["extraction_id"]),
        stage=SourceExtractionStage(str(row["stage"])),
        level=int(row["level"]),
        ordinal=int(row["ordinal"]),
        state=SourceExtractionWorkState(str(row["state"])),
        idempotency_key=bytes(row["idempotency_key"]),
        attempt_count=int(row["attempt_count"]),
        created_at_us=int(row["created_at_us"]),
        updated_at_us=int(row["updated_at_us"]),
    )


def _artifact_from_row(row: Any) -> SourceHierarchicalExtractionArtifact:
    artifact_id = uuid_from_blob(row["artifact_id"])
    content_json = str(row["content_json"])
    content_hash = bytes(row["content_hash"])

    if (
        content_json == EXTRACTION_NEUTRAL_ARTIFACT_CONTENT_JSON
        and content_hash == extraction_artifact_neutral_content_hash(
            artifact_id
        )
    ):
        raise SourceHierarchicalExtractionInvariantError(
            "Protected SourceExtraction artifact semantics are unavailable "
            "through the public reader."
        )

    return SourceHierarchicalExtractionArtifact(
        artifact_id=artifact_id,
        extraction_id=uuid_from_blob(row["extraction_id"]),
        work_item_id=uuid_from_blob(row["work_item_id"]),
        artifact_kind=SourceExtractionStage(str(row["artifact_kind"])),
        level=int(row["level"]),
        ordinal=int(row["ordinal"]),
        content_json=content_json,
        content_hash=content_hash,
        processing_run_id=uuid_from_blob(row["processing_run_id"]),
        created_at_us=int(row["created_at_us"]),
    )


def _work_input_from_row(row: Any) -> SourceHierarchicalExtractionWorkInput:
    return SourceHierarchicalExtractionWorkInput(
        work_item_id=uuid_from_blob(row["work_item_id"]),
        ordinal=int(row["ordinal"]),
        input_kind=SourceExtractionInputKind(str(row["input_kind"])),
        source_anchor_id=(
            uuid_from_blob(row["source_anchor_id"])
            if row["source_anchor_id"] is not None
            else None
        ),
        artifact_id=(
            uuid_from_blob(row["artifact_id"]) if row["artifact_id"] is not None else None
        ),
    )
