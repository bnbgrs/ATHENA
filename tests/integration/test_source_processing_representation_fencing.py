from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.jobs.models import JobState
from athena.jobs.repository import JobLeaseError


def _app(root: Path) -> AthenaApplication:
    app = AthenaApplication(
        settings=AthenaSettings(local_root=root)
    )
    app.start()
    return app


def _capture(
    app: AthenaApplication,
    path: Path,
    text: str,
):
    path.write_text(
        text,
        encoding="utf-8",
        newline="",
    )
    return app.sources.capture_file(path)


_CHILD = r"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from uuid import UUID

repo_root = Path(sys.argv[1])
runtime_root = Path(sys.argv[2])
job_id = UUID(sys.argv[3])
lease_token = bytes.fromhex(sys.argv[4])
ready_path = Path(sys.argv[5])
release_path = Path(sys.argv[6])
outcome_path = Path(sys.argv[7])

sys.path.insert(
    0,
    str(repo_root / "src"),
)

from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication

app = None

try:
    app = AthenaApplication(
        settings=AthenaSettings(
            local_root=runtime_root
        )
    )
    app.start()

    store = app.source_text.representation_store
    original_extract = store.extract

    def gated_extract(path):
        prepared = original_extract(path)

        ready_path.write_text(
            "ready",
            encoding="utf-8",
        )

        deadline = time.monotonic() + 20.0
        while not release_path.exists():
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    "Timed out waiting for lease takeover."
                )
            time.sleep(0.01)

        return prepared

    store.extract = gated_extract

    try:
        app.source_processing.step(
            job_id,
            lease_token=lease_token,
            extend_seconds=60,
        )
    except Exception as exc:
        outcome_path.write_text(
            type(exc).__name__
            + "|"
            + str(exc),
            encoding="utf-8",
        )
    else:
        outcome_path.write_text(
            "NO_ERROR",
            encoding="utf-8",
        )

except Exception as exc:
    outcome_path.write_text(
        "HARNESS_ERROR|"
        + type(exc).__name__
        + "|"
        + str(exc),
        encoding="utf-8",
    )

finally:
    if app is not None:
        app.stop()
