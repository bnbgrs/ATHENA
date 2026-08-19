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
from athena.model.domain import ModelChatMessage, ModelInfo
from athena.security.models import Argon2idParameters
from athena.source.analysis_repository import SourceAnalysisInvariantError
from athena.source.protected_semantic import (
    ANALYSIS_ARTIFACT_SEMANTIC_KIND,
    ANALYSIS_NEUTRAL_ARTIFACT_CONTENT_JSON,
    ANALYSIS_SEMANTIC_KIND,
    SourceProtectedSemanticIntegrityError,
    SourceProtectedSemanticNotFoundError,
    SourceProtectedSemanticRepository,
    analysis_artifact_neutral_content_hash,
    analysis_neutral_question,
    decode_source_analysis_artifact_semantics,
    decode_source_analysis_semantics,
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
        json_schema: Mapping[str, Any],
        max_output_tokens: int | None = None,
    ) -> Mapping[str, Any]:
        del messages, json_schema, max_output_tokens
        assert model_id == "fake-primary"

        if "map" in schema_id:
            return {
                "relevant": True,
                "summary": "ATHENA_ANALYSIS_ARTIFACT_CANARY map summary.",
                "findings": ["ATHENA_ANALYSIS_ARTIFACT_CANARY map finding."],
                "contradictions": [],
                "uncertainty": "",
            }

        return {
            "summary": "ATHENA_ANALYSIS_ARTIFACT_CANARY synthesis.",
            "findings": ["ATHENA_ANALYSIS_ARTIFACT_CANARY synthesis finding."],
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
        neutral_label="analysis-semantic-test",
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
        f"ATHENA_ANALYSIS_SOURCE_CANARY_{name} "
        + ("semantic analysis fixture payload " * 240)
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
    question: str,
):
    source = _prepare_source(
        app,
        tmp_path,
        name=name,
    )
    analysis = _run_analysis(
        app,
        source.source_id,
        question=question,
        worker=f"analysis-semantic-{name}",
    )
    return source, analysis


def _analysis_row(
    app: AthenaApplication,
    analysis_id: uuid.UUID,
):
    return app.database.connection.execute(
        """
        SELECT analysis_id, source_id, question
        FROM source_analyses
        WHERE analysis_id = ?
        """,
        (uuid_to_blob(analysis_id),),
    ).fetchone()


def _artifact_rows(
    app: AthenaApplication,
    analysis_id: uuid.UUID,
):
    return app.database.connection.execute(
        """
        SELECT
            artifact_id,
            analysis_id,
            content_json,
            content_hash
        FROM source_analysis_artifacts
        WHERE analysis_id = ?
        ORDER BY artifact_id
        """,
        (uuid_to_blob(analysis_id),),
    ).fetchall()


