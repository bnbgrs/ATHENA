from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)


def _run_cli(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["ATHENA_LOCAL_ROOT"] = str(root.resolve())
    return subprocess.run(
        [sys.executable, "-m", "athena", *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_durable_embedding_rebuild_cli_can_complete_empty_generation(tmp_path) -> None:
    local_root = tmp_path / "runtime"
    queued = _run_cli(
        local_root,
        "job",
        "embedding-rebuild",
        "--model",
        "fake-embed-model",
        "--batch-size",
        "4",
        "--priority",
        "4",
    )
    assert queued.returncode == 0, queued.stderr
    job_match = _UUID_RE.search(queued.stdout)
    assert job_match is not None
    job_id = job_match.group(0)
    assert "Type: embedding.rebuild" in queued.stdout
    assert "State: queued" in queued.stdout
    assert '"index_kind":"archive_source_chunks"' in queued.stdout
    assert '"model_id":"fake-embed-model"' in queued.stdout
    assert '"pipeline_version":"archive-embedding-rebuild-v1"' in queued.stdout
    assert '"target_chunk_generation":0' in queued.stdout

    run = _run_cli(
        local_root,
        "job",
        "run-embedding",
        job_id,
        "--worker",
        "cli-embedding-worker",
        "--lease-seconds",
        "60",
    )
    assert run.returncode == 0, run.stderr
    assert "State: completed" in run.stdout
    assert "Completed stage: complete" in run.stdout
    assert "Documents: 0/0" in run.stdout
    assert "Dimensions: 1" in run.stdout
    assert "Waiting: False" in run.stdout
    assert "Done: True" in run.stdout

    shown = _run_cli(local_root, "job", "show", job_id)
    assert shown.returncode == 0, shown.stderr
    assert "State: completed" in shown.stdout
    assert "Stage: embedding_index_current" in shown.stdout
    assert "Fencing sequence: 1" in shown.stdout

    checkpoints = _run_cli(local_root, "job", "checkpoints", job_id)
    assert checkpoints.returncode == 0, checkpoints.stderr
    assert checkpoints.stdout.count("fence=1") == 1
    assert '"next_stage":"complete"' in checkpoints.stdout
