from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

from athena.jobs.models import JobPriority

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


def _neutralize_environmental_resource_admission(
    root: Path,
) -> None:
    """Keep checkpoint integration independent of host resource telemetry."""
    database = (
        root
        / "state"
        / "athena.db"
    )

    with sqlite3.connect(
        database
    ) as connection:
        policy_cursor = connection.execute(
            """
            UPDATE resource_policy
            SET ram_headroom_bytes = 0,
                disk_headroom_bytes = 0
            WHERE singleton_id = 1
            """
        )

        if policy_cursor.rowcount != 1:
            raise RuntimeError(
                "ATHENA resource_policy row "
                "is missing from test runtime."
            )

        # This test validates source-processing checkpoint boundaries and
        # atomic publication, not host resource admission. DATA_SAFETY is
        # deliberately exempt from ResourceManager admission checks, so the
        # isolated fixture remains deterministic even when the developer
        # machine is under genuine RAM/disk pressure.
        job_cursor = connection.execute(
            """
            UPDATE jobs
            SET priority = ?
            WHERE job_type = 'source.process'
              AND state = 'queued'
            """,
            (int(JobPriority.DATA_SAFETY),),
        )

        if job_cursor.rowcount != 1:
            raise RuntimeError(
                "Expected exactly one queued source.process "
                "job in the isolated test runtime."
            )

        connection.commit()



def _large_source(path: Path, *, sections: int = 140) -> None:
    blocks = [
        f"## Section {index:03d}\nATHENA_LARGE_CLI_SECTION_{index:03d} "
        + ("payload " * 140)
        for index in range(sections)
    ]
    path.write_text("\n\n".join(blocks), encoding="utf-8", newline="")


def _chunk_generation(root: Path) -> int:
    database = root / "derived" / "search.db"
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT chunk_generation FROM archive_search_state WHERE singleton_id = 1"
        ).fetchone()
    assert row is not None
    return int(row[0])


def test_large_source_scheduler_checkpoints_batches_and_publishes_atomically(
    tmp_path: Path,
) -> None:
    local_root = tmp_path / "runtime"
    source_file = tmp_path / "large-source.md"
    _large_source(source_file)

    imported = _run_cli(local_root, "source", "import", str(source_file))
    assert imported.returncode == 0, imported.stderr
    source_match = _UUID_RE.search(imported.stdout)
    assert source_match is not None
    source_id = source_match.group(0)
    source_file.unlink()

    queued = _run_cli(local_root, "job", "source-process", source_id)
    assert queued.returncode == 0, queued.stderr
    job_match = _UUID_RE.search(queued.stdout)
    assert job_match is not None
    job_id = job_match.group(0)
    assert '"pipeline_version":"source-process-v2"' in queued.stdout
    assert '"chunk_batch_size":32' in queued.stdout

    initialized = _run_cli(local_root, "source", "search", "ATHENA_NO_MATCH")
    assert initialized.returncode == 0, initialized.stderr
    generation_before = _chunk_generation(local_root)

    # This test validates source-processing/checkpoint semantics,
    # not the machine's instantaneous free RAM/disk state.
    _neutralize_environmental_resource_admission(
        local_root
    )

    first = _run_cli(
        local_root,
        "job",
        "scheduler-once",
        "--worker",
        "large-source-cli-a",
    )
    assert first.returncode == 0, first.stderr
    assert "Scheduler action: yielded" in first.stdout
    assert f"Job: {job_id}" in first.stdout
    assert "State: queued" in first.stdout

    checkpoints = _run_cli(local_root, "job", "checkpoints", job_id)
    assert checkpoints.returncode == 0, checkpoints.stderr
    progress_rows = []
    for line in checkpoints.stdout.splitlines():
        if " progress=" not in line or " resume=" not in line:
            continue
        payload_text = line.split(" progress=", 1)[1].split(" resume=", 1)[0]
        payload = json.loads(payload_text)
        if "confirmed_chunks" in payload:
            progress_rows.append(payload)
    confirmed = [int(item["confirmed_chunks"]) for item in progress_rows]
    assert confirmed == [0, 32, 64, 96, 128, 140]
    assert all(int(item["total_chunks"]) == 140 for item in progress_rows)
    assert '"next_stage":"chunk_publish"' in checkpoints.stdout

    # Staged chunks must remain invisible until one atomic publication boundary.
    assert _chunk_generation(local_root) == generation_before
    hidden = _run_cli(local_root, "source", "search", "ATHENA_LARGE_CLI_SECTION_139")
    assert hidden.returncode == 0, hidden.stderr
    assert "Archive search results: 0" in hidden.stdout

    second = _run_cli(
        local_root,
        "job",
        "scheduler-once",
        "--worker",
        "large-source-cli-b",
    )
    assert second.returncode == 0, second.stderr
    assert "Scheduler action: completed" in second.stdout
    assert f"Job: {job_id}" in second.stdout
    assert "State: completed" in second.stdout
    assert _chunk_generation(local_root) == generation_before + 1

    final = _run_cli(local_root, "job", "show", job_id)
    assert final.returncode == 0, final.stderr
    assert "State: completed" in final.stdout
    assert "Stage: chunks_ready" in final.stdout
    assert "Fencing sequence: 2" in final.stdout

    visible = _run_cli(local_root, "source", "search", "ATHENA_LARGE_CLI_SECTION_139")
    assert visible.returncode == 0, visible.stderr
    assert "Archive search results: 1" in visible.stdout
    assert f"source={source_id}" in visible.stdout