def test_analysis_semantics_roundtrip_neutralizes_public_rows_and_readers_fail_closed(
    app: AthenaApplication,
    tmp_path: Path,
) -> None:
    question = "ATHENA_ANALYSIS_QUESTION_CANARY: summarize the source."
    source, analysis = _prepare_analysis(
        app,
        tmp_path,
        name="roundtrip",
        question=question,
    )

    original_artifacts = _artifact_rows(
        app,
        analysis.analysis_id,
    )
    assert original_artifacts
    assert any(
        "ATHENA_ANALYSIS_ARTIFACT_CANARY" in str(row["content_json"])
        for row in original_artifacts
    )

    scope = _scope(
        app,
        b"analysis-semantic-roundtrip-password",
    )
    repository = SourceProtectedSemanticRepository(app.database)

    with app.database.write_transaction() as connection:
        mappings = repository.protect_analysis_semantics(
            connection,
            source_id=source.source_id,
            analysis_id=analysis.analysis_id,
            protection_scope_id=scope.protection_scope_id,
            payload_writer=_writer(
                app,
                scope.protection_scope_id,
            ),
        )

    assert len(mappings) == 1 + len(original_artifacts)

    question_mappings = tuple(
        item
        for item in mappings
        if item.semantic_kind == ANALYSIS_SEMANTIC_KIND
    )
    artifact_mappings = tuple(
        item
        for item in mappings
        if item.semantic_kind == ANALYSIS_ARTIFACT_SEMANTIC_KIND
    )

    assert len(question_mappings) == 1
    assert len(artifact_mappings) == len(original_artifacts)
    assert question_mappings[0].entity_id == analysis.analysis_id

    public_analysis = _analysis_row(
        app,
        analysis.analysis_id,
    )
    assert public_analysis is not None
    assert str(public_analysis["question"]) == analysis_neutral_question(
        analysis.analysis_id
    )
    assert "ATHENA_ANALYSIS_QUESTION_CANARY" not in str(
        public_analysis["question"]
    )

    public_artifacts = _artifact_rows(
        app,
        analysis.analysis_id,
    )

    original_by_id = {
        uuid.UUID(bytes=bytes(row["artifact_id"])): (
            str(row["content_json"]),
            bytes(row["content_hash"]),
        )
        for row in original_artifacts
    }

    for row in public_artifacts:
        artifact_id = uuid.UUID(bytes=bytes(row["artifact_id"]))
        assert str(row["content_json"]) == ANALYSIS_NEUTRAL_ARTIFACT_CONTENT_JSON
        assert bytes(row["content_hash"]) == analysis_artifact_neutral_content_hash(
            artifact_id
        )
        assert bytes(row["content_hash"]) != original_by_id[artifact_id][1]
        assert "ATHENA_ANALYSIS_ARTIFACT_CANARY" not in str(row["content_json"])

    decoded_question = decode_source_analysis_semantics(
        app.protected_content.load_payload(
            question_mappings[0].protected_payload_id
        )
    )
    assert decoded_question.analysis_id == analysis.analysis_id
    assert decoded_question.question == question

    artifact_mapping_by_id = {
        item.entity_id: item
        for item in artifact_mappings
    }

    for artifact_id, (content_json, content_hash) in original_by_id.items():
        decoded = decode_source_analysis_artifact_semantics(
            app.protected_content.load_payload(
                artifact_mapping_by_id[artifact_id].protected_payload_id
            )
        )
        assert decoded.artifact_id == artifact_id
        assert decoded.analysis_id == analysis.analysis_id
        assert decoded.content_json == content_json
        assert decoded.content_hash == content_hash

    with pytest.raises(
        SourceAnalysisInvariantError,
        match="Protected SourceAnalysis semantics",
    ):
        app.source_analysis_repository.get_analysis(
            analysis.analysis_id
        )

    first_artifact_id = uuid.UUID(
        bytes=bytes(public_artifacts[0]["artifact_id"])
    )
    with pytest.raises(
        SourceAnalysisInvariantError,
        match="Protected SourceAnalysis artifact semantics",
    ):
        app.source_analysis_repository.get_artifact(
            first_artifact_id
        )

    assert app.database.connection.execute(
        "PRAGMA integrity_check"
    ).fetchone()[0] == "ok"