"""


def _wait_for_child_barrier(
    path: Path,
    process: subprocess.Popen[str],
) -> None:
    deadline = time.monotonic() + 20.0

    while not path.exists():
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise AssertionError(
                "Child exited before reaching representation barrier."
                f"\nstdout:\n{stdout}"
                f"\nstderr:\n{stderr}"
            )

        if time.monotonic() >= deadline:
            process.kill()
            stdout, stderr = process.communicate()
            raise AssertionError(
                "Timed out waiting for child representation barrier."
                f"\nstdout:\n{stdout}"
                f"\nstderr:\n{stderr}"
            )

        time.sleep(0.01)


def test_stale_process_cannot_publish_representation_after_real_lease_takeover(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    runtime_root = tmp_path / "runtime"

    app = _app(runtime_root)

    captured = _capture(
        app,
        tmp_path / "fenced-source.md",
        "Real multiprocess fencing marker.\n",
    )

    job = app.source_processing.enqueue(
        captured.source.source_id
    )

    stale = app.jobs.acquire(
        job.job_id,
        worker_id="stale-process",
        lease_seconds=60,
    )
    assert stale.lease_token is not None

    verified = app.source_processing.step(
        job.job_id,
        lease_token=stale.lease_token,
        extend_seconds=60,
    )
    assert verified.completed_stage == "verify"

    ready_path = tmp_path / "representation-ready"
    release_path = tmp_path / "release-stale-worker"
    outcome_path = tmp_path / "stale-outcome"

    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            _CHILD,
            str(repo_root),
            str(runtime_root),
            str(job.job_id),
            stale.lease_token.hex(),
            str(ready_path),
            str(release_path),
            str(outcome_path),
        ],
        cwd=repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        _wait_for_child_barrier(
            ready_path,
            process,
        )

        # Child has:
        # - successfully heartbeated its original lease
        # - started a real ProcessingRun
        # - parsed the real archived Source
        #
        # It is now paused before canonical representation publication.
        current = app.jobs.get(job.job_id)
        assert current.lease_expires_at_us is not None

        takeover_at = current.lease_expires_at_us + 1

        recovered = app.jobs.recover_startup(
            now_us=takeover_at
        )

        assert len(recovered) == 1
        assert recovered[0].job_id == job.job_id
        assert recovered[0].state is JobState.QUEUED

        replacement = app.jobs.acquire(
            job.job_id,
            worker_id="replacement-process",
            lease_seconds=60,
            now_us=takeover_at + 1,
        )
        assert replacement.lease_token is not None

        release_path.write_text(
            "release",
            encoding="utf-8",
        )

        try:
            stdout, stderr = process.communicate(
                timeout=20
            )
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            pytest.fail(
                "Stale child did not terminate."
                f"\nstdout:\n{stdout}"
                f"\nstderr:\n{stderr}"
            )

        assert process.returncode == 0, (
            f"stdout:\n{stdout}\n"
            f"stderr:\n{stderr}"
        )

        assert outcome_path.exists()
        outcome = outcome_path.read_text(
            encoding="utf-8"
        )

        assert outcome.startswith(
            "JobLeaseError|"
        ), outcome

        # Stale process reached actual parsing, but its canonical DB
        # transaction was fenced and rolled back.
        representation_count = (
            app.database.connection.execute(
                """
                SELECT COUNT(*)
                FROM source_representations
                WHERE source_id = ?
                """,
                (
                    captured.source.source_id.bytes,
                ),
            ).fetchone()[0]
        )
        assert representation_count == 0

        # It must not have managed to checkpoint either.
        checkpoints = app.jobs.checkpoints(
            job.job_id
        )
        assert len(checkpoints) == 1
        assert (
            app.jobs.get(job.job_id).current_stage
            == "source_verified"
        )

        # Failed stale processing attempt remains auditable.
        stale_statuses = [
            str(row[0])
            for row in app.database.connection.execute(
                """
                SELECT status
                FROM processing_runs
                ORDER BY started_at_us
                """
            ).fetchall()
        ]
        assert stale_statuses == ["failed"]

        # Replacement owner now processes the same canonical stage.
        resumed = app.source_processing.step(
            job.job_id,
            lease_token=replacement.lease_token,
            extend_seconds=60,
        )

        assert resumed.completed_stage == "represent"
        assert resumed.representation_id is not None

        representation_count = (
            app.database.connection.execute(
                """
                SELECT COUNT(*)
                FROM source_representations
                WHERE source_id = ?
                """,
                (
                    captured.source.source_id.bytes,
                ),
            ).fetchone()[0]
        )
        assert representation_count == 1

        statuses = sorted(
            str(row[0])
            for row in app.database.connection.execute(
                """
                SELECT status
                FROM processing_runs
                """
            ).fetchall()
        )
        assert statuses == [
            "failed",
            "succeeded",
        ]

        # Exactly one representation checkpoint now exists in addition
        # to the original source verification checkpoint.
        checkpoints = app.jobs.checkpoints(
            job.job_id
        )
        assert len(checkpoints) == 2

    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()
        app.stop()


def test_cancel_during_representation_build_blocks_canonical_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _app(
        tmp_path / "runtime"
    )

    try:
        captured = _capture(
            app,
            tmp_path / "cancel-source.md",
            "Cancellation fencing marker.\n",
        )

        job = app.source_processing.enqueue(
            captured.source.source_id
        )

        leased = app.jobs.acquire(
            job.job_id,
            worker_id="cancel-worker",
            lease_seconds=60,
        )
        assert leased.lease_token is not None

        verified = app.source_processing.step(
            job.job_id,
            lease_token=leased.lease_token,
            extend_seconds=60,
        )
        assert verified.completed_stage == "verify"

        store = app.source_text.representation_store
        original_extract = store.extract

        def extract_then_cancel(path):
            prepared = original_extract(path)
            app.jobs.request_cancel(
                job.job_id
            )
            return prepared

        monkeypatch.setattr(
            store,
            "extract",
            extract_then_cancel,
        )

        with pytest.raises(JobLeaseError):
            app.source_processing.step(
                job.job_id,
                lease_token=leased.lease_token,
                extend_seconds=60,
            )

        count = app.database.connection.execute(
            """
            SELECT COUNT(*)
            FROM source_representations
            WHERE source_id = ?
            """,
            (
                captured.source.source_id.bytes,
            ),
        ).fetchone()[0]

        assert count == 0

        current = app.jobs.get(
            job.job_id
        )
        assert (
            current.state
            is JobState.CANCEL_REQUESTED
        )

        cancelled = app.source_processing.step(
            job.job_id,
            lease_token=leased.lease_token,
            extend_seconds=60,
        )

        assert cancelled.done is True
        assert (
            cancelled.job.state
            is JobState.CANCELLED
        )

        count = app.database.connection.execute(
            """
            SELECT COUNT(*)
            FROM source_representations
            WHERE source_id = ?
            """,
            (
                captured.source.source_id.bytes,
            ),
        ).fetchone()[0]

        assert count == 0

    finally:
        app.stop()
