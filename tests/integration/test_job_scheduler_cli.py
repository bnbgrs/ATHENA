from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

import athena.__main__ as athena_cli
from athena.jobs.scheduler import JobSchedulerError, SchedulerLane

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

def test_scheduler_run_supervisor_processes_control_lane_job(
    tmp_path,
) -> None:
    local_root = tmp_path / "runtime"
    source_file = tmp_path / "scheduler-supervisor.md"
    source_file.write_text(
        "Scheduler supervisor control-lane marker.\n",
        encoding="utf-8",
    )

    captured = _run_cli(
        local_root,
        "source",
        "import",
        str(source_file),
    )
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

    supervised = _run_cli(
        local_root,
        "job",
        "scheduler-run",
        "--worker",
        "scheduler-supervisor-e2e",
        "--max-ticks",
        "1",
    )

    assert supervised.returncode == 0, supervised.stderr
    assert "Scheduler supervisor lanes started:" in supervised.stdout
    assert (
        "Scheduler supervisor lanes completed: control, provider"
        in supervised.stdout
    )

    final = _run_cli(
        local_root,
        "job",
        "show",
        job_id,
    )
    assert final.returncode == 0, final.stderr
    assert "State: completed" in final.stdout
    assert "Fencing sequence: 1" in final.stdout

def test_scheduler_supervisor_initializes_fresh_runtime_once(
    tmp_path,
) -> None:
    local_root = tmp_path / "fresh-runtime"

    supervised = _run_cli(
        local_root,
        "job",
        "scheduler-run",
        "--worker",
        "scheduler-fresh-supervisor",
        "--max-ticks",
        "1",
    )

    assert supervised.returncode == 0, supervised.stderr
    assert "Scheduler supervisor lanes started:" in supervised.stdout
    assert (
        "Scheduler supervisor lanes completed: control, provider"
        in supervised.stdout
    )
    assert supervised.stderr.count('"event":"core.starting"') == 2

class _FakeSchedulerProcess:
    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.returncode: int | None = None
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        if self.returncode is None:
            raise AssertionError(
                "Fake scheduler process waited before termination."
            )
        return self.returncode


def test_scheduler_supervisor_cleans_control_if_provider_fails_before_ready(
    monkeypatch,
) -> None:
    control = _FakeSchedulerProcess(101)
    provider = _FakeSchedulerProcess(202)
    pending = [control, provider]

    def fake_popen(command, **kwargs):
        del command, kwargs
        if not pending:
            raise AssertionError("Supervisor started unexpected child.")
        return pending.pop(0)

    def fake_wait_ready(
        lane,
        process,
        ready_file,
    ) -> None:
        del process, ready_file
        if lane is SchedulerLane.PROVIDER:
            raise JobSchedulerError(
                "synthetic provider startup failure"
            )

    monkeypatch.setattr(
        athena_cli.subprocess,
        "Popen",
        fake_popen,
    )
    monkeypatch.setattr(
        athena_cli,
        "_wait_scheduler_child_started",
        lambda lane, process, started_file: None,
    )
    monkeypatch.setattr(
        athena_cli,
        "_wait_scheduler_child_ready",
        fake_wait_ready,
    )

    args = argparse.Namespace(
        worker="scheduler-cleanup-test",
        max_ticks=None,
    )

    with pytest.raises(
        JobSchedulerError,
        match="synthetic provider startup failure",
    ):
        athena_cli._run_scheduler_supervisor(args)

    assert control.terminated is True
    assert control.returncode == -15
    assert provider.terminated is True
    assert provider.returncode == -15

