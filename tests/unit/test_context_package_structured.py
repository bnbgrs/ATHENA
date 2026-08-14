from __future__ import annotations

import json
import uuid

from athena.model.domain import ModelInfo
from athena.model.provenance import ModelRunRepository
from athena.retrieval.context_package import (
    ContextIncludedRef,
    ContextPackageBudget,
    ContextPackageService,
    ContextSection,
    ContextTokenEstimates,
    ExcludedCandidateSummary,
)
from athena.storage.database import SQLiteDatabase


def test_generic_structured_package_roundtrips_schema_without_plaintext_snapshot(tmp_path) -> None:
    database = SQLiteDatabase(tmp_path / "athena.db")
    database.start()
    try:
        runs = ModelRunRepository(database)
        model = ModelInfo(
            provider="lm_studio",
            backend_model_id="primary",
            display_name="primary",
            model_type="llm",
            context_capacity=32768,
            quantization="Q4_K_M",
            loaded=True,
            vision=False,
            trained_for_tool_use=False,
            loaded_context_length=4096,
        )
        signature = runs.get_or_create_signature(
            model=model,
            generation_parameters={"temperature": 0.0, "structured_output": True},
            context_configuration={"effective_context_limit": 4096},
        )
        entity_id = uuid.uuid4()
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
        }
        package = ContextPackageService(database).build_from_sections(
            model_signature=signature,
            budget=ContextPackageBudget(
                effective_context_limit=4096,
                context_budget=3000,
                output_reserve=800,
                safety_margin=100,
            ),
            sections=(
                ContextSection(
                    name="policy",
                    role="system",
                    content="system policy",
                    included_ref_ids=(),
                ),
                ContextSection(
                    name="task",
                    role="user",
                    content="source evidence plaintext",
                    included_ref_ids=("SRC-001",),
                ),
            ),
            included_refs=(
                ContextIncludedRef(
                    ref_id="SRC-001",
                    entity_type="source_anchor",
                    entity_id=entity_id,
                    revision_id=None,
                ),
            ),
            excluded_candidate_summary=ExcludedCandidateSummary(
                retrieval_candidate_count=1,
                retrieval_included_count=1,
                retrieval_excluded_count=0,
                memory_candidate_count=0,
                memory_included_count=0,
                memory_excluded_count=0,
                conversation_candidate_count=0,
                conversation_included_count=0,
                conversation_excluded_count=0,
            ),
            token_estimates=ContextTokenEstimates(
                conversation_tokens=0,
                current_user_tokens=0,
                system_tokens=10,
                context_tokens=100,
                estimated_input_tokens=200,
                estimated_total_tokens=1100,
            ),
            snapshot_commit_seq=0,
            structured_schema_id="test_schema_v1",
            structured_schema=schema,
        )

        assert package.structured_schema() == schema
        assert package.structured_schema_id == "test_schema_v1"

        snapshot = package.run_snapshot()
        assert snapshot["structured_output"]["schema_id"] == "test_schema_v1"
        assert len(snapshot["structured_output"]["schema_sha256"]) == 64
        encoded = json.dumps(snapshot, ensure_ascii=False)
        assert "source evidence plaintext" not in encoded
        assert '"answer"' not in encoded
    finally:
        database.stop()
