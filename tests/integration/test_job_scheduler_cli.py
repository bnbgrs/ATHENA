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


def test_scheduler_once_automatically_processes_queued_source_job(tmp_path) -> None:
    local_root = tmp_path / "runtime"
    source_file = tmp_path / "scheduler-cli.md"
    source_file.write_text("Scheduler CLI durable source marker.\n", encoding="utf-8")

    captured = _run_cli(local_root, "source", "import", str(source_file))
    assert captured.returncode == 0, captured.stderr
    source_match = _UUID_RE.search(captured.stdout)
    assert source_match is not None

    queued = _run_cli(
        local_root,
        "job",
        "source-process",
        source_match.group(0),
    )
    assert queued.returncode == 0, queued.stderr
    job_match = _UUID_RE.search(queued.stdout)
    assert job_match is not None
    job_id = job_match.group(0)
    assert "State: queued" in queued.stdout

    scheduled = _run_cli(
        local_root,
        "job",
        "scheduler-once",
        "--worker",
        "scheduler-cli-e2e",
    )
    assert scheduled.returncode == 0, scheduled.stderr
    assert "Scheduler action: completed" in scheduled.stdout
    assert f"Job: {job_id}" in scheduled.stdout
    assert "State: completed" in scheduled.stdout
    assert "Fencing sequence: 1" in scheduled.stdout

    final = _run_cli(local_root, "job", "show", job_id)
    assert final.returncode == 0, final.stderr
    assert "State: completed" in final.stdout
    assert "Worker: <none>" in final.stdout


def test_scheduler_drain_leaves_unimplemented_registered_job_visible(tmp_path) -> None:
    local_root = tmp_path / "runtime"
    created = _run_cli(
        local_root,
        "job",
        "create",
        "integrity.sweep",
        "--priority",
        "0",
    )
    assert created.returncode == 0, created.stderr
    job_match = _UUID_RE.search(created.stdout)
    assert job_match is not None

    drained = _run_cli(
        local_root,
        "job",
        "scheduler-drain",
        "--worker",
        "scheduler-cli-e2e",
        "--max-jobs",
        "5",
    )
    assert drained.returncode == 0, drained.stderr
    assert "Dispatched jobs: 0" in drained.stdout
    assert "Idle: True" in drained.stdout

    shown = _run_cli(local_root, "job", "show", job_match.group(0))
    assert shown.returncode == 0, shown.stderr
    assert "State: queued" in shown.stdout


def test_two_scheduler_processes_do_not_double_dispatch_one_job(tmp_path) -> None:
    local_root = tmp_path / "runtime"
    source_file = tmp_path / "scheduler-race.md"
    source_file.write_text("Scheduler race durable marker.\n", encoding="utf-8")

    captured = _run_cli(local_root, "source", "import", str(source_file))
    assert captured.returncode == 0, captured.stderr
    source_match = _UUID_RE.search(captured.stdout)
    assert source_match is not None
    queued = _run_cli(
        local_root,
        "job",
        "source-process",
        source_match.group(0),
    )
    assert queued.returncode == 0, queued.stderr
    job_match = _UUID_RE.search(queued.stdout)
    assert job_match is not None
    job_id = job_match.group(0)

    env = os.environ.copy()
    env["ATHENA_LOCAL_ROOT"] = str(local_root.resolve())
    command_a = [
        sys.executable,
        "-m",
        "athena",
        "job",
        "scheduler-once",
        "--worker",
        "scheduler-race-a",
    ]
    command_b = [
        sys.executable,
        "-m",
        "athena",
        "job",
        "scheduler-once",
        "--worker",
        "scheduler-race-b",
    ]
    process_a = subprocess.Popen(
        command_a,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    process_b = subprocess.Popen(
        command_b,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    stdout_a, stderr_a = process_a.communicate(timeout=30)
    stdout_b, stderr_b = process_b.communicate(timeout=30)

    assert process_a.returncode == 0, stderr_a
    assert process_b.returncode == 0, stderr_b
    outputs = (stdout_a, stdout_b)
    assert sum("Scheduler action: completed" in output for output in outputs) == 1
    assert sum("Scheduler action: idle" in output for output in outputs) == 1

    final = _run_cli(local_root, "job", "show", job_id)
    assert final.returncode == 0, final.stderr
    assert "State: completed" in final.stdout
    assert "Fencing sequence: 1" in final.stdout
