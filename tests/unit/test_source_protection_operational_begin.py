from __future__ import annotations

from pathlib import Path

import pytest

from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.jobs.models import (
    JobState,
    WaitingReason,
)
from athena.jobs.repository import (
    JobSourceProtectionFenceError,
)
from athena.security.models import (
    Argon2idParameters,
)
from athena.source.protection_transition import (
    SourceProtectionOperationalBlockerError,
    SourceProtectionTransitionState,
)

_TEST_KDF = Argon2idParameters(
    iterations=1,
    lanes=1,
    memory_cost_kib=8 * 1024,
    length=32,
)


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


def _scope(
    app: AthenaApplication,
    *,
    password: bytes,
):
    app.protected_content.initialize_password(
        password,
        parameters=_TEST_KDF,
    )

    scope = (
        app.protected_content
        .create_scope(
            password,
            neutral_label=(
                "atomic-operational-begin"
            ),
        )
    )

    app.protected_content.unlock_scope(
        scope.protection_scope_id,
        password,
    )

    return scope


def test_waiting_job_is_protected_before_raw_source_transition_prepares(
    tmp_path: Path,
) -> None:
    source_path = (
        tmp_path
        / "waiting-atomic-source.txt"
    )

    source_path.write_bytes(
        b"ATHENA_ATOMIC_WAITING_SOURCE_91D2"
    )

    app = _app(
        tmp_path
        / "runtime"
    )

    try:
        scope = _scope(
            app,
            password=(
                b"atomic-waiting-password"
            ),
        )

        captured = (
            app.sources.capture_file(
                source_path
            )
        )

        job = app.jobs.create(
            job_type="source.process",
            requested_scope={
                "source_id": str(
                    captured.source.source_id
                ),
                "canary": (
                    "ATHENA_ATOMIC_JOB_SCOPE_91D2"
                ),
            },
            pinned_configuration={
                "canary": (
                    "ATHENA_ATOMIC_JOB_CONFIG_91D2"
                ),
            },
        )

        running = app.jobs.acquire(
            job.job_id,
            worker_id=(
                "atomic-waiting-worker"
            ),
            lease_seconds=60,
        )

        assert (
            running.lease_token
            is not None
        )

        checkpoints = []

        for index in range(3):
            checkpoints.append(
                app.jobs.checkpoint(
                    job.job_id,
                    lease_token=(
                        running.lease_token
                    ),
                    current_stage=(
                        f"checkpoint-{index}"
                    ),
                    progress_state={
                        "canary": (
                            "ATHENA_ATOMIC_"
                            f"CHECKPOINT_{index}_91D2"
                        ),
                    },
                    resume_metadata={
                        "source_id": str(
                            captured
                            .source
                            .source_id
                        ),
                    },
                )
            )

        waiting = (
            app.job_repository.wait(
                job_id=job.job_id,
                lease_token=(
                    running.lease_token
                ),
                reason=(
                    WaitingReason.DEPENDENCY
                ),
            )
        )

        assert (
            waiting.state
            is JobState.WAITING
        )

        protected = (
            app.sources
            .protect_existing_source(
                captured.source.source_id,
                scope.protection_scope_id,
            )
        )

        assert (
            protected.source
            .protection_scope_id
            == scope.protection_scope_id
        )

        migrated_job = (
            app.jobs.get(
                job.job_id
            )
        )

        assert (
            migrated_job.state
            is JobState.CANCELLED
        )

        assert (
            migrated_job
            .requested_scope_json
            is None
        )

        assert (
            migrated_job
            .pinned_configuration_json
            is None
        )

        assert (
            migrated_job
            .protection_scope_id
            == scope.protection_scope_id
        )

        assert (
            migrated_job
            .protected_payload_id
            is not None
        )

        for checkpoint in checkpoints:
            stored = (
                app.job_repository
                .get_checkpoint(
                    checkpoint
                    .checkpoint_id
                )
            )

            assert (
                stored
                .progress_state_json
                is None
            )

            assert (
                stored
                .resume_metadata_json
                is None
            )

            assert (
                stored
                .protection_scope_id
                == scope
                .protection_scope_id
            )

            assert (
                stored
                .protected_payload_id
                is not None
            )

        assert (
            app.source_protection_repository
            .get_for_source(
                captured.source.source_id
            )
            is None
        )

    finally:
        app.stop()


