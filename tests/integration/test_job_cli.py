from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)
_TOKEN_RE = re.compile(r"Lease token: ([0-9a-f]{64})")


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


def test_job_cli_survives_process_restarts_and_checkpoints(tmp_path) -> None:
    local_root = tmp_path / "runtime"
    created = _run_cli(
        local_root,
        "job",
        "create",
        "source.process",
        "--priority",
        "4",
        "--scope-json",
        '{"source_id":"11111111-1111-4111-8111-111111111111"}',
        "--config-json",
        '{"pipeline_version":1}',
    )
    assert created.returncode == 0, created.stderr
    match = _UUID_RE.search(created.stdout)
    assert match is not None
    job_id = match.group(0)
    assert "State: queued" in created.stdout
    assert 'Scope: {"source_id":"11111111-1111-4111-8111-111111111111"}' in created.stdout

    leased = _run_cli(
        local_root,
        "job",
        "acquire",
        job_id,
        "--worker",
        "e2e-worker",
        "--lease-seconds",
        "60",
    )
    assert leased.returncode == 0, leased.stderr
    token_match = _TOKEN_RE.search(leased.stdout)
    assert token_match is not None
    token = token_match.group(1)
    assert "State: running" in leased.stdout
    assert "Fencing sequence: 1" in leased.stdout

    checkpointed = _run_cli(
        local_root,
        "job",
        "checkpoint",
        job_id,
        token,
        "--stage",
        "representation",
        "--progress-json",
        '{"completed_units":1}',
        "--resume-json",
        '{"next_unit":2}',
    )
    assert checkpointed.returncode == 0, checkpointed.stderr
    checkpoint_ids = _UUID_RE.findall(checkpointed.stdout)
    assert checkpoint_ids
    checkpoint_id = checkpoint_ids[0]
    assert "Fencing sequence: 1" in checkpointed.stdout

    shown = _run_cli(local_root, "job", "show", job_id)
    assert shown.returncode == 0, shown.stderr
    assert "State: running" in shown.stdout
    assert f"Checkpoint: {checkpoint_id}" in shown.stdout
    assert "Worker: e2e-worker" in shown.stdout
    assert "Lease token:" not in shown.stdout

    completed = _run_cli(local_root, "job", "complete", job_id, token)
    assert completed.returncode == 0, completed.stderr
    assert f"Job completed: {job_id}" in completed.stdout

    final = _run_cli(local_root, "job", "show", job_id)
    assert final.returncode == 0, final.stderr
    assert "State: completed" in final.stdout
    assert "Worker: <none>" in final.stdout

    checkpoints = _run_cli(local_root, "job", "checkpoints", job_id)
    assert checkpoints.returncode == 0, checkpoints.stderr
    assert checkpoint_id in checkpoints.stdout
