from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest

from athena.common.ids import uuid_to_blob
from athena.common.time import utc_now_us
from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.knowledge.source_extraction import (
    SourceExtractionError,
    SourceExtractionSnapshotNotFoundError,
)
from athena.model.domain import ModelChatMessage, ModelInfo
from athena.security.models import Argon2idParameters
from athena.source.protected_semantic import (
    EXTRACTION_SNAPSHOT_NEUTRAL_EVIDENCE_JSON,
    EXTRACTION_SNAPSHOT_NEUTRAL_PROPOSALS_JSON,
    EXTRACTION_SNAPSHOT_SEMANTIC_KIND,
    SourceProtectedSemanticIntegrityError,
    SourceProtectedSemanticNotFoundError,
    SourceProtectedSemanticRepository,
    decode_source_extraction_snapshot_semantics,
)

_TEST_KDF = Argon2idParameters(
    iterations=1,
    lanes=1,
    memory_cost_kib=8 * 1024,
    length=32,
)


@dataclass
class _FakeAnalysisProvider:
    context_capacity: int = 5000
    quantization: str = "Q4"

    @property
    def provider_id(self) -> str:
        return "fake"

    def discover_models(self) -> tuple[ModelInfo, ...]:
        return (
            ModelInfo(
                provider="fake",
                backend_model_id="fake-primary",
                display_name="Fake Primary",
                model_type="llm",
                context_capacity=self.context_capacity,
                quantization=self.quantization,
                loaded=True,
                vision=False,
                trained_for_tool_use=False,
            ),
        )

    def generate_structured(
        self,
        *,
        model_id: str,
        messages: Sequence[ModelChatMessage],
        schema_id: str,
        json_schema: Mapping[str, object],
        max_output_tokens: int | None = None,
    ) -> Mapping[str, object]:
        del messages, json_schema, max_output_tokens
        assert model_id == "fake-primary"

        if "map" in schema_id:
            return {
                "relevant": True,
                "summary": "Relevant snapshot fixture.",
                "findings": ["Snapshot fixture finding."],
                "contradictions": [],
                "uncertainty": "",
            }

        return {
            "summary": "Snapshot fixture synthesis.",
            "findings": ["Snapshot fixture finding."],
            "contradictions": [],
            "uncertainty": "",
        }

    def stream_chat(
        self,
        *,
        model_id: str,
        messages: Sequence[ModelChatMessage],
    ) -> Iterator[str]:
        del model_id, messages
        yield "unused"


@pytest.fixture
def app(tmp_path: Path) -> Iterator[AthenaApplication]:
    instance = AthenaApplication(
        AthenaSettings(local_root=tmp_path / "runtime")
    )
    instance.start()
    instance.source_analysis_service.provider = _FakeAnalysisProvider()

    try:
        yield instance
    finally:
        instance.stop()


def _scope(
    app: AthenaApplication,
    password: bytes,
):
    app.protected_content.initialize_password(
        password,
        parameters=_TEST_KDF,
    )
    scope = app.protected_content.create_scope(
        password,
        neutral_label="extraction-snapshot-semantic-test",
    )
    app.protected_content.unlock_scope(
        scope.protection_scope_id,
        password,
    )
    return scope


def _writer(
    app: AthenaApplication,
    scope_id: uuid.UUID,
    calls: list[bytes] | None = None,
):
    def write(
        connection: sqlite3.Connection,
        plaintext: bytes,
    ) -> uuid.UUID:
        if calls is not None:
            calls.append(plaintext)

        record = app.protected_content.prepare_payload(
            scope_id,
            plaintext,
        )
        app.protection_repository.insert_payload_in_transaction(
            connection,
            record,
        )
        return record.protected_payload_id

    return write


def _prepare_source(
    app: AthenaApplication,
    tmp_path: Path,
    *,
    name: str,
):
    text = (
        f"ATHENA_EXTRACTION_SNAPSHOT_SOURCE_{name} "
        + ("durable snapshot source payload " * 220)
    )
    path = tmp_path / f"{name}.txt"
    path.write_text(text, encoding="utf-8", newline="")

    source = app.sources.capture_file(path).source
    representation = app.source_text.build(
        source.source_id
    ).result.representation
    chunks = app.source_chunks.build_default(
        representation.representation_id
    ).chunks
    assert chunks

    return source


