from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from athena.common.ids import uuid_to_blob
from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.knowledge.source_hierarchical_repository import (
    SourceHierarchicalExtractionInvariantError,
)
from athena.knowledge.source_hierarchical_service import (
    SourceHierarchicalExtractionConfigurationError,
)
from athena.model.domain import ModelChatMessage, ModelInfo
from athena.security.models import Argon2idParameters
from athena.source.protected_semantic import (
    EXTRACTION_EVIDENCE_SEMANTIC_KIND,
    SourceProtectedSemanticIntegrityError,
    SourceProtectedSemanticNotFoundError,
    SourceProtectedSemanticRepository,
    decode_source_extraction_evidence_semantics,
    extraction_evidence_neutral_quoted_hash,
)

_TEST_KDF = Argon2idParameters(
    iterations=1,
    lanes=1,
    memory_cost_kib=8 * 1024,
    length=32,
)


@dataclass
class _FakeAnalysisProvider:
    context_capacity: int = 4000
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
        json_schema: Mapping[str, Any],
        max_output_tokens: int | None = None,
    ) -> Mapping[str, Any]:
        del messages, json_schema, max_output_tokens
        assert model_id == "fake-primary"

        if "map" in schema_id:
            return {
                "relevant": True,
                "summary": "Relevant protected-evidence fixture.",
                "findings": ["Protected-evidence fixture finding."],
                "contradictions": [],
                "uncertainty": "",
            }

        return {
            "summary": "Protected-evidence fixture synthesis.",
            "findings": ["Protected-evidence fixture finding."],
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
        neutral_label="extraction-evidence-semantic-test",
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


def _prepare_analysis(
    app: AthenaApplication,
    tmp_path: Path,
    *,
    name: str,
):
    text = (
        f"ATHENA_EXTRACTION_EVIDENCE_CANARY_{name} "
        + ("durable evidence payload " * 140)
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

    job = app.source_analysis.enqueue(
        source.source_id,
        question="Summarize all relevant protected evidence.",
        requested_model_id="fake-primary",
        context_limit=3000,
        output_reserve=300,
        safety_margin=100,
        max_hierarchy_depth=12,
    )
    result = app.source_analysis.run_to_completion(
        job.job_id,
        worker_id=f"protected-evidence-analysis-{name}",
    )

    assert result.done is True
    assert result.analysis is not None
    analysis = result.analysis
    assert analysis.final_artifact_id is not None

    anchor_ids = (
        app.source_analysis_repository
        .source_anchor_ids_for_artifact(
            analysis.final_artifact_id
        )
    )
    assert anchor_ids

    evidence: list[tuple[int, uuid.UUID, bytes]] = []

    for sequence_no, anchor_id in enumerate(anchor_ids, 1):
        anchor = app.source_anchors.verify(anchor_id)
        assert anchor.quoted_hash is not None
        evidence.append(
            (
                sequence_no,
                anchor_id,
                anchor.quoted_hash,
            )
        )

    return source, analysis, tuple(evidence)


def _create_extraction(
    app: AthenaApplication,
    analysis,
    evidence: tuple[tuple[int, uuid.UUID, bytes], ...],
):
    assert analysis.final_artifact_id is not None

    job = app.jobs.create(job_type="source.extract")
    arguments = {
        "job_id": job.job_id,
        "analysis_id": analysis.analysis_id,
        "final_artifact_id": analysis.final_artifact_id,
        "model_signature_id": analysis.model_signature_id,
        "pipeline_version": "protected-evidence-test-v1",
        "effective_context_limit": 3000,
        "output_reserve": 300,
        "safety_margin": 100,
        "token_estimator": "protected-evidence-test-estimator",
        "prompt_template_id": "protected-evidence-test",
        "prompt_template_version": "1",
        "max_hierarchy_depth": 12,
        "evidence": evidence,
    }
    extraction = (
        app.source_hierarchical_extraction_repository
        .get_or_create_extraction(**arguments)
    )
    return extraction, arguments


def _rows(
    app: AthenaApplication,
    extraction_id: uuid.UUID,
):
    return app.database.connection.execute(
        """
        SELECT sequence_no, source_anchor_id, quoted_hash
        FROM source_extraction_evidence
        WHERE extraction_id = ?
        ORDER BY sequence_no
        """,
        (uuid_to_blob(extraction_id),),
    ).fetchall()


def test_extraction_evidence_roundtrip_neutralizes_public_hashes_and_reader_fails_closed(
    app: AthenaApplication,
    tmp_path: Path,
) -> None:
    source, analysis, evidence = _prepare_analysis(
        app,
        tmp_path,
        name="roundtrip",
    )
    extraction, arguments = _create_extraction(
        app,
        analysis,
        evidence,
    )
    original_hashes = tuple(item[2] for item in evidence)

    scope = _scope(
        app,
        b"extraction-evidence-roundtrip-password",
    )
    repository = SourceProtectedSemanticRepository(app.database)

    with app.database.write_transaction() as connection:
        mapping = repository.protect_extraction_evidence_semantics(
            connection,
            source_id=source.source_id,
            extraction_id=extraction.extraction_id,
            protection_scope_id=scope.protection_scope_id,
            payload_writer=_writer(
                app,
                scope.protection_scope_id,
            ),
        )

    assert mapping.semantic_kind == EXTRACTION_EVIDENCE_SEMANTIC_KIND
    assert mapping.entity_id == extraction.extraction_id

    rows = _rows(app, extraction.extraction_id)
    assert len(rows) == len(evidence)

    for row, original in zip(rows, evidence, strict=True):
        sequence_no, anchor_id, quoted_hash = original
        public_hash = bytes(row["quoted_hash"])

        assert int(row["sequence_no"]) == sequence_no
        assert bytes(row["source_anchor_id"]) == uuid_to_blob(anchor_id)
        assert public_hash == extraction_evidence_neutral_quoted_hash(
            extraction.extraction_id,
            sequence_no,
            anchor_id,
        )
        assert public_hash != quoted_hash
        assert public_hash not in original_hashes

    decoded = decode_source_extraction_evidence_semantics(
        app.protected_content.load_payload(
            mapping.protected_payload_id
        )
    )

    assert decoded.extraction_id == extraction.extraction_id
    assert tuple(
        (
            item.sequence_no,
            item.source_anchor_id,
            item.quoted_hash,
        )
        for item in decoded.evidence
    ) == evidence

    with pytest.raises(
        SourceHierarchicalExtractionConfigurationError,
        match="SourceAnchor hash changed",
    ):
        app.source_hierarchical_extraction_service._verified_source_messages(
            extraction
        )

    with pytest.raises(
        SourceHierarchicalExtractionInvariantError,
        match="evidence changed",
    ):
        app.source_hierarchical_extraction_repository.get_or_create_extraction(
            **arguments
        )

    assert app.database.connection.execute(
        "PRAGMA integrity_check"
    ).fetchone()[0] == "ok"


def test_extraction_evidence_cutover_is_idempotent_and_mixed_state_fails_closed(
    app: AthenaApplication,
    tmp_path: Path,
) -> None:
    source, analysis, evidence = _prepare_analysis(
        app,
        tmp_path,
        name="idempotent",
    )
    extraction, _arguments = _create_extraction(
        app,
        analysis,
        evidence,
    )
    scope = _scope(
        app,
        b"extraction-evidence-idempotent-password",
    )
    repository = SourceProtectedSemanticRepository(app.database)
    calls: list[bytes] = []
    writer = _writer(
        app,
        scope.protection_scope_id,
        calls,
    )

    with app.database.write_transaction() as connection:
        first = repository.protect_extraction_evidence_semantics(
            connection,
            source_id=source.source_id,
            extraction_id=extraction.extraction_id,
            protection_scope_id=scope.protection_scope_id,
            payload_writer=writer,
        )

    payload_count = int(
        app.database.connection.execute(
            "SELECT COUNT(*) FROM protected_payloads"
        ).fetchone()[0]
    )

    with app.database.write_transaction() as connection:
        second = repository.protect_extraction_evidence_semantics(
            connection,
            source_id=source.source_id,
            extraction_id=extraction.extraction_id,
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

    sequence_no, anchor_id, original_hash = evidence[0]

    with app.database.write_transaction() as connection:
        connection.execute(
            """
            UPDATE source_extraction_evidence
            SET quoted_hash = ?
            WHERE extraction_id = ?
              AND sequence_no = ?
              AND source_anchor_id = ?
            """,
            (
                original_hash,
                uuid_to_blob(extraction.extraction_id),
                sequence_no,
                uuid_to_blob(anchor_id),
            ),
        )

    with pytest.raises(
        SourceProtectedSemanticIntegrityError,
        match="not fully neutralized",
    ):
        with app.database.write_transaction() as connection:
            repository.protect_extraction_evidence_semantics(
                connection,
                source_id=source.source_id,
                extraction_id=extraction.extraction_id,
                protection_scope_id=scope.protection_scope_id,
                payload_writer=writer,
            )

    assert len(calls) == 1


def test_second_extraction_failure_rolls_back_first_mapping_payload_and_neutralization(
    app: AthenaApplication,
    tmp_path: Path,
) -> None:
    source, analysis, evidence = _prepare_analysis(
        app,
        tmp_path,
        name="rollback",
    )
    first, _first_arguments = _create_extraction(
        app,
        analysis,
        evidence,
    )
    second, _second_arguments = _create_extraction(
        app,
        analysis,
        evidence,
    )

    scope = _scope(
        app,
        b"extraction-evidence-rollback-password",
    )
    repository = SourceProtectedSemanticRepository(app.database)

    ordered_ids = sorted(
        (
            first.extraction_id,
            second.extraction_id,
        ),
        key=lambda item: item.bytes,
    )
    failing_id = ordered_ids[1]

    before_rows = tuple(
        tuple(row)
        for row in app.database.connection.execute(
            """
            SELECT e.extraction_id, e.sequence_no, e.quoted_hash
            FROM source_extraction_evidence AS e
            JOIN source_extractions AS x
              ON x.extraction_id = e.extraction_id
            JOIN source_analyses AS a
              ON a.analysis_id = x.analysis_id
            WHERE a.source_id = ?
            ORDER BY e.extraction_id, e.sequence_no
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
            CREATE TRIGGER fail_second_extraction_evidence_mapping
            BEFORE INSERT
            ON source_protected_semantic_payloads
            WHEN NEW.semantic_kind = '{EXTRACTION_EVIDENCE_SEMANTIC_KIND}'
             AND hex(NEW.entity_id) = '{failing_id.hex.upper()}'
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'forced extraction evidence mapping failure'
                );
            END
            """
        )

    with pytest.raises(
        SourceProtectedSemanticIntegrityError,
        match="mapping violates",
    ):
        with app.database.write_transaction() as connection:
            repository.protect_source_extraction_evidence_semantics(
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
            SELECT e.extraction_id, e.sequence_no, e.quoted_hash
            FROM source_extraction_evidence AS e
            JOIN source_extractions AS x
              ON x.extraction_id = e.extraction_id
            JOIN source_analyses AS a
              ON a.analysis_id = x.analysis_id
            WHERE a.source_id = ?
            ORDER BY e.extraction_id, e.sequence_no
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
                EXTRACTION_EVIDENCE_SEMANTIC_KIND,
            ),
        ).fetchone()[0]
    ) == 0


def test_missing_wrong_and_empty_source_paths_encrypt_nothing(
    app: AthenaApplication,
    tmp_path: Path,
) -> None:
    source, analysis, evidence = _prepare_analysis(
        app,
        tmp_path,
        name="scope",
    )
    extraction, _arguments = _create_extraction(
        app,
        analysis,
        evidence,
    )

    empty_path = tmp_path / "empty-source.txt"
    empty_path.write_text(
        "source with no extraction",
        encoding="utf-8",
        newline="",
    )
    empty_source = app.sources.capture_file(empty_path).source

    scope = _scope(
        app,
        b"extraction-evidence-scope-password",
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
            repository.protect_extraction_evidence_semantics(
                connection,
                source_id=empty_source.source_id,
                extraction_id=extraction.extraction_id,
                protection_scope_id=scope.protection_scope_id,
                payload_writer=writer,
            )

    with pytest.raises(SourceProtectedSemanticNotFoundError):
        with app.database.write_transaction() as connection:
            repository.protect_extraction_evidence_semantics(
                connection,
                source_id=source.source_id,
                extraction_id=uuid.uuid4(),
                protection_scope_id=scope.protection_scope_id,
                payload_writer=writer,
            )

    with pytest.raises(SourceProtectedSemanticNotFoundError):
        with app.database.write_transaction() as connection:
            repository.protect_source_extraction_evidence_semantics(
                connection,
                source_id=uuid.uuid4(),
                protection_scope_id=scope.protection_scope_id,
                payload_writer=writer,
            )

    with app.database.write_transaction() as connection:
        empty = repository.protect_source_extraction_evidence_semantics(
            connection,
            source_id=empty_source.source_id,
            protection_scope_id=scope.protection_scope_id,
            payload_writer=writer,
        )

    assert empty == ()
    assert calls == []


def test_requires_transaction_and_rejects_pre_neutralized_row_without_mapping(
    app: AthenaApplication,
    tmp_path: Path,
) -> None:
    source, analysis, evidence = _prepare_analysis(
        app,
        tmp_path,
        name="pre-neutralized",
    )
    extraction, _arguments = _create_extraction(
        app,
        analysis,
        evidence,
    )
    scope = _scope(
        app,
        b"extraction-evidence-pre-neutralized-password",
    )
    repository = SourceProtectedSemanticRepository(app.database)
    calls: list[bytes] = []
    writer = _writer(
        app,
        scope.protection_scope_id,
        calls,
    )

    with pytest.raises(
        RuntimeError,
        match="active transaction",
    ):
        repository.protect_extraction_evidence_semantics(
            app.database.connection,
            source_id=source.source_id,
            extraction_id=extraction.extraction_id,
            protection_scope_id=scope.protection_scope_id,
            payload_writer=writer,
        )

    sequence_no, anchor_id, _original_hash = evidence[0]
    neutral_hash = extraction_evidence_neutral_quoted_hash(
        extraction.extraction_id,
        sequence_no,
        anchor_id,
    )

    with app.database.write_transaction() as connection:
        connection.execute(
            """
            UPDATE source_extraction_evidence
            SET quoted_hash = ?
            WHERE extraction_id = ?
              AND sequence_no = ?
              AND source_anchor_id = ?
            """,
            (
                neutral_hash,
                uuid_to_blob(extraction.extraction_id),
                sequence_no,
                uuid_to_blob(anchor_id),
            ),
        )

    with pytest.raises(
        SourceProtectedSemanticIntegrityError,
        match="without a protected mapping",
    ):
        with app.database.write_transaction() as connection:
            repository.protect_extraction_evidence_semantics(
                connection,
                source_id=source.source_id,
                extraction_id=extraction.extraction_id,
                protection_scope_id=scope.protection_scope_id,
                payload_writer=writer,
            )

    assert calls == []


def test_existing_extraction_without_evidence_fails_closed_before_encryption(
    app: AthenaApplication,
    tmp_path: Path,
) -> None:
    source, analysis, evidence = _prepare_analysis(
        app,
        tmp_path,
        name="missing-evidence",
    )
    extraction, _arguments = _create_extraction(
        app,
        analysis,
        evidence,
    )
    scope = _scope(
        app,
        b"extraction-evidence-missing-password",
    )
    repository = SourceProtectedSemanticRepository(app.database)
    calls: list[bytes] = []
    writer = _writer(
        app,
        scope.protection_scope_id,
        calls,
    )

    with app.database.write_transaction() as connection:
        connection.execute(
            """
            DELETE FROM source_extraction_evidence
            WHERE extraction_id = ?
            """,
            (uuid_to_blob(extraction.extraction_id),),
        )

    with pytest.raises(
        SourceProtectedSemanticIntegrityError,
        match="has no frozen evidence",
    ):
        with app.database.write_transaction() as connection:
            repository.protect_extraction_evidence_semantics(
                connection,
                source_id=source.source_id,
                extraction_id=extraction.extraction_id,
                protection_scope_id=scope.protection_scope_id,
                payload_writer=writer,
            )

    assert calls == []
