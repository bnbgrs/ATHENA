from __future__ import annotations

import inspect

from athena.knowledge.source_hierarchical_service import (
    SourceHierarchicalExtractionService,
)
from athena.source.analysis_service import SourceAnalysisService


def test_source_analysis_provider_call_is_package_wrapped() -> None:
    source = inspect.getsource(SourceAnalysisService.execute_call)
    assert "_context_package_for_prepared" in source
    assert '"context_package": package.run_snapshot()' in source
    assert '"included_refs": list(prepared.input_refs)' in source
    assert "assert_snapshot_current" in source
    assert "messages=package.model_messages()" in source
    assert "json_schema=structured_schema" in source


def test_hierarchical_extraction_provider_call_is_package_wrapped() -> None:
    source = inspect.getsource(SourceHierarchicalExtractionService.execute_call)
    assert "_context_package_for_prepared" in source
    assert '"context_package": package.run_snapshot()' in source
    assert '"input_refs": list(prepared.input_refs)' in source
    assert "assert_snapshot_current" in source
    assert "messages=package.model_messages()" in source
    assert "json_schema=structured_schema" in source
    assert "reasoning_mode=config.reasoning_mode" in source
    assert "context_length=extraction.effective_context_limit" in source
    assert "max_output_tokens=extraction.output_reserve" in source
