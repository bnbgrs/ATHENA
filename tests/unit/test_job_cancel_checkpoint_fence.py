from __future__ import annotations

from pathlib import Path

import pytest

from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.jobs.models import JobState
from athena.jobs.repository import JobLeaseError


def _app(
    local_root: Path,
) -> AthenaApplication:
    app = AthenaApplication(
        AthenaSettings(
            local_root=local_root,
        )
    )

    app.start()

    return app


def test_cancel_requested_job_cannot_commit_new_checkpoint(
    tmp_path: Path,
) -> None:
    app = _app(
        tmp_path
        / "runtime"
    )

    try:
        job = app.jobs.create(
            job_type="integrity.sweep",
            requested_scope=None,
        )

        running = app.jobs.acquire(
            job.job_id,
            worker_id="checkpoint-fence-test",
            lease_seconds=60,
        )

        assert (
            running.state
            is JobState.RUNNING
        )

        assert (
            running.lease_token
            is not None
        )

        lease_token = (
            running.lease_token
        )

        before_count = int(
            app.database.connection.execute(
                """
                SELECT COUNT(*)
                FROM checkpoints
                WHERE job_id = ?
                """,
                (
                    job.job_id.bytes,
                ),
            ).fetchone()[0]
        )

        cancelled = (
            app.jobs.request_cancel(
                job.job_id
            )
        )

        assert (
            cancelled.state
            is JobState.CANCEL_REQUESTED
        )

        # The lease intentionally still exists:
        # cancellation is cooperative for a running
        # worker, but durable publication is fenced.
        assert (
            cancelled.lease_token
            == lease_token
        )

        with pytest.raises(
            JobLeaseError,
            match=(
                "cannot checkpoint "
                "in state 'cancel_requested'"
            ),
        ):
            app.jobs.checkpoint(
                job.job_id,
                lease_token=lease_token,
                current_stage=(
                    "must-not-persist"
                ),
                progress_state={
                    "plaintext_canary": (
                        "ATHENA_CANCEL_CHECKPOINT_"
                        "CANARY_74AC"
                    ),
                },
                last_confirmed_input={
                    "plaintext_canary": (
                        "ATHENA_CANCEL_INPUT_"
                        "CANARY_74AC"
                    ),
                },
                last_confirmed_output={
                    "plaintext_canary": (
                        "ATHENA_CANCEL_OUTPUT_"
                        "CANARY_74AC"
                    ),
                },
                resume_metadata={
                    "plaintext_canary": (
                        "ATHENA_CANCEL_RESUME_"
                        "CANARY_74AC"
                    ),
                },
            )

        after_count = int(
            app.database.connection.execute(
                """
                SELECT COUNT(*)
                FROM checkpoints
                WHERE job_id = ?
                """,
                (
                    job.job_id.bytes,
                ),
            ).fetchone()[0]
        )

        assert (
            after_count
            == before_count
        )

        row = (
            app.database.connection.execute(
                """
                SELECT
                    state,
                    lease_token,
                    last_checkpoint_id,
                    current_stage
                FROM jobs
                WHERE job_id = ?
                """,
                (
                    job.job_id.bytes,
                ),
            ).fetchone()
        )

        assert row is not None

        assert (
            row["state"]
            == "cancel_requested"
        )

        assert (
            bytes(
                row["lease_token"]
            )
            == lease_token
        )

        assert (
            row[
                "last_checkpoint_id"
            ]
            is None
        )

        assert (
            row[
                "current_stage"
            ]
            is None
        )

    finally:
        app.stop()
