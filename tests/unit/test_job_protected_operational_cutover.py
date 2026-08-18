from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path

import pytest

from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.jobs.models import JobState, WaitingReason
from athena.jobs.repository import JobLeaseError
from athena.security.models import Argon2idParameters

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
        app.protected_content.create_scope(
            password,
            neutral_label=(
                "operational-cutover-test"
            ),
        )
    )

    app.protected_content.unlock_scope(
        scope.protection_scope_id,
        password,
    )

    return scope


def _writer(
    app: AthenaApplication,
    protection_scope_id: uuid.UUID,
):
    def write(
        connection: sqlite3.Connection,
        plaintext: bytes,
    ) -> uuid.UUID:
        record = (
            app.protected_content
            .prepare_payload(
                protection_scope_id,
                plaintext,
            )
        )

        app.protection_repository.insert_payload_in_transaction(
            connection,
            record,
        )

        return (
            record.protected_payload_id
        )

    return write


def _payload(
    app: AthenaApplication,
    payload_id: bytes,
) -> dict[str, object]:
    decoded = json.loads(
        app.protected_content
        .load_payload(
            uuid.UUID(
                bytes=bytes(
                    payload_id
                )
            )
        )
        .decode("utf-8")
    )

    assert isinstance(
        decoded,
        dict,
    )

    return decoded