def test_analysis_semantic_cutover_is_idempotent_without_new_ciphertext(
    app: AthenaApplication,
    tmp_path: Path,
) -> None:
    source, analysis = _prepare_analysis(
        app,
        tmp_path,
        name="idempotent",
        question="Idempotent analysis semantic question.",
    )
    scope = _scope(
        app,
        b"analysis-semantic-idempotent-password",
    )
    repository = SourceProtectedSemanticRepository(app.database)
    calls: list[bytes] = []
    writer = _writer(
        app,
        scope.protection_scope_id,
        calls,
    )

    with app.database.write_transaction() as connection:
        first = repository.protect_analysis_semantics(
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
    call_count = len(calls)
    assert call_count == len(first)

    with app.database.write_transaction() as connection:
        second = repository.protect_analysis_semantics(
            connection,
            source_id=source.source_id,
            analysis_id=analysis.analysis_id,
            protection_scope_id=scope.protection_scope_id,
            payload_writer=writer,
        )

    assert second == first
    assert len(calls) == call_count
    assert int(
        app.database.connection.execute(
            "SELECT COUNT(*) FROM protected_payloads"
        ).fetchone()[0]
    ) == payload_count


def test_analysis_existing_mapping_with_public_mixed_state_fails_closed(
    app: AthenaApplication,
    tmp_path: Path,
) -> None:
    question = "Mixed-state analysis semantic question."
    source, analysis = _prepare_analysis(
        app,
        tmp_path,
        name="mixed",
        question=question,
    )
    scope = _scope(
        app,
        b"analysis-semantic-mixed-password",
    )
    repository = SourceProtectedSemanticRepository(app.database)
    calls: list[bytes] = []
    writer = _writer(
        app,
        scope.protection_scope_id,
        calls,
    )

    with app.database.write_transaction() as connection:
        repository.protect_analysis_semantics(
            connection,
            source_id=source.source_id,
            analysis_id=analysis.analysis_id,
            protection_scope_id=scope.protection_scope_id,
            payload_writer=writer,
        )

    call_count = len(calls)

    with app.database.write_transaction() as connection:
        connection.execute(
            """
            UPDATE source_analyses
            SET question = ?
            WHERE analysis_id = ?
            """,
            (
                question,
                uuid_to_blob(analysis.analysis_id),
            ),
        )

    with pytest.raises(
        SourceProtectedSemanticIntegrityError,
        match="not fully neutralized",
    ):
        with app.database.write_transaction() as connection:
            repository.protect_analysis_semantics(
                connection,
                source_id=source.source_id,
                analysis_id=analysis.analysis_id,
                protection_scope_id=scope.protection_scope_id,
                payload_writer=writer,
            )

    assert len(calls) == call_count


def test_source_analysis_semantic_batch_rolls_back_on_second_analysis_mapping_failure(
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
        question="First rollback analysis question.",
        worker="analysis-semantic-rollback-first",
    )
    second = _run_analysis(
        app,
        source.source_id,
        question="Second rollback analysis question.",
        worker="analysis-semantic-rollback-second",
    )

    scope = _scope(
        app,
        b"analysis-semantic-rollback-password",
    )
    repository = SourceProtectedSemanticRepository(app.database)

    ordered = sorted(
        (
            first.analysis_id,
            second.analysis_id,
        ),
        key=lambda item: item.bytes,
    )
    failing_id = ordered[1]

    before_analysis = tuple(
        tuple(row)
        for row in app.database.connection.execute(
            """
            SELECT analysis_id, question
            FROM source_analyses
            WHERE source_id = ?
            ORDER BY analysis_id
            """,
            (uuid_to_blob(source.source_id),),
        ).fetchall()
    )
    before_artifacts = tuple(
        tuple(row)
        for row in app.database.connection.execute(
            """
            SELECT a.artifact_id, a.content_json, a.content_hash
            FROM source_analysis_artifacts AS a
            JOIN source_analyses AS s
              ON s.analysis_id = a.analysis_id
            WHERE s.source_id = ?
            ORDER BY a.artifact_id
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
            CREATE TRIGGER fail_second_analysis_semantic_mapping
            BEFORE INSERT
            ON source_protected_semantic_payloads
            WHEN NEW.semantic_kind = '{ANALYSIS_SEMANTIC_KIND}'
             AND hex(NEW.entity_id) = '{failing_id.hex.upper()}'
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'forced analysis semantic mapping failure'
                );
            END
            """
        )

    with pytest.raises(
        SourceProtectedSemanticIntegrityError,
        match="mapping violates",
    ):
        with app.database.write_transaction() as connection:
            repository.protect_source_analysis_semantics(
                connection,
                source_id=source.source_id,
                protection_scope_id=scope.protection_scope_id,
                payload_writer=_writer(
                    app,
                    scope.protection_scope_id,
                ),
            )

    after_analysis = tuple(
        tuple(row)
        for row in app.database.connection.execute(
            """
            SELECT analysis_id, question
            FROM source_analyses
            WHERE source_id = ?
            ORDER BY analysis_id
            """,
            (uuid_to_blob(source.source_id),),
        ).fetchall()
    )
    after_artifacts = tuple(
        tuple(row)
        for row in app.database.connection.execute(
            """
            SELECT a.artifact_id, a.content_json, a.content_hash
            FROM source_analysis_artifacts AS a
            JOIN source_analyses AS s
              ON s.analysis_id = a.analysis_id
            WHERE s.source_id = ?
            ORDER BY a.artifact_id
            """,
            (uuid_to_blob(source.source_id),),
        ).fetchall()
    )

    assert after_analysis == before_analysis
    assert after_artifacts == before_artifacts
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
              AND semantic_kind IN (?, ?)
            """,
            (
                uuid_to_blob(source.source_id),
                ANALYSIS_SEMANTIC_KIND,
                ANALYSIS_ARTIFACT_SEMANTIC_KIND,
            ),
        ).fetchone()[0]
    ) == 0


def test_analysis_wrong_or_missing_source_paths_encrypt_nothing(
    app: AthenaApplication,
    tmp_path: Path,
) -> None:
    first_source, _first_analysis = _prepare_analysis(
        app,
        tmp_path,
        name="wrong-source-a",
        question="First source analysis.",
    )
    _second_source, second_analysis = _prepare_analysis(
        app,
        tmp_path,
        name="wrong-source-b",
        question="Second source analysis.",
    )

    scope = _scope(
        app,
        b"analysis-semantic-path-password",
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
            repository.protect_analysis_semantics(
                connection,
                source_id=first_source.source_id,
                analysis_id=second_analysis.analysis_id,
                protection_scope_id=scope.protection_scope_id,
                payload_writer=writer,
            )

    with pytest.raises(SourceProtectedSemanticNotFoundError):
        with app.database.write_transaction() as connection:
            repository.protect_analysis_semantics(
                connection,
                source_id=first_source.source_id,
                analysis_id=uuid.uuid4(),
                protection_scope_id=scope.protection_scope_id,
                payload_writer=writer,
            )

    with pytest.raises(SourceProtectedSemanticNotFoundError):
        with app.database.write_transaction() as connection:
            repository.protect_source_analysis_semantics(
                connection,
                source_id=uuid.uuid4(),
                protection_scope_id=scope.protection_scope_id,
                payload_writer=writer,
            )

    assert calls == []


def test_analysis_neutral_question_without_mapping_is_rejected(
    app: AthenaApplication,
    tmp_path: Path,
) -> None:
    source, analysis = _prepare_analysis(
        app,
        tmp_path,
        name="premature-neutral",
        question="Premature neutral analysis question.",
    )
    scope = _scope(
        app,
        b"analysis-semantic-neutral-password",
    )
    repository = SourceProtectedSemanticRepository(app.database)
    calls: list[bytes] = []

    with app.database.write_transaction() as connection:
        connection.execute(
            """
            UPDATE source_analyses
            SET question = ?
            WHERE analysis_id = ?
            """,
            (
                analysis_neutral_question(analysis.analysis_id),
                uuid_to_blob(analysis.analysis_id),
            ),
        )

    with pytest.raises(
        SourceProtectedSemanticIntegrityError,
        match="neutralized without a protected mapping",
    ):
        with app.database.write_transaction() as connection:
            repository.protect_analysis_semantics(
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


def test_analysis_artifact_corrupt_hash_rolls_back_question_payload_and_public_update(
    app: AthenaApplication,
    tmp_path: Path,
) -> None:
    question = "Corrupt artifact hash analysis question."
    source, analysis = _prepare_analysis(
        app,
        tmp_path,
        name="corrupt-hash",
        question=question,
    )
    artifacts = _artifact_rows(
        app,
        analysis.analysis_id,
    )
    assert artifacts

    artifact_id = uuid.UUID(
        bytes=bytes(artifacts[0]["artifact_id"])
    )

    with app.database.write_transaction() as connection:
        connection.execute(
            """
            UPDATE source_analysis_artifacts
            SET content_hash = ?
            WHERE artifact_id = ?
            """,
            (
                b"\xA5" * 32,
                uuid_to_blob(artifact_id),
            ),
        )

    scope = _scope(
        app,
        b"analysis-semantic-corrupt-password",
    )
    repository = SourceProtectedSemanticRepository(app.database)
    before_payloads = int(
        app.database.connection.execute(
            "SELECT COUNT(*) FROM protected_payloads"
        ).fetchone()[0]
    )

    with pytest.raises(
        SourceProtectedSemanticIntegrityError,
        match="hash disagrees with content",
    ):
        with app.database.write_transaction() as connection:
            repository.protect_analysis_semantics(
                connection,
                source_id=source.source_id,
                analysis_id=analysis.analysis_id,
                protection_scope_id=scope.protection_scope_id,
                payload_writer=_writer(
                    app,
                    scope.protection_scope_id,
                ),
            )

    row = _analysis_row(
        app,
        analysis.analysis_id,
    )
    assert row is not None
    assert str(row["question"]) == question
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
              AND semantic_kind IN (?, ?)
            """,
            (
                uuid_to_blob(source.source_id),
                ANALYSIS_SEMANTIC_KIND,
                ANALYSIS_ARTIFACT_SEMANTIC_KIND,
            ),
        ).fetchone()[0]
    ) == 0


