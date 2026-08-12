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


def test_durable_source_process_cli_builds_representation_chunks_and_search(tmp_path) -> None:
    source_file = tmp_path / "worker-source.md"
    source_file.write_text(
        "Durable pipeline Leipzig marker.\n\n" + ("long content " * 180),
        encoding="utf-8",
    )
    local_root = tmp_path / "runtime"

    imported = _run_cli(local_root, "source", "import", str(source_file))
    assert imported.returncode == 0, imported.stderr
    source_match = _UUID_RE.search(imported.stdout)
    assert source_match is not None
    source_id = source_match.group(0)
    source_file.unlink()

    queued = _run_cli(local_root, "job", "source-process", source_id, "--priority", "3")
    assert queued.returncode == 0, queued.stderr
    job_match = _UUID_RE.search(queued.stdout)
    assert job_match is not None
    job_id = job_match.group(0)
    assert "Type: source.process" in queued.stdout
    assert "State: queued" in queued.stdout
    assert f'"source_id":"{source_id}"' in queued.stdout
    assert '"pipeline_version":"source-process-v2"' in queued.stdout
    assert '"chunk_batch_size":32' in queued.stdout

    run = _run_cli(
        local_root,
        "job",
        "run-source",
        job_id,
        "--worker",
        "cli-e2e-worker",
        "--lease-seconds",
        "60",
    )
    assert run.returncode == 0, run.stderr
    assert "State: completed" in run.stdout
    assert "Completed stage: finalize" in run.stdout
    assert "Done: True" in run.stdout
    ids = _UUID_RE.findall(run.stdout)
    assert len(ids) >= 2
    representation_id = ids[-1]

    shown = _run_cli(local_root, "job", "show", job_id)
    assert shown.returncode == 0, shown.stderr
    assert "State: completed" in shown.stdout
    assert "Stage: chunks_ready" in shown.stdout

    checkpoints = _run_cli(local_root, "job", "checkpoints", job_id)
    assert checkpoints.returncode == 0, checkpoints.stderr
    assert checkpoints.stdout.count("fence=1") == 5
    assert '"next_stage":"represent"' in checkpoints.stdout
    assert '"next_stage":"chunk"' in checkpoints.stdout
    assert '"next_stage":"chunk_batch"' in checkpoints.stdout
    assert '"next_stage":"chunk_publish"' in checkpoints.stdout
    assert '"next_stage":"finalize"' in checkpoints.stdout

    representations = _run_cli(local_root, "source", "representation-list", source_id)
    assert representations.returncode == 0, representations.stderr
    assert representation_id in representations.stdout

    chunks = _run_cli(local_root, "source", "chunk-list", representation_id)
    assert chunks.returncode == 0, chunks.stderr
    assert "index=0" in chunks.stdout

    searched = _run_cli(local_root, "source", "search", "Leipzig marker")
    assert searched.returncode == 0, searched.stderr
    assert "Archive search results: 1" in searched.stdout
    assert f"source={source_id}" in searched.stdout
    assert f"representation={representation_id}" in searched.stdout