def test_waiting_source_job_and_checkpoints_are_protected_atomically(
    tmp_path: Path,
) -> None:
    source_path = (
        tmp_path
        / "waiting-source.txt"
    )

    source_path.write_bytes(
        b"ATHENA_OPERATIONAL_WAITING_CANARY_D391"
    )

    app = _app(
        tmp_path
        / "runtime"
    )

    try:
        scope = _scope(
            app,
            password=(
                b"operational-waiting-password"
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
                    "ATHENA_JOB_SCOPE_CANARY_D391"
                ),
            },
            pinned_configuration={
                "canary": (
                    "ATHENA_JOB_CONFIG_CANARY_D391"
                ),
            },
        )

        running = app.jobs.acquire(
            job.job_id,
            worker_id="operational-cutover",
            lease_seconds=60,
        )

        assert (
            running.lease_token
            is not None
        )

        checkpoint = app.jobs.checkpoint(
            job.job_id,
            lease_token=running.lease_token,
            current_stage="source_verified",
            progress_state={
                "canary": (
                    "ATHENA_PROGRESS_CANARY_D391"
                ),
            },
            last_confirmed_input={
                "canary": (
                    "ATHENA_INPUT_CANARY_D391"
                ),
            },
            last_confirmed_output={
                "canary": (
                    "ATHENA_OUTPUT_CANARY_D391"
                ),
            },
            resume_metadata={
                "canary": (
                    "ATHENA_RESUME_CANARY_D391"
                ),
            },
        )

        waiting = (
            app.jobs.repository.wait(
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

        with (
            app.database.write_transaction()
            as connection
        ):
            migrated, blockers = (
                app.job_repository
                .protect_source_dependency_payloads(
                    connection,
                    source_id=(
                        captured.source.source_id
                    ),
                    protection_scope_id=(
                        scope.protection_scope_id
                    ),
                    payload_writer=_writer(
                        app,
                        scope.protection_scope_id,
                    ),
                )
            )

            assert migrated == (
                job.job_id,
            )

            assert blockers == ()

            job_row = connection.execute(
                """
                SELECT *
                FROM jobs
                WHERE job_id = ?
                """,
                (
                    job.job_id.bytes,
                ),
            ).fetchone()

            assert job_row is not None
            assert (
                job_row["state"]
                == "cancelled"
            )

            assert (
                job_row[
                    "requested_scope_json"
                ]
                is None
            )

            assert (
                job_row[
                    "pinned_configuration_json"
                ]
                is None
            )

            assert (
                job_row[
                    "blocked_reason"
                ]
                is None
            )

            assert (
                job_row[
                    "protection_scope_id"
                ]
                == scope
                .protection_scope_id
                .bytes
            )

            assert (
                job_row[
                    "protected_payload_id"
                ]
                is not None
            )

            checkpoint_row = (
                connection.execute(
                    """
                    SELECT *
                    FROM checkpoints
                    WHERE checkpoint_id = ?
                    """,
                    (
                        checkpoint
                        .checkpoint_id
                        .bytes,
                    ),
                ).fetchone()
            )

            assert checkpoint_row is not None

            for column in (
                "progress_state_json",
                "last_confirmed_input_json",
                "last_confirmed_output_json",
                "resume_metadata_json",
            ):
                assert (
                    checkpoint_row[column]
                    is None
                )

            assert (
                checkpoint_row[
                    "protection_scope_id"
                ]
                == scope
                .protection_scope_id
                .bytes
            )

            assert (
                checkpoint_row[
                    "protected_payload_id"
                ]
                is not None
            )

            job_payload_id = bytes(
                job_row[
                    "protected_payload_id"
                ]
            )

            checkpoint_payload_id = (
                bytes(
                    checkpoint_row[
                        "protected_payload_id"
                    ]
                )
            )

        protected_job = _payload(
            app,
            job_payload_id,
        )

        protected_checkpoint = _payload(
            app,
            checkpoint_payload_id,
        )

        assert (
            protected_job[
                "payload_type"
            ]
            == "athena.job.operational.v1"
        )

        job_values = (
            protected_job["values"]
        )

        assert isinstance(
            job_values,
            dict,
        )

        assert (
            "ATHENA_JOB_SCOPE_CANARY_D391"
            in str(
                job_values[
                    "requested_scope_json"
                ]
            )
        )

        assert (
            "ATHENA_JOB_CONFIG_CANARY_D391"
            in str(
                job_values[
                    "pinned_configuration_json"
                ]
            )
        )

        assert (
            protected_checkpoint[
                "payload_type"
            ]
            == (
                "athena.checkpoint."
                "operational.v1"
            )
        )

        checkpoint_values = (
            protected_checkpoint[
                "values"
            ]
        )

        assert isinstance(
            checkpoint_values,
            dict,
        )

        for canary in (
            "ATHENA_PROGRESS_CANARY_D391",
            "ATHENA_INPUT_CANARY_D391",
            "ATHENA_OUTPUT_CANARY_D391",
            "ATHENA_RESUME_CANARY_D391",
        ):
            assert canary in str(
                checkpoint_values
            )

    finally:
        app.stop()


def test_running_source_job_is_fenced_but_not_scrubbed_until_terminal(
    tmp_path: Path,
) -> None:
    source_path = (
        tmp_path
        / "running-source.txt"
    )

    source_path.write_bytes(
        b"ATHENA_OPERATIONAL_RUNNING_CANARY_55E2"
    )

    app = _app(
        tmp_path
        / "runtime"
    )

    try:
        scope = _scope(
            app,
            password=(
                b"operational-running-password"
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
                    "ATHENA_RUNNING_SCOPE_CANARY_55E2"
                ),
            },
        )

        running = app.jobs.acquire(
            job.job_id,
            worker_id="running-cutover",
            lease_seconds=60,
        )

        assert (
            running.lease_token
            is not None
        )

        lease_token = (
            running.lease_token
        )

        checkpoint = app.jobs.checkpoint(
            job.job_id,
            lease_token=lease_token,
            current_stage="source_verified",
            resume_metadata={
                "canary": (
                    "ATHENA_RUNNING_CHECKPOINT_CANARY_55E2"
                ),
            },
        )

        with (
            app.database.write_transaction()
            as connection
        ):
            migrated, blockers = (
                app.job_repository
                .protect_source_dependency_payloads(
                    connection,
                    source_id=(
                        captured.source.source_id
                    ),
                    protection_scope_id=(
                        scope.protection_scope_id
                    ),
                    payload_writer=_writer(
                        app,
                        scope.protection_scope_id,
                    ),
                )
            )

            assert migrated == ()

            assert blockers == (
                job.job_id,
            )

        blocked = app.jobs.get(
            job.job_id
        )

        assert (
            blocked.state
            is JobState.CANCEL_REQUESTED
        )

        # Scope remains temporarily readable while
        # worker lease ownership must still be able
        # to validate and acknowledge cancellation.
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

        with pytest.raises(
            JobLeaseError
        ):
            app.jobs.checkpoint(
                job.job_id,
                lease_token=lease_token,
                current_stage=(
                    "must-not-persist"
                ),
                progress_state={
                    "canary": (
                        "ATHENA_FORBIDDEN_"
                        "POST_CANCEL_CANARY_55E2"
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

        with (
            app.database.write_transaction()
            as connection
        ):
            migrated, blockers = (
                app.job_repository
                .protect_source_dependency_payloads(
                    connection,
                    source_id=(
                        captured.source.source_id
                    ),
                    protection_scope_id=(
                        scope.protection_scope_id
                    ),
                    payload_writer=_writer(
                        app,
                        scope.protection_scope_id,
                    ),
                )
            )

            assert migrated == (
                job.job_id,
            )

            assert blockers == ()

        protected = app.jobs.get(
            job.job_id
        )

        assert (
            protected.requested_scope_json
            is None
        )

        assert (
            protected.protection_scope_id
            == scope.protection_scope_id
        )

        protected_checkpoint = (
            app.job_repository
            .get_checkpoint(
                checkpoint.checkpoint_id
            )
        )

        assert (
            protected_checkpoint
            .resume_metadata_json
            is None
        )

        assert (
            protected_checkpoint
            .protection_scope_id
            == scope.protection_scope_id
        )

    finally:
        app.stop()


def test_operational_cutover_rolls_back_job_checkpoint_and_ciphertext_together(
    tmp_path: Path,
) -> None:
    source_path = (
        tmp_path
        / "rollback-source.txt"
    )

    source_path.write_bytes(
        b"ATHENA_OPERATIONAL_ROLLBACK_CANARY_719C"
    )

    app = _app(
        tmp_path
        / "runtime"
    )

    class SyntheticRollback(
        RuntimeError
    ):
        pass

    try:
        scope = _scope(
            app,
            password=(
                b"operational-rollback-password"
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
                    "ATHENA_ROLLBACK_SCOPE_CANARY_719C"
                ),
            },
        )

        running = app.jobs.acquire(
            job.job_id,
            worker_id="rollback-worker",
            lease_seconds=60,
        )

        assert (
            running.lease_token
            is not None
        )

        checkpoint = app.jobs.checkpoint(
            job.job_id,
            lease_token=(
                running.lease_token
            ),
            current_stage="source_verified",
            resume_metadata={
                "canary": (
                    "ATHENA_ROLLBACK_CHECKPOINT_CANARY_719C"
                ),
            },
        )

        app.jobs.repository.wait(
            job_id=job.job_id,
            lease_token=(
                running.lease_token
            ),
            reason=(
                WaitingReason.DEPENDENCY
            ),
        )

        before_payloads = int(
            app.database.connection.execute(
                """
                SELECT COUNT(*)
                FROM protected_payloads
                """
            ).fetchone()[0]
        )

        with pytest.raises(
            SyntheticRollback
        ):
            with (
                app.database
                .write_transaction()
                as connection
            ):
                migrated, blockers = (
                    app.job_repository
                    .protect_source_dependency_payloads(
                        connection,
                        source_id=(
                            captured.source.source_id
                        ),
                        protection_scope_id=(
                            scope.protection_scope_id
                        ),
                        payload_writer=_writer(
                            app,
                            scope.protection_scope_id,
                        ),
                    )
                )

                assert migrated == (
                    job.job_id,
                )

                assert blockers == ()

                raise SyntheticRollback(
                    "rollback complete "
                    "operational cutover"
                )

        restored_job = app.jobs.get(
            job.job_id
        )

        assert (
            restored_job.state
            is JobState.WAITING
        )

        assert (
            restored_job
            .requested_scope_json
            is not None
        )

        assert (
            restored_job
            .protected_payload_id
            is None
        )

        restored_checkpoint = (
            app.job_repository
            .get_checkpoint(
                checkpoint.checkpoint_id
            )
        )

        assert (
            restored_checkpoint
            .resume_metadata_json
            is not None
        )

        assert (
            restored_checkpoint
            .protected_payload_id
            is None
        )

        after_payloads = int(
            app.database.connection.execute(
                """
                SELECT COUNT(*)
                FROM protected_payloads
                """
            ).fetchone()[0]
        )

        assert (
            after_payloads
            == before_payloads
        )

    finally:
        app.stop()