def test_protected_analysis_blocks_late_artifact_commit_from_in_memory_work(
    app: AthenaApplication,
    tmp_path: Path,
) -> None:
    source = _prepare_source(
        app,
        tmp_path,
        name="late-commit",
    )
    job = app.source_analysis.enqueue(
        source.source_id,
        question="Late commit race analysis question.",
        requested_model_id="fake-primary",
        context_limit=4000,
        output_reserve=400,
        safety_margin=100,
        max_hierarchy_depth=12,
    )
    leased = app.jobs.acquire(
        job.job_id,
        worker_id="analysis-semantic-late-commit",
        lease_seconds=120,
    )
    assert leased.lease_token is not None

    analysis = app.source_analysis_service.initialize_analysis(
        leased
    )
    work_items = app.source_analysis_service.plan_map(
        analysis
    )
    assert work_items

    scope = _scope(
        app,
        b"analysis-semantic-late-commit-password",
    )
    repository = SourceProtectedSemanticRepository(app.database)

    with app.database.write_transaction() as connection:
        mappings = repository.protect_analysis_semantics(
            connection,
            source_id=source.source_id,
            analysis_id=analysis.analysis_id,
            protection_scope_id=scope.protection_scope_id,
            payload_writer=_writer(
                app,
                scope.protection_scope_id,
            ),
        )

    assert len(mappings) == 1

    with pytest.raises(
        SourceAnalysisInvariantError,
        match="cannot accept new semantic artifacts",
    ):
        app.source_analysis_repository.commit_artifact(
            work_item_id=work_items[0].work_item_id,
            job_id=job.job_id,
            lease_token=leased.lease_token,
            content={
                "relevant": True,
                "summary": "must not persist",
                "findings": [],
                "contradictions": [],
                "uncertainty": "",
            },
            processing_run_id=uuid.uuid4(),
        )

    assert _artifact_rows(
        app,
        analysis.analysis_id,
    ) == []


def test_analysis_cutover_requires_caller_transaction(
    app: AthenaApplication,
) -> None:
    repository = SourceProtectedSemanticRepository(app.database)

    with pytest.raises(
        RuntimeError,
        match="requires an active transaction",
    ):
        repository.protect_analysis_semantics(
            app.database.connection,
            source_id=uuid.uuid4(),
            analysis_id=uuid.uuid4(),
            protection_scope_id=uuid.uuid4(),
            payload_writer=lambda _connection, _payload: uuid.uuid4(),
        )

    with pytest.raises(
        RuntimeError,
        match="requires an active transaction",
    ):
        repository.protect_source_analysis_semantics(
            app.database.connection,
            source_id=uuid.uuid4(),
            protection_scope_id=uuid.uuid4(),
            payload_writer=lambda _connection, _payload: uuid.uuid4(),
        )
