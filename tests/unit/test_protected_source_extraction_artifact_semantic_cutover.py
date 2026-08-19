from __future__ import annotations

import hashlib
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
from athena.knowledge.source_hierarchical_repository import (
    SourceHierarchicalExtractionInvariantError,
    SourceHierarchicalExtractionRepository,
)
from athena.model.domain import ModelChatMessage, ModelInfo
from athena.security.models import Argon2idParameters
from athena.source.protected_semantic import (
    EXTRACTION_ARTIFACT_SEMANTIC_KIND,
    EXTRACTION_NEUTRAL_ARTIFACT_CONTENT_JSON,
    SourceProtectedSemanticIntegrityError,
    SourceProtectedSemanticNotFoundError,
    SourceProtectedSemanticRepository,
    decode_source_extraction_artifact_semantics,
    extraction_artifact_neutral_content_hash,
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
                "summary": "Relevant extraction-artifact fixture.",
                "findings": ["Extraction artifact fixture finding."],
                "contradictions": [],
                "uncertainty": "",
            }

        return {
            "summary": "Extraction artifact fixture synthesis.",
            "findings": ["Extraction artifact fixture finding."],
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
        neutral_label="extraction-artifact-semantic-test",
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
        f"ATHENA_EXTRACTION_ARTIFACT_SOURCE_{name} "
        + ("durable source payload " * 220)
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
        question=f"Extract artifact semantics for {name}.",
        worker=f"extraction-artifact-analysis-{name}",
    )
    return source, analysis


def _evidence(
    app: AthenaApplication,
    analysis,
) -> tuple[tuple[int, uuid.UUID, bytes], ...]:
    assert analysis.final_artifact_id is not None
    anchor_ids = (
        app.source_analysis_repository
        .source_anchor_ids_for_artifact(
            analysis.final_artifact_id
        )
    )
    assert anchor_ids

    result: list[tuple[int, uuid.UUID, bytes]] = []

    for sequence_no, anchor_id in enumerate(anchor_ids, 1):
        anchor = app.source_anchors.verify(anchor_id)
        assert anchor.quoted_hash is not None
        result.append(
            (
                sequence_no,
                anchor_id,
                anchor.quoted_hash,
            )
        )

    return tuple(result)