def test_running_job_commits_pending_guard_then_retry_completes_after_ack(
    tmp_path: Path,
) -> None:
    source_path = (
        tmp_path
        / "running-atomic-source.txt"
    )

    source_path.write_bytes(
        b"ATHENA_ATOMIC_RUNNING_SOURCE_6F20"
    )

    app = _app(
        tmp_path
        / "runtime"
    )

    try:
        scope = _scope(
            app,
            password=(
                b"atomic-running-password"
            ),
        )

        captured = (
            app.sources.capture_file(
                source_path
            )
        )

        job = app.jobs.create(
            job_type="source.process",
            requested_scope={
                "source_id": str(
                    captured.source.source_id
                ),
                "canary": (
                    "ATHENA_ATOMIC_RUNNING_SCOPE_6F20"
                ),
            },
        )

        running = app.jobs.acquire(
            job.job_id,
            worker_id=(
                "atomic-running-worker"
            ),
            lease_seconds=60,
        )

        assert (
            running.lease_token
            is not None
        )

        lease_token = (
            running.lease_token
        )

        checkpoint = (
            app.jobs.checkpoint(
                job.job_id,
                lease_token=lease_token,
                current_stage=(
                    "running-before-protection"
                ),
                resume_metadata={
                    "canary": (
                        "ATHENA_ATOMIC_RUNNING_"
                        "CHECKPOINT_6F20"
                    ),
                },
            )
        )

        with pytest.raises(
            SourceProtectionOperationalBlockerError,
            match=(
                "pending until running "
                "dependent jobs"
            ),
        ):
            app.sources.protect_existing_source(
                captured.source.source_id,
                scope.protection_scope_id,
            )

        transition = (
            app.source_protection_repository
            .get_for_source(
                captured.source.source_id
            )
        )

        assert transition is not None

        assert (
            transition.state
            is SourceProtectionTransitionState.PENDING
        )

        blocked = app.jobs.get(
            job.job_id
        )

        assert (
            blocked.state
            is JobState.CANCEL_REQUESTED
        )

        # Running worker state remains temporarily
        # readable until cancellation acknowledgment.
        assert (
            blocked.requested_scope_json
            is not None
        )

        stored_checkpoint = (
            app.job_repository
            .get_checkpoint(
                checkpoint.checkpoint_id
            )
        )

        assert (
            stored_checkpoint
            .resume_metadata_json
            is not None
        )

        # pending is already durable, therefore new
        # jobs cannot race into the protection window.
        with pytest.raises(
            JobSourceProtectionFenceError
        ):
            app.jobs.create(
                job_type="source.process",
                requested_scope={
                    "source_id": str(
                        captured.source.source_id
                    ),
                },
            )

        cancelled = (
            app.jobs.acknowledge_cancel(
                job.job_id,
                lease_token=lease_token,
            )
        )

        assert (
            cancelled.state
            is JobState.CANCELLED
        )

        protected = (
            app.sources
            .protect_existing_source(
                captured.source.source_id,
                scope.protection_scope_id,
            )
        )

        assert (
            protected.source
            .protection_scope_id
            == scope.protection_scope_id
        )

        migrated = app.jobs.get(
            job.job_id
        )

        assert (
            migrated.state
            is JobState.CANCELLED
        )

        assert (
            migrated.requested_scope_json
            is None
        )

        assert (
            migrated.protected_payload_id
            is not None
        )

        migrated_checkpoint = (
            app.job_repository
            .get_checkpoint(
                checkpoint.checkpoint_id
            )
        )

        assert (
            migrated_checkpoint
            .resume_metadata_json
            is None
        )

        assert (
            migrated_checkpoint
            .protected_payload_id
            is not None
        )

        assert (
            app.source_protection_repository
            .get_for_source(
                captured.source.source_id
            )
            is None
        )

    finally:
        app.stop()


def test_begin_callback_failure_rolls_back_pending_and_job_fence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_path = (
        tmp_path
        / "rollback-atomic-source.txt"
    )

    source_path.write_bytes(
        b"ATHENA_ATOMIC_BEGIN_ROLLBACK_B83D"
    )

    app = _app(
        tmp_path
        / "runtime"
    )

    class SyntheticCutoverFailure(
        RuntimeError
    ):
        pass

    try:
        scope = _scope(
            app,
            password=(
                b"atomic-rollback-password"
            ),
        )

        captured = (
            app.sources.capture_file(
                source_path
            )
        )

        job = app.jobs.create(
            job_type="source.process",
            requested_scope={
                "source_id": str(
                    captured.source.source_id
                ),
            },
        )

        def fail_cutover(
            *args: object,
            **kwargs: object,
        ) -> object:
            del args, kwargs

            raise SyntheticCutoverFailure(
                "synthetic operational "
                "cutover failure"
            )

        monkeypatch.setattr(
            app.job_repository,
            "protect_source_dependency_payloads",
            fail_cutover,
        )

        with pytest.raises(
            SyntheticCutoverFailure
        ):
            app.sources.protect_existing_source(
                captured.source.source_id,
                scope.protection_scope_id,
            )

        assert (
            app.source_protection_repository
            .get_for_source(
                captured.source.source_id
            )
            is None
        )

        restored = app.jobs.get(
            job.job_id
        )

        assert (
            restored.state
            is JobState.QUEUED
        )

        assert (
            restored.requested_scope_json
            is not None
        )

        assert (
            restored.protected_payload_id
            is None
        )

    finally:
        app.stop()