def _run_analysis(
    app: AthenaApplication,
    source_id: uuid.UUID,
    *,
    question: str,
    worker: str,
):
    job = app.source_analysis.enqueue(
        source_id,
        question=question,
        requested_model_id="fake-primary",
        context_limit=4000,
        output_reserve=400,
        safety_margin=100,
        max_hierarchy_depth=12,
    )
    result = app.source_analysis.run_to_completion(
        job.job_id,
        worker_id=worker,
    )

    assert result.done is True
    assert result.analysis is not None
    assert result.analysis.final_artifact_id is not None
    return result.analysis


def _prepare_analysis(
    app: AthenaApplication,
    tmp_path: Path,
    *,
    name: str,
):
    source = _prepare_source(
        app,
        tmp_path,
        name=name,
    )
    analysis = _run_analysis(
        app,
        source.source_id,
        question=f"Extract frozen snapshot semantics for {name}.",
        worker=f"extraction-snapshot-analysis-{name}",
    )
    return source, analysis


def _insert_snapshot(
    app: AthenaApplication,
    analysis,
    *,
    canary: str,
):
    assert analysis.final_artifact_id is not None

    final_row = app.database.connection.execute(
        """
        SELECT processing_run_id
        FROM source_analysis_artifacts
        WHERE artifact_id = ?
        """,
        (uuid_to_blob(analysis.final_artifact_id),),
    ).fetchone()
    assert final_row is not None
    processing_run_id = uuid.UUID(
        bytes=bytes(final_row["processing_run_id"])
    )

    anchor_ids = (
        app.source_analysis_repository
        .source_anchor_ids_for_artifact(
            analysis.final_artifact_id
        )
    )
    assert anchor_ids

    evidence_items = []
    for sequence_no, anchor_id in enumerate(anchor_ids, 1):
        anchor = app.source_anchors.verify(anchor_id)
        assert anchor.quoted_hash is not None
        evidence_items.append(
            {
                "sequence_no": sequence_no,
                "anchor_id": str(anchor_id),
                "quoted_hash": anchor.quoted_hash.hex(),
            }
        )

    model_json = json.dumps(
        {
            "provider": "fake",
            "backend_model_id": "fake-primary",
            "display_name": "Fake Primary",
            "model_type": "llm",
            "context_capacity": 5000,
            "quantization": "Q4",
            "loaded": True,
            "vision": False,
            "trained_for_tool_use": False,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    evidence_json = json.dumps(
        {"items": evidence_items},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    proposals_json = json.dumps(
        {
            "knowledge_units": [],
            "claims": [
                {
                    "source_sequence_no": 1,
                    "source_quote": canary,
                    "claim_kind": "factual_assertion",
                    "statement": canary,
                    "epistemic_status": "asserted",
                    "confidence": 1.0,
                }
            ],
            "relations": [],
            "merge_candidates": [],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )

    with app.database.write_transaction() as connection:
        connection.execute(
            """
            INSERT INTO source_extraction_result_snapshots (
                processing_run_id,
                analysis_id,
                final_artifact_id,
                model_json,
                evidence_json,
                proposals_json,
                created_at_us
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uuid_to_blob(processing_run_id),
                uuid_to_blob(analysis.analysis_id),
                uuid_to_blob(analysis.final_artifact_id),
                model_json,
                evidence_json,
                proposals_json,
                utc_now_us(),
            ),
        )

    return (
        processing_run_id,
        model_json,
        evidence_json,
        proposals_json,
    )


def _snapshot_row(
    app: AthenaApplication,
    processing_run_id: uuid.UUID,
):
    return app.database.connection.execute(
        """
        SELECT
            processing_run_id,
            analysis_id,
            final_artifact_id,
            model_json,
            evidence_json,
            proposals_json
        FROM source_extraction_result_snapshots
        WHERE processing_run_id = ?
        """,
        (uuid_to_blob(processing_run_id),),
    ).fetchone()


def test_extraction_snapshot_roundtrip_neutralizes_only_semantics_and_reader_fails_closed(
    app: AthenaApplication,
    tmp_path: Path,
) -> None:
    source, analysis = _prepare_analysis(
        app,
        tmp_path,
        name="roundtrip",
    )
    canary = "ATHENA_EXTRACTION_SNAPSHOT_PROPOSAL_CANARY"
    (
        processing_run_id,
        model_json,
        evidence_json,
        proposals_json,
    ) = _insert_snapshot(
        app,
        analysis,
        canary=canary,
    )

    before = app.source_extraction_snapshots.load(
        processing_run_id
    )
    assert before.proposals.claims[0].statement == canary

    scope = _scope(
        app,
        b"extraction-snapshot-roundtrip-password",
    )
    repository = SourceProtectedSemanticRepository(app.database)

    with app.database.write_transaction() as connection:
        mapping = repository.protect_analysis_extraction_snapshot_semantics(
            connection,
            source_id=source.source_id,
            analysis_id=analysis.analysis_id,
            protection_scope_id=scope.protection_scope_id,
            payload_writer=_writer(
                app,
                scope.protection_scope_id,
            ),
        )

    assert mapping.semantic_kind == EXTRACTION_SNAPSHOT_SEMANTIC_KIND
    assert mapping.entity_id == analysis.analysis_id

    public_row = _snapshot_row(
        app,
        processing_run_id,
    )
    assert public_row is not None
    assert str(public_row["model_json"]) == model_json
    assert (
        str(public_row["evidence_json"])
        == EXTRACTION_SNAPSHOT_NEUTRAL_EVIDENCE_JSON
    )
    assert (
        str(public_row["proposals_json"])
        == EXTRACTION_SNAPSHOT_NEUTRAL_PROPOSALS_JSON
    )
    assert canary not in str(public_row["proposals_json"])

    decoded = decode_source_extraction_snapshot_semantics(
        app.protected_content.load_payload(
            mapping.protected_payload_id
        )
    )
    assert decoded.analysis_id == analysis.analysis_id
    assert len(decoded.snapshots) == 1
    assert decoded.snapshots[0].processing_run_id == processing_run_id
    assert decoded.snapshots[0].final_artifact_id == analysis.final_artifact_id
    assert decoded.snapshots[0].evidence_json == evidence_json
    assert decoded.snapshots[0].proposals_json == proposals_json

    with pytest.raises(
        SourceExtractionSnapshotNotFoundError,
        match="Protected source extraction snapshot semantics",
    ):
        app.source_extraction_snapshots.load(
            processing_run_id
        )

    assert app.database.connection.execute(
        "PRAGMA integrity_check"
    ).fetchone()[0] == "ok"


def test_empty_analysis_snapshot_set_creates_durable_late_write_fence(
    app: AthenaApplication,
    tmp_path: Path,
) -> None:
    source, analysis = _prepare_analysis(
        app,
        tmp_path,
        name="empty-fence",
    )

    (
        processing_run_id,
        _model_json,
        _evidence_json,
        _proposals_json,
    ) = _insert_snapshot(
        app,
        analysis,
        canary="ATHENA_LATE_SNAPSHOT_INSERT_FIXTURE",
    )
    result = app.source_extraction_snapshots.load(
        processing_run_id
    )

    with app.database.write_transaction() as connection:
        connection.execute(
            """
            DELETE FROM source_extraction_result_snapshots
            WHERE processing_run_id = ?
            """,
            (uuid_to_blob(processing_run_id),),
        )

    assert _snapshot_row(
        app,
        processing_run_id,
    ) is None

    scope = _scope(
        app,
        b"extraction-snapshot-empty-fence-password",
    )
    repository = SourceProtectedSemanticRepository(app.database)

    with app.database.write_transaction() as connection:
        mapping = repository.protect_analysis_extraction_snapshot_semantics(
            connection,
            source_id=source.source_id,
            analysis_id=analysis.analysis_id,
            protection_scope_id=scope.protection_scope_id,
            payload_writer=_writer(
                app,
                scope.protection_scope_id,
            ),
        )

    decoded = decode_source_extraction_snapshot_semantics(
        app.protected_content.load_payload(
            mapping.protected_payload_id
        )
    )
    assert decoded.snapshots == ()

    with pytest.raises(
        SourceExtractionError,
        match="Protected SourceAnalysis cannot accept new extraction snapshots",
    ):
        app.source_extraction_snapshots.save(result)

    assert _snapshot_row(
        app,
        processing_run_id,
    ) is None


def test_extraction_snapshot_cutover_is_idempotent_without_new_ciphertext(
    app: AthenaApplication,
    tmp_path: Path,
) -> None:
    source, analysis = _prepare_analysis(
        app,
        tmp_path,
        name="idempotent",
    )
    _insert_snapshot(
        app,
        analysis,
        canary="Idempotent snapshot proposal.",
    )

    scope = _scope(
        app,
        b"extraction-snapshot-idempotent-password",
    )
    repository = SourceProtectedSemanticRepository(app.database)
    calls: list[bytes] = []
    writer = _writer(
        app,
        scope.protection_scope_id,
        calls,
    )

    with app.database.write_transaction() as connection:
        first = repository.protect_analysis_extraction_snapshot_semantics(
            connection,
            source_id=source.source_id,
            analysis_id=analysis.analysis_id,
            protection_scope_id=scope.protection_scope_id,
            payload_writer=writer,
        )

    payload_count = int(
        app.database.connection.execute(
            "SELECT COUNT(*) FROM protected_payloads"
        ).fetchone()[0]
    )
    assert len(calls) == 1

    with app.database.write_transaction() as connection:
        second = repository.protect_analysis_extraction_snapshot_semantics(
            connection,
            source_id=source.source_id,
            analysis_id=analysis.analysis_id,
            protection_scope_id=scope.protection_scope_id,
            payload_writer=writer,
        )

    assert second == first
    assert len(calls) == 1
    assert int(
        app.database.connection.execute(
            "SELECT COUNT(*) FROM protected_payloads"
        ).fetchone()[0]
    ) == payload_count


def test_extraction_snapshot_mapping_blocks_reader_even_if_public_plaintext_is_restored(
    app: AthenaApplication,
    tmp_path: Path,
) -> None:
    source, analysis = _prepare_analysis(
        app,
        tmp_path,
        name="reader-mapping",
    )
    (
        processing_run_id,
        _model_json,
        evidence_json,
        proposals_json,
    ) = _insert_snapshot(
        app,
        analysis,
        canary="ATHENA_RESTORED_PUBLIC_SNAPSHOT_CANARY",
    )

    scope = _scope(
        app,
        b"extraction-snapshot-reader-mapping-password",
    )
    repository = SourceProtectedSemanticRepository(app.database)

    with app.database.write_transaction() as connection:
        repository.protect_analysis_extraction_snapshot_semantics(
            connection,
            source_id=source.source_id,
            analysis_id=analysis.analysis_id,
            protection_scope_id=scope.protection_scope_id,
            payload_writer=_writer(
                app,
                scope.protection_scope_id,
            ),
        )

    with app.database.write_transaction() as connection:
        connection.execute(
            """
            UPDATE source_extraction_result_snapshots
            SET evidence_json = ?, proposals_json = ?
            WHERE processing_run_id = ?
            """,
            (
                evidence_json,
                proposals_json,
                uuid_to_blob(processing_run_id),
            ),
        )

    with pytest.raises(
        SourceExtractionSnapshotNotFoundError,
        match="Protected source extraction snapshot semantics",
    ):
        app.source_extraction_snapshots.load(
            processing_run_id
        )


def test_extraction_snapshot_existing_mapping_with_public_mixed_state_fails_closed(
    app: AthenaApplication,
    tmp_path: Path,
) -> None:
    source, analysis = _prepare_analysis(
        app,
        tmp_path,
        name="mixed",
    )
    (
        processing_run_id,
        _model_json,
        evidence_json,
        _proposals_json,
    ) = _insert_snapshot(
        app,
        analysis,
        canary="Mixed snapshot proposal.",
    )

    scope = _scope(
        app,
        b"extraction-snapshot-mixed-password",
    )
    repository = SourceProtectedSemanticRepository(app.database)
    calls: list[bytes] = []
    writer = _writer(
        app,
        scope.protection_scope_id,
        calls,
    )

    with app.database.write_transaction() as connection:
        repository.protect_analysis_extraction_snapshot_semantics(
            connection,
            source_id=source.source_id,
            analysis_id=analysis.analysis_id,
            protection_scope_id=scope.protection_scope_id,
            payload_writer=writer,
        )

    with app.database.write_transaction() as connection:
        connection.execute(
            """
            UPDATE source_extraction_result_snapshots
            SET evidence_json = ?
            WHERE processing_run_id = ?
            """,
            (
                evidence_json,
                uuid_to_blob(processing_run_id),
            ),
        )

    with pytest.raises(
        SourceProtectedSemanticIntegrityError,
        match="not fully neutralized",
    ):
        with app.database.write_transaction() as connection:
            repository.protect_analysis_extraction_snapshot_semantics(
                connection,
                source_id=source.source_id,
                analysis_id=analysis.analysis_id,
                protection_scope_id=scope.protection_scope_id,
                payload_writer=writer,
            )

    assert len(calls) == 1


def test_pre_neutralized_snapshot_without_mapping_fails_before_encryption(
    app: AthenaApplication,
    tmp_path: Path,
) -> None:
    source, analysis = _prepare_analysis(
        app,
        tmp_path,
        name="pre-neutral",
    )
    (
        processing_run_id,
        _model_json,
        _evidence_json,
        _proposals_json,
    ) = _insert_snapshot(
        app,
        analysis,
        canary="Pre-neutral snapshot proposal.",
    )

    with app.database.write_transaction() as connection:
        connection.execute(
            """
            UPDATE source_extraction_result_snapshots
            SET evidence_json = ?, proposals_json = ?
            WHERE processing_run_id = ?
            """,
            (
                EXTRACTION_SNAPSHOT_NEUTRAL_EVIDENCE_JSON,
                EXTRACTION_SNAPSHOT_NEUTRAL_PROPOSALS_JSON,
                uuid_to_blob(processing_run_id),
            ),
        )

    scope = _scope(
        app,
        b"extraction-snapshot-pre-neutral-password",
    )
    repository = SourceProtectedSemanticRepository(app.database)
    calls: list[bytes] = []

    with pytest.raises(
        SourceProtectedSemanticIntegrityError,
        match="neutralized without a protected mapping",
    ):
        with app.database.write_transaction() as connection:
            repository.protect_analysis_extraction_snapshot_semantics(
                connection,
                source_id=source.source_id,
                analysis_id=analysis.analysis_id,
                protection_scope_id=scope.protection_scope_id,
                payload_writer=_writer(
                    app,
                    scope.protection_scope_id,
                    calls,
                ),
            )

    assert calls == []


def test_source_snapshot_batch_rolls_back_on_second_analysis_mapping_failure(
    app: AthenaApplication,
    tmp_path: Path,
) -> None:
    source = _prepare_source(
        app,
        tmp_path,
        name="rollback",
    )
    first = _run_analysis(
        app,
        source.source_id,
        question="First snapshot rollback analysis.",
        worker="snapshot-rollback-first",
    )
    second = _run_analysis(
        app,
        source.source_id,
        question="Second snapshot rollback analysis.",
        worker="snapshot-rollback-second",
    )

    _insert_snapshot(
        app,
        first,
        canary="First rollback snapshot.",
    )
    _insert_snapshot(
        app,
        second,
        canary="Second rollback snapshot.",
    )

    ordered_ids = sorted(
        (
            first.analysis_id,
            second.analysis_id,
        ),
        key=lambda item: item.bytes,
    )
    failing_id = ordered_ids[1]

    scope = _scope(
        app,
        b"extraction-snapshot-rollback-password",
    )
    repository = SourceProtectedSemanticRepository(app.database)

    before_rows = tuple(
        tuple(row)
        for row in app.database.connection.execute(
            """
            SELECT
                s.processing_run_id,
                s.analysis_id,
                s.model_json,
                s.evidence_json,
                s.proposals_json
            FROM source_extraction_result_snapshots AS s
            JOIN source_analyses AS a
              ON a.analysis_id = s.analysis_id
            WHERE a.source_id = ?
            ORDER BY s.processing_run_id
            """,
            (uuid_to_blob(source.source_id),),
        ).fetchall()
    )
    before_payloads = int(
        app.database.connection.execute(
            "SELECT COUNT(*) FROM protected_payloads"
        ).fetchone()[0]
    )

    with app.database.write_transaction() as connection:
        connection.execute(
            f"""
            CREATE TRIGGER fail_second_snapshot_mapping
            BEFORE INSERT
            ON source_protected_semantic_payloads
            WHEN NEW.semantic_kind = '{EXTRACTION_SNAPSHOT_SEMANTIC_KIND}'
             AND hex(NEW.entity_id) = '{failing_id.hex.upper()}'
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'forced extraction snapshot mapping failure'
                );
            END
            """
        )

    with pytest.raises(
        SourceProtectedSemanticIntegrityError,
        match="mapping violates",
    ):
        with app.database.write_transaction() as connection:
            repository.protect_source_extraction_snapshot_semantics(
                connection,
                source_id=source.source_id,
                protection_scope_id=scope.protection_scope_id,
                payload_writer=_writer(
                    app,
                    scope.protection_scope_id,
                ),
            )

    after_rows = tuple(
        tuple(row)
        for row in app.database.connection.execute(
            """
            SELECT
                s.processing_run_id,
                s.analysis_id,
                s.model_json,
                s.evidence_json,
                s.proposals_json
            FROM source_extraction_result_snapshots AS s
            JOIN source_analyses AS a
              ON a.analysis_id = s.analysis_id
            WHERE a.source_id = ?
            ORDER BY s.processing_run_id
            """,
            (uuid_to_blob(source.source_id),),
        ).fetchall()
    )

    assert after_rows == before_rows
    assert int(
        app.database.connection.execute(
            "SELECT COUNT(*) FROM protected_payloads"
        ).fetchone()[0]
    ) == before_payloads
    assert int(
        app.database.connection.execute(
            """
            SELECT COUNT(*)
            FROM source_protected_semantic_payloads
            WHERE source_id = ?
              AND semantic_kind = ?
            """,
            (
                uuid_to_blob(source.source_id),
                EXTRACTION_SNAPSHOT_SEMANTIC_KIND,
            ),
        ).fetchone()[0]
    ) == 0


def test_extraction_snapshot_wrong_or_missing_identity_encrypts_nothing(
    app: AthenaApplication,
    tmp_path: Path,
) -> None:
    source, analysis = _prepare_analysis(
        app,
        tmp_path,
        name="identity",
    )
    _insert_snapshot(
        app,
        analysis,
        canary="Identity snapshot proposal.",
    )
    other_source = _prepare_source(
        app,
        tmp_path,
        name="other-source",
    )

    scope = _scope(
        app,
        b"extraction-snapshot-identity-password",
    )
    repository = SourceProtectedSemanticRepository(app.database)
    calls: list[bytes] = []
    writer = _writer(
        app,
        scope.protection_scope_id,
        calls,
    )

    with pytest.raises(
        SourceProtectedSemanticIntegrityError,
        match="does not belong",
    ):
        with app.database.write_transaction() as connection:
            repository.protect_analysis_extraction_snapshot_semantics(
                connection,
                source_id=other_source.source_id,
                analysis_id=analysis.analysis_id,
                protection_scope_id=scope.protection_scope_id,
                payload_writer=writer,
            )

    with pytest.raises(SourceProtectedSemanticNotFoundError):
        with app.database.write_transaction() as connection:
            repository.protect_analysis_extraction_snapshot_semantics(
                connection,
                source_id=source.source_id,
                analysis_id=uuid.uuid4(),
                protection_scope_id=scope.protection_scope_id,
                payload_writer=writer,
            )

    with pytest.raises(SourceProtectedSemanticNotFoundError):
        with app.database.write_transaction() as connection:
            repository.protect_source_extraction_snapshot_semantics(
                connection,
                source_id=uuid.uuid4(),
                protection_scope_id=scope.protection_scope_id,
                payload_writer=writer,
            )

    assert calls == []


def test_extraction_snapshot_cutover_requires_active_transaction(
    app: AthenaApplication,
    tmp_path: Path,
) -> None:
    source, analysis = _prepare_analysis(
        app,
        tmp_path,
        name="transaction",
    )

    scope = _scope(
        app,
        b"extraction-snapshot-transaction-password",
    )
    repository = SourceProtectedSemanticRepository(app.database)

    with pytest.raises(
        RuntimeError,
        match="active transaction",
    ):
        repository.protect_analysis_extraction_snapshot_semantics(
            app.database.connection,
            source_id=source.source_id,
            analysis_id=analysis.analysis_id,
            protection_scope_id=scope.protection_scope_id,
            payload_writer=_writer(
                app,
                scope.protection_scope_id,
            ),
        )