def _create_extraction(
    app: AthenaApplication,
    analysis,
    *,
    content: Mapping[str, object] | None,
):
    assert analysis.final_artifact_id is not None

    job = app.jobs.create(job_type="source.extract")
    extraction = (
        app.source_hierarchical_extraction_repository
        .get_or_create_extraction(
            job_id=job.job_id,
            analysis_id=analysis.analysis_id,
            final_artifact_id=analysis.final_artifact_id,
            model_signature_id=analysis.model_signature_id,
            pipeline_version="protected-extraction-artifact-test-v1",
            effective_context_limit=3000,
            output_reserve=300,
            safety_margin=100,
            token_estimator="protected-extraction-artifact-test-estimator",
            prompt_template_id="protected-extraction-artifact-test",
            prompt_template_version="1",
            max_hierarchy_depth=12,
            evidence=_evidence(app, analysis),
        )
    )

    if content is None:
        return extraction, job, None, None

    content_json = json.dumps(
        dict(content),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    content_hash = hashlib.sha256(
        content_json.encode("utf-8")
    ).digest()

    processing_run = app.database.connection.execute(
        """
        SELECT processing_run_id
        FROM source_analysis_artifacts
        WHERE artifact_id = ?
        """,
        (uuid_to_blob(analysis.final_artifact_id),),
    ).fetchone()
    assert processing_run is not None

    work_item_id = uuid.uuid4()
    artifact_id = uuid.uuid4()
    now_us = utc_now_us()

    with app.database.write_transaction() as connection:
        connection.execute(
            """
            INSERT INTO source_extraction_work_items (
                work_item_id, extraction_id, stage, level, ordinal, state,
                idempotency_key, attempt_count, created_at_us, updated_at_us
            ) VALUES (?, ?, 'merge', 0, 0, 'completed', ?, 1, ?, ?)
            """,
            (
                uuid_to_blob(work_item_id),
                uuid_to_blob(extraction.extraction_id),
                hashlib.sha256(work_item_id.bytes).digest(),
                now_us,
                now_us,
            ),
        )
        connection.execute(
            """
            INSERT INTO source_extraction_artifacts (
                artifact_id, extraction_id, work_item_id, artifact_kind,
                level, ordinal, content_json, content_hash,
                processing_run_id, created_at_us
            ) VALUES (?, ?, ?, 'merge', 0, 0, ?, ?, ?, ?)
            """,
            (
                uuid_to_blob(artifact_id),
                uuid_to_blob(extraction.extraction_id),
                uuid_to_blob(work_item_id),
                content_json,
                content_hash,
                bytes(processing_run["processing_run_id"]),
                now_us,
            ),
        )

    return extraction, job, artifact_id, (content_json, content_hash)


def _artifact_rows(
    app: AthenaApplication,
    extraction_id: uuid.UUID,
):
    return app.database.connection.execute(
        """
        SELECT artifact_id, extraction_id, content_json, content_hash
        FROM source_extraction_artifacts
        WHERE extraction_id = ?
        ORDER BY artifact_id
        """,
        (uuid_to_blob(extraction_id),),
    ).fetchall()


def _insert_pending_work(
    app: AthenaApplication,
    extraction_id: uuid.UUID,
) -> uuid.UUID:
    work_item_id = uuid.uuid4()
    now_us = utc_now_us()

    with app.database.write_transaction() as connection:
        connection.execute(
            """
            INSERT INTO source_extraction_work_items (
                work_item_id, extraction_id, stage, level, ordinal, state,
                idempotency_key, attempt_count, created_at_us, updated_at_us
            ) VALUES (?, ?, 'merge', 1, 1, 'pending', ?, 0, ?, ?)
            """,
            (
                uuid_to_blob(work_item_id),
                uuid_to_blob(extraction_id),
                hashlib.sha256(work_item_id.bytes).digest(),
                now_us,
                now_us,
            ),
        )

    return work_item_id


def test_extraction_artifact_roundtrip_neutralizes_public_rows_and_reader_fails_closed(
    app: AthenaApplication,
    tmp_path: Path,
) -> None:
    source, analysis = _prepare_analysis(
        app,
        tmp_path,
        name="roundtrip",
    )
    extraction, _job, artifact_id, original = _create_extraction(
        app,
        analysis,
        content={
            "summary": "ATHENA_EXTRACTION_ARTIFACT_CANARY",
            "claims": ["Protected extraction artifact canary."],
        },
    )
    assert artifact_id is not None
    assert original is not None

    scope = _scope(
        app,
        b"extraction-artifact-roundtrip-password",
    )
    repository = SourceProtectedSemanticRepository(app.database)

    with app.database.write_transaction() as connection:
        mapping = repository.protect_extraction_artifact_semantics(
            connection,
            source_id=source.source_id,
            extraction_id=extraction.extraction_id,
            protection_scope_id=scope.protection_scope_id,
            payload_writer=_writer(
                app,
                scope.protection_scope_id,
            ),
        )

    assert mapping.semantic_kind == EXTRACTION_ARTIFACT_SEMANTIC_KIND
    assert mapping.entity_id == extraction.extraction_id

    rows = _artifact_rows(
        app,
        extraction.extraction_id,
    )
    assert len(rows) == 1
    row = rows[0]

    assert str(row["content_json"]) == EXTRACTION_NEUTRAL_ARTIFACT_CONTENT_JSON
    assert bytes(row["content_hash"]) == extraction_artifact_neutral_content_hash(
        artifact_id
    )
    assert bytes(row["content_hash"]) != original[1]
    assert "ATHENA_EXTRACTION_ARTIFACT_CANARY" not in str(row["content_json"])

    decoded = decode_source_extraction_artifact_semantics(
        app.protected_content.load_payload(
            mapping.protected_payload_id
        )
    )
    assert decoded.extraction_id == extraction.extraction_id
    assert len(decoded.artifacts) == 1
    assert decoded.artifacts[0].artifact_id == artifact_id
    assert decoded.artifacts[0].content_json == original[0]
    assert decoded.artifacts[0].content_hash == original[1]

    with pytest.raises(
        SourceHierarchicalExtractionInvariantError,
        match="Protected SourceExtraction artifact semantics",
    ):
        app.source_hierarchical_extraction_repository.get_artifact(
            artifact_id
        )

    assert app.database.connection.execute(
        "PRAGMA integrity_check"
    ).fetchone()[0] == "ok"


def test_empty_extraction_artifact_set_creates_durable_late_write_fence(
    app: AthenaApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, analysis = _prepare_analysis(
        app,
        tmp_path,
        name="empty-fence",
    )
    extraction, job, _artifact_id, _original = _create_extraction(
        app,
        analysis,
        content=None,
    )

    scope = _scope(
        app,
        b"extraction-artifact-empty-fence-password",
    )
    repository = SourceProtectedSemanticRepository(app.database)

    with app.database.write_transaction() as connection:
        mapping = repository.protect_extraction_artifact_semantics(
            connection,
            source_id=source.source_id,
            extraction_id=extraction.extraction_id,
            protection_scope_id=scope.protection_scope_id,
            payload_writer=_writer(
                app,
                scope.protection_scope_id,
            ),
        )

    decoded = decode_source_extraction_artifact_semantics(
        app.protected_content.load_payload(
            mapping.protected_payload_id
        )
    )
    assert decoded.artifacts == ()

    work_item_id = _insert_pending_work(
        app,
        extraction.extraction_id,
    )

    monkeypatch.setattr(
        SourceHierarchicalExtractionRepository,
        "_require_live_fence",
        staticmethod(
            lambda *_args, **_kwargs: None
        ),
    )

    with pytest.raises(
        SourceHierarchicalExtractionInvariantError,
        match="Protected SourceExtraction cannot accept new semantic artifacts",
    ):
        app.source_hierarchical_extraction_repository.commit_artifact(
            work_item_id=work_item_id,
            job_id=job.job_id,
            lease_token=b"x" * 32,
            content={"late": "ATHENA_LATE_WRITE_CANARY"},
            processing_run_id=uuid.uuid4(),
        )


def test_extraction_artifact_cutover_is_idempotent_without_new_ciphertext(
    app: AthenaApplication,
    tmp_path: Path,
) -> None:
    source, analysis = _prepare_analysis(
        app,
        tmp_path,
        name="idempotent",
    )
    extraction, _job, _artifact_id, _original = _create_extraction(
        app,
        analysis,
        content={"summary": "Idempotent extraction artifact."},
    )
    scope = _scope(
        app,
        b"extraction-artifact-idempotent-password",
    )
    repository = SourceProtectedSemanticRepository(app.database)
    calls: list[bytes] = []
    writer = _writer(
        app,
        scope.protection_scope_id,
        calls,
    )

    with app.database.write_transaction() as connection:
        first = repository.protect_extraction_artifact_semantics(
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
    assert len(calls) == 1

    with app.database.write_transaction() as connection:
        second = repository.protect_extraction_artifact_semantics(
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


def test_extraction_artifact_existing_mapping_with_public_mixed_state_fails_closed(
    app: AthenaApplication,
    tmp_path: Path,
) -> None:
    source, analysis = _prepare_analysis(
        app,
        tmp_path,
        name="mixed",
    )
    extraction, _job, artifact_id, original = _create_extraction(
        app,
        analysis,
        content={"summary": "Mixed extraction artifact."},
    )
    assert artifact_id is not None
    assert original is not None

    scope = _scope(
        app,
        b"extraction-artifact-mixed-password",
    )
    repository = SourceProtectedSemanticRepository(app.database)
    calls: list[bytes] = []
    writer = _writer(
        app,
        scope.protection_scope_id,
        calls,
    )

    with app.database.write_transaction() as connection:
        repository.protect_extraction_artifact_semantics(
            connection,
            source_id=source.source_id,
            extraction_id=extraction.extraction_id,
            protection_scope_id=scope.protection_scope_id,
            payload_writer=writer,
        )

    with app.database.write_transaction() as connection:
        connection.execute(
            """
            UPDATE source_extraction_artifacts
            SET content_json = ?, content_hash = ?
            WHERE artifact_id = ?
            """,
            (
                original[0],
                original[1],
                uuid_to_blob(artifact_id),
            ),
        )

    with pytest.raises(
        SourceProtectedSemanticIntegrityError,
        match="not fully neutralized",
    ):
        with app.database.write_transaction() as connection:
            repository.protect_extraction_artifact_semantics(
                connection,
                source_id=source.source_id,
                extraction_id=extraction.extraction_id,
                protection_scope_id=scope.protection_scope_id,
                payload_writer=writer,
            )

    assert len(calls) == 1


def test_source_extraction_artifact_batch_rolls_back_on_second_mapping_failure(
    app: AthenaApplication,
    tmp_path: Path,
) -> None:
    source = _prepare_source(
        app,
        tmp_path,
        name="rollback",
    )
    first_analysis = _run_analysis(
        app,
        source.source_id,
        question="First extraction artifact rollback analysis.",
        worker="extraction-artifact-rollback-first",
    )
    second_analysis = _run_analysis(
        app,
        source.source_id,
        question="Second extraction artifact rollback analysis.",
        worker="extraction-artifact-rollback-second",
    )

    first, _first_job, _first_artifact, _first_original = _create_extraction(
        app,
        first_analysis,
        content={"summary": "First rollback extraction artifact."},
    )
    second, _second_job, _second_artifact, _second_original = _create_extraction(
        app,
        second_analysis,
        content={"summary": "Second rollback extraction artifact."},
    )

    ordered_ids = sorted(
        (
            first.extraction_id,
            second.extraction_id,
        ),
        key=lambda item: item.bytes,
    )
    failing_id = ordered_ids[1]

    scope = _scope(
        app,
        b"extraction-artifact-rollback-password",
    )
    repository = SourceProtectedSemanticRepository(app.database)

    before_rows = tuple(
        tuple(row)
        for row in app.database.connection.execute(
            """
            SELECT art.extraction_id, art.artifact_id,
                   art.content_json, art.content_hash
            FROM source_extraction_artifacts AS art
            JOIN source_extractions AS x
              ON x.extraction_id = art.extraction_id
            JOIN source_analyses AS a
              ON a.analysis_id = x.analysis_id
            WHERE a.source_id = ?
            ORDER BY art.extraction_id, art.artifact_id
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
            CREATE TRIGGER fail_second_extraction_artifact_mapping
            BEFORE INSERT
            ON source_protected_semantic_payloads
            WHEN NEW.semantic_kind = '{EXTRACTION_ARTIFACT_SEMANTIC_KIND}'
             AND hex(NEW.entity_id) = '{failing_id.hex.upper()}'
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'forced extraction artifact mapping failure'
                );
            END
            """
        )

    with pytest.raises(
        SourceProtectedSemanticIntegrityError,
        match="mapping violates",
    ):
        with app.database.write_transaction() as connection:
            repository.protect_source_extraction_artifact_semantics(
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
            SELECT art.extraction_id, art.artifact_id,
                   art.content_json, art.content_hash
            FROM source_extraction_artifacts AS art
            JOIN source_extractions AS x
              ON x.extraction_id = art.extraction_id
            JOIN source_analyses AS a
              ON a.analysis_id = x.analysis_id
            WHERE a.source_id = ?
            ORDER BY art.extraction_id, art.artifact_id
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
                EXTRACTION_ARTIFACT_SEMANTIC_KIND,
            ),
        ).fetchone()[0]
    ) == 0


def test_extraction_artifact_wrong_or_missing_identity_encrypts_nothing(
    app: AthenaApplication,
    tmp_path: Path,
) -> None:
    source, analysis = _prepare_analysis(
        app,
        tmp_path,
        name="identity",
    )
    extraction, _job, _artifact_id, _original = _create_extraction(
        app,
        analysis,
        content={"summary": "Identity extraction artifact."},
    )
    other_source = _prepare_source(
        app,
        tmp_path,
        name="other-source",
    )

    scope = _scope(
        app,
        b"extraction-artifact-identity-password",
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
            repository.protect_extraction_artifact_semantics(
                connection,
                source_id=other_source.source_id,
                extraction_id=extraction.extraction_id,
                protection_scope_id=scope.protection_scope_id,
                payload_writer=writer,
            )

    with pytest.raises(SourceProtectedSemanticNotFoundError):
        with app.database.write_transaction() as connection:
            repository.protect_extraction_artifact_semantics(
                connection,
                source_id=source.source_id,
                extraction_id=uuid.uuid4(),
                protection_scope_id=scope.protection_scope_id,
                payload_writer=writer,
            )

    with pytest.raises(SourceProtectedSemanticNotFoundError):
        with app.database.write_transaction() as connection:
            repository.protect_source_extraction_artifact_semantics(
                connection,
                source_id=uuid.uuid4(),
                protection_scope_id=scope.protection_scope_id,
                payload_writer=writer,
            )

    assert calls == []


def test_extraction_artifact_cutover_requires_active_transaction(
    app: AthenaApplication,
    tmp_path: Path,
) -> None:
    source, analysis = _prepare_analysis(
        app,
        tmp_path,
        name="transaction",
    )
    extraction, _job, _artifact_id, _original = _create_extraction(
        app,
        analysis,
        content={"summary": "Transaction extraction artifact."},
    )

    scope = _scope(
        app,
        b"extraction-artifact-transaction-password",
    )
    repository = SourceProtectedSemanticRepository(app.database)

    with pytest.raises(
        RuntimeError,
        match="active transaction",
    ):
        repository.protect_extraction_artifact_semantics(
            app.database.connection,
            source_id=source.source_id,
            extraction_id=extraction.extraction_id,
            protection_scope_id=scope.protection_scope_id,
            payload_writer=_writer(
                app,
                scope.protection_scope_id,
            ),
        )
