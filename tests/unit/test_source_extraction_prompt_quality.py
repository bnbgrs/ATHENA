from __future__ import annotations

import uuid

from athena.knowledge.source_extraction import (
    PIPELINE_VERSION,
    PROMPT_TEMPLATE_VERSION,
    SourceAnalysisKnowledgeExtractionService,
)
from athena.source.analysis_models import (
    AnalysisStage,
    SourceAnalysisArtifact,
    SourceAnalysisRecord,
    SourceAnalysisState,
)


def test_source_extraction_prompt_rejects_structure_only_knowledge() -> None:
    analysis_id = uuid.uuid4()
    final_artifact_id = uuid.uuid4()
    analysis = SourceAnalysisRecord(
        analysis_id=analysis_id,
        job_id=uuid.uuid4(),
        source_id=uuid.uuid4(),
        representation_id=uuid.uuid4(),
        question="Summarize the substantive requirements.",
        state=SourceAnalysisState.COMPLETED,
        model_signature_id=uuid.uuid4(),
        pipeline_version="source-analysis/1",
        effective_context_limit=16_384,
        output_reserve=8_192,
        safety_margin=1_024,
        token_estimator="utf8-bytes-div3-v1",
        max_hierarchy_depth=12,
        total_map_units=1,
        completed_map_units=1,
        failed_map_units=0,
        coverage=1.0,
        final_artifact_id=final_artifact_id,
        created_at_us=1,
        updated_at_us=1,
    )
    final = SourceAnalysisArtifact(
        artifact_id=final_artifact_id,
        analysis_id=analysis_id,
        work_item_id=uuid.uuid4(),
        artifact_kind=AnalysisStage.FINAL,
        level=1,
        ordinal=0,
        content_json='{"summary":"durable hierarchical analysis"}',
        content_hash=b"x" * 32,
        processing_run_id=uuid.uuid4(),
        created_at_us=1,
    )

    system, user = SourceAnalysisKnowledgeExtractionService._build_prompt(
        analysis=analysis,
        final=final,
        source_messages={
            1: "## Evidence Section 01",
            2: "Durable processing must preserve confirmed semantic progress.",
        },
    )

    assert PIPELINE_VERSION == "source-analysis-knowledge-extraction/2"
    assert PROMPT_TEMPLATE_VERSION == "2"
    assert "Do not propose document-structure observations" in system
    assert "only content is that a section/header/label exists" in system
    assert "heading text itself states substantive domain knowledge" in system
    assert "explicitly asks about document structure" in system
    assert "## Evidence Section 01" in user