def _wait_scheduler_ready_file(
    ready_file: Path,
    process: subprocess.Popen[str],
    *,
    timeout_seconds: float = 10.0,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while not ready_file.is_file():
        returncode = process.poll()
        if returncode is not None:
            stderr = (
                process.stderr.read()
                if process.stderr is not None
                else ""
            )
            raise AssertionError(
                "Scheduler child exited before readiness: "
                f"code={returncode} stderr={stderr!r}"
            )
        if time.monotonic() >= deadline:
            raise AssertionError(
                f"Timed out waiting for {ready_file}."
            )
        time.sleep(0.02)


def test_scheduler_provider_lane_has_single_process_owner(
    tmp_path,
) -> None:
    local_root = tmp_path / "single-owner-runtime"
    first_ready = tmp_path / "provider-first.ready"
    second_ready = tmp_path / "provider-second.ready"

    env = os.environ.copy()
    env["ATHENA_LOCAL_ROOT"] = str(local_root.resolve())

    first = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "athena",
            "job",
            "scheduler-run",
            "--worker",
            "provider-owner-first",
            "--lane",
            "provider",
            "--ready-file",
            str(first_ready),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        _wait_scheduler_ready_file(
            first_ready,
            first,
        )

        second = _run_cli(
            local_root,
            "job",
            "scheduler-run",
            "--worker",
            "provider-owner-second",
            "--lane",
            "provider",
            "--ready-file",
            str(second_ready),
            "--max-ticks",
            "1",
        )

        assert second.returncode == 2
        assert (
            "Scheduler provider lane already has a live process owner."
            in second.stderr
        )
        assert not second_ready.exists()
    finally:
        if first.poll() is None:
            first.terminate()
        first.wait(timeout=10)

    released = _run_cli(
        local_root,
        "job",
        "scheduler-run",
        "--worker",
        "provider-owner-released",
        "--lane",
        "provider",
        "--max-ticks",
        "1",
    )
    assert released.returncode == 0, released.stderr


def test_scheduler_child_exits_when_supervisor_pipe_closes(
    tmp_path,
) -> None:
    local_root = tmp_path / "watchdog-runtime"
    ready_file = tmp_path / "watchdog.ready"

    env = os.environ.copy()
    env["ATHENA_LOCAL_ROOT"] = str(local_root.resolve())

    child = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "athena",
            "job",
            "scheduler-run",
            "--worker",
            "watchdog-child",
            "--lane",
            "control",
            "--ready-file",
            str(ready_file),
            "--supervisor-watchdog",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        _wait_scheduler_ready_file(
            ready_file,
            child,
        )
        assert child.stdin is not None
        child.stdin.close()
        assert child.wait(timeout=10) == 70
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)

    released = _run_cli(
        local_root,
        "job",
        "scheduler-run",
        "--worker",
        "watchdog-released",
        "--lane",
        "control",
        "--max-ticks",
        "1",
    )
    assert released.returncode == 0, released.stderr


def test_scheduler_child_ready_wait_has_bounded_timeout(
    tmp_path,
) -> None:
    process = _FakeSchedulerProcess(303)

    with pytest.raises(
        JobSchedulerError,
        match="did not become ready within",
    ):
        athena_cli._wait_scheduler_child_ready(
            SchedulerLane.CONTROL,
            process,
            tmp_path / "never-ready.flag",
            timeout_seconds=0.01,
        )

    assert process.returncode is None


def test_scheduler_child_started_wait_has_bounded_timeout(
    tmp_path,
) -> None:
    process = _FakeSchedulerProcess(404)

    with pytest.raises(
        JobSchedulerError,
        match="did not enter startup within",
    ):
        athena_cli._wait_scheduler_child_started(
            SchedulerLane.CONTROL,
            process,
            tmp_path / "never-started.flag",
            timeout_seconds=0.01,
        )

    assert process.returncode is None


def test_scheduler_start_and_ready_timeouts_are_separate() -> None:
    assert (
        athena_cli._SCHEDULER_CHILD_START_TIMEOUT_SECONDS
        == 10.0
    )
    assert (
        athena_cli._SCHEDULER_CHILD_READY_TIMEOUT_SECONDS
        > athena_cli._SCHEDULER_CHILD_START_TIMEOUT_SECONDS
    )
