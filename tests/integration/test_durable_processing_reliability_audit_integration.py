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


def test_two_scheduler_processes_consume_one_retry_budget_slot(tmp_path) -> None:
    local_root = tmp_path / "runtime"
    created = _run_cli(local_root, "job", "create", "embedding.rebuild")
    assert created.returncode == 0, created.stderr
    job_match = _UUID_RE.search(created.stdout)
    assert job_match is not None
    job_id = job_match.group(0)

    acquired = _run_cli(
        local_root,
        "job",
        "acquire",
        job_id,
        "--worker",
        "retry-race-owner",
        "--lease-seconds",
        "60",
    )
    assert acquired.returncode == 0, acquired.stderr
    token_match = _TOKEN_RE.search(acquired.stdout)
    assert token_match is not None

    waiting = _run_cli(
        local_root,
        "job",
        "wait",
        job_id,
        token_match.group(1),
        "waiting_network",
    )
    assert waiting.returncode == 0, waiting.stderr
    assert "reason=waiting_network" in waiting.stdout

    env = os.environ.copy()
    env["ATHENA_LOCAL_ROOT"] = str(local_root.resolve())
    commands = [
        [
            sys.executable,
            "-m",
            "athena",
            "job",
            "scheduler-once",
            "--worker",
            worker,
        ]
        for worker in ("retry-race-a", "retry-race-b")
    ]
    processes = [
        subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        for command in commands
    ]
    results = [process.communicate(timeout=30) for process in processes]

    for process, (_stdout, stderr) in zip(processes, results, strict=True):
        assert process.returncode == 0, stderr

    final = _run_cli(local_root, "job", "show", job_id)
    assert final.returncode == 0, final.stderr
    assert "State: waiting" in final.stdout
    assert "Blocked reason: waiting_network" in final.stdout
    assert "Retry count: 1" in final.stdout
