from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.jobs.models import JobState
from athena.model.domain import ModelInfo
from athena.source.analysis_service import SourceAnalysisConfigurationError


@dataclass
class _CatalogProvider:
    context_capacity: int | None = 262_144
    loaded_context_length: int | None = 32_256

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
                quantization="Q4",
                loaded=True,
                loaded_context_length=self.loaded_context_length,
                vision=False,
                trained_for_tool_use=False,
            ),
        )


def _app(root: Path) -> AthenaApplication:
    app = AthenaApplication(settings=AthenaSettings(local_root=root))
    app.start()
    return app


def _processed_source(app: AthenaApplication, tmp_path: Path):
    source_path = tmp_path / "runtime-context-source.md"
    source_path.write_text(
        "ATHENA runtime context pinning evidence.\n\n" + ("payload " * 200),
        encoding="utf-8",
        newline="",
    )
    source = app.sources.capture_file(source_path).source
    representation = app.source_text.build(source.source_id).result.representation
    app.source_chunks.build_default(representation.representation_id)
    return source


def test_source_analysis_defaults_to_loaded_runtime_context(tmp_path: Path) -> None:
    app = _app(tmp_path / "runtime")
    source = _processed_source(app, tmp_path)
    provider = _CatalogProvider(
        context_capacity=262_144,
        loaded_context_length=32_256,
    )
    app.source_analysis_service.provider = provider

    job = app.source_analysis.enqueue(
        source.source_id,
        question="Summarize the evidence.",
        requested_model_id="fake-primary",
        output_reserve=2_048,
        safety_margin=512,
    )

    config = json.loads(job.pinned_configuration_json or "{}")
    assert config["effective_context_limit"] == 32_256
    assert config["output_reserve"] == 2_048
    assert config["safety_margin"] == 512
    app.stop()


def test_source_analysis_rejects_explicit_context_above_loaded_runtime(
    tmp_path: Path,
) -> None:
    app = _app(tmp_path / "runtime")
    source = _processed_source(app, tmp_path)
    app.source_analysis_service.provider = _CatalogProvider(
        context_capacity=262_144,
        loaded_context_length=32_256,
    )

    with pytest.raises(
        SourceAnalysisConfigurationError,
        match="exceeds loaded runtime context",
    ):
        app.source_analysis.enqueue(
            source.source_id,
            question="Summarize the evidence.",
            requested_model_id="fake-primary",
            context_limit=40_000,
        )

    assert app.jobs.list() == ()
    app.stop()


def test_source_analysis_requires_runtime_context_or_explicit_limit(
    tmp_path: Path,
) -> None:
    app = _app(tmp_path / "runtime")
    source = _processed_source(app, tmp_path)
    app.source_analysis_service.provider = _CatalogProvider(
        context_capacity=262_144,
        loaded_context_length=None,
    )

    with pytest.raises(
        SourceAnalysisConfigurationError,
        match="did not report its loaded runtime context",
    ):
        app.source_analysis.enqueue(
            source.source_id,
            question="Summarize the evidence.",
            requested_model_id="fake-primary",
        )

    explicit = app.source_analysis.enqueue(
        source.source_id,
        question="Summarize the evidence.",
        requested_model_id="fake-primary",
        context_limit=16_384,
        output_reserve=1_024,
        safety_margin=256,
    )
    config = json.loads(explicit.pinned_configuration_json or "{}")
    assert config["effective_context_limit"] == 16_384
    app.stop()


def test_source_process_hard_exit_restart_resumes_idempotently(
    tmp_path: Path,
) -> None:
    root = (tmp_path / "runtime").resolve()
    source_path = tmp_path / "hard-kill-source.md"
    source_path.write_text(
        "ATHENA hard kill durable source marker.\n\n" + ("payload " * 300),
        encoding="utf-8",
        newline="",
    )

    first = _app(root)
    source = first.sources.capture_file(source_path).source
    job = first.source_processing.enqueue(source.source_id)
    first.stop()

    child_code = r"""
import os
import sys
import uuid
from pathlib import Path

from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication

root = Path(sys.argv[1])
job_id = uuid.UUID(sys.argv[2])

app = AthenaApplication(settings=AthenaSettings(local_root=root))
app.start()
leased = app.jobs.acquire(
    job_id,
    worker_id="hard-kill-worker",
    lease_seconds=1,
)
assert leased.lease_token is not None
result = app.source_processing.step(
    job_id,
    lease_token=leased.lease_token,
    extend_seconds=1,
)
assert result.completed_stage == "verify"
os._exit(73)
"""

    child = subprocess.run(
        [sys.executable, "-c", child_code, str(root), str(job.job_id)],
        cwd=Path.cwd(),
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert child.returncode == 73, child.stderr

    second = _app(root)
    killed = second.jobs.get(job.job_id)
    assert killed.state is JobState.RUNNING
    assert killed.lease_expires_at_us is not None

    recovered = second.jobs.recover_startup(
        now_us=killed.lease_expires_at_us + 1,
    )
    assert [item.job_id for item in recovered] == [job.job_id]
    assert recovered[0].state is JobState.QUEUED

    resumed = second.source_processing.run_to_completion(
        job.job_id,
        worker_id="resume-after-hard-kill",
        lease_seconds=60,
    )
    assert resumed.done is True
    assert resumed.job.state is JobState.COMPLETED
    assert resumed.representation_id is not None

    representations = second.source_text.list_for_source(source.source_id)
    assert len(representations) == 1
    assert representations[0][0].representation_id == resumed.representation_id

    chunks = second.source_chunks.list_for_representation(
        resumed.representation_id
    )
    assert chunks
    assert len(second.jobs.checkpoints(job.job_id)) == 5
    second.stop()
