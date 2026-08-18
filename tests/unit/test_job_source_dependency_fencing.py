from __future__ import annotations

from pathlib import Path

import pytest

from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.jobs.models import JobState, WaitingReason
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


def test_source_dependency_fence_cancels_waiting_and_fences_running_job(
    tmp_path: Path,
) -> None:
    first_source_path = (
        tmp_path
        / "protected-target.txt"
    )

    second_source_path = (
        tmp_path
        / "unrelated-source.txt"
    )

    first_source_path.write_bytes(
        b"ATHENA_SOURCE_DEPENDENCY_FENCE_TARGET_A91E"
    )

    second_source_path.write_bytes(
        b"ATHENA_SOURCE_DEPENDENCY_FENCE_OTHER_B72F"
    )

    app = _app(
        tmp_path
        / "runtime"
    )

    try:
        target = (
            app.sources.capture_file(
                first_source_path
            )
        )

        unrelated_source = (
            app.sources.capture_file(
                second_source_path
            )
        )

        waiting_job = app.jobs.create(
            job_type="source.process",
            requested_scope={
                "source_id": str(
                    target.source.source_id
                ),
            },
        )

        waiting_running = app.jobs.acquire(
            waiting_job.job_id,
            worker_id="waiting-worker",
            lease_seconds=60,
        )

        assert (
            waiting_running.lease_token
            is not None
        )

        waiting = app.jobs.repository.wait(
            job_id=waiting_job.job_id,
            lease_token=waiting_running.lease_token,
            reason=WaitingReason.DEPENDENCY,
        )

        assert (
            waiting.state
            is JobState.WAITING
        )

        running_job = app.jobs.create(
            job_type="source.process",
            requested_scope={
                "source_id": str(
                    target.source.source_id
                ),
            },
        )

        running = app.jobs.acquire(
            running_job.job_id,
            worker_id="running-worker",
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

        running_lease = (
            running.lease_token
        )

        unrelated = app.jobs.create(
            job_type="source.process",
            requested_scope={
                "source_id": str(
                    unrelated_source.source.source_id
                ),
            },
        )

        before_unrelated = (
            app.jobs.get(
                unrelated.job_id
            )
        )

        assert (
            before_unrelated.state
            is JobState.QUEUED
        )

        with app.database.write_transaction() as connection:
            fenced_ids = (
                app.jobs.repository.fence_source_dependencies(
                    connection,
                    source_id=(
                        target.source.source_id
                    ),
                )
            )

            assert set(
                fenced_ids
            ) == {
                waiting_job.job_id,
                running_job.job_id,
            }

            # Verify inside the SAME transaction. This is
            # the contract needed later by Protection.begin().
            waiting_row = connection.execute(
                """
                SELECT
                    state,
                    lease_token
                FROM jobs
                WHERE job_id = ?
                """,
                (
                    waiting_job.job_id.bytes,
                ),
            ).fetchone()

            running_row = connection.execute(
                """
                SELECT
                    state,
                    lease_token
                FROM jobs
                WHERE job_id = ?
                """,
                (
                    running_job.job_id.bytes,
                ),
            ).fetchone()

            unrelated_row = connection.execute(
                """
                SELECT state
                FROM jobs
                WHERE job_id = ?
                """,
                (
                    unrelated.job_id.bytes,
                ),
            ).fetchone()

            assert waiting_row is not None
            assert running_row is not None
            assert unrelated_row is not None

            assert (
                waiting_row["state"]
                == "cancelled"
            )

            assert (
                waiting_row["lease_token"]
                is None
            )

            assert (
                running_row["state"]
                == "cancel_requested"
            )

            assert (
                bytes(
                    running_row["lease_token"]
                )
                == running_lease
            )

            assert (
                unrelated_row["state"]
                == "queued"
            )

        waiting_after = app.jobs.get(
            waiting_job.job_id
        )

        running_after = app.jobs.get(
            running_job.job_id
        )

        unrelated_after = app.jobs.get(
            unrelated.job_id
        )

        assert (
            waiting_after.state
            is JobState.CANCELLED
        )

        assert (
            running_after.state
            is JobState.CANCEL_REQUESTED
        )

        assert (
            running_after.lease_token
            == running_lease
        )

        assert (
            unrelated_after.state
            is JobState.QUEUED
        )

        # The running worker still owns its lease so it
        # can acknowledge cancellation, but it may no
        # longer persist a checkpoint.
        with pytest.raises(
            JobLeaseError
        ):
            app.jobs.checkpoint(
                running_job.job_id,
                lease_token=running_lease,
                current_stage=(
                    "must-not-persist"
                ),
                progress_state={
                    "canary": (
                        "ATHENA_SOURCE_DEPENDENCY_"
                        "CHECKPOINT_CANARY_A91E"
                    ),
                },
            )

        acknowledged = (
            app.jobs.acknowledge_cancel(
                running_job.job_id,
                lease_token=running_lease,
            )
        )

        assert (
            acknowledged.state
            is JobState.CANCELLED
        )

        assert (
            acknowledged.lease_token
            is None
        )

    finally:
        app.stop()


def test_source_dependency_fence_requires_existing_transaction(
    tmp_path: Path,
) -> None:
    source_path = (
        tmp_path
        / "transaction-required.txt"
    )

    source_path.write_bytes(
        b"ATHENA_TRANSACTION_REQUIRED_FENCE_49B2"
    )

    app = _app(
        tmp_path
        / "runtime"
    )

    try:
        captured = (
            app.sources.capture_file(
                source_path
            )
        )

        with pytest.raises(
            RuntimeError,
            match=(
                "requires an active transaction"
            ),
        ):
            app.jobs.repository.fence_source_dependencies(
                app.database.connection,
                source_id=(
                    captured.source.source_id
                ),
            )

    finally:
        app.stop()
