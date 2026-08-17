from __future__ import annotations

import json

from athena.backup.target_lock import backup_target_lock
from athena.common.ids import uuid_to_blob
from athena.common.time import utc_now_us
from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.jobs.backup import (
    _DAY_US,
    BACKUP_CREATE_JOB_TYPE,
    daily_backup_slot_us,
)
from athena.jobs.models import JobState


def _app(tmp_path) -> AthenaApplication:
    app = AthenaApplication(
        settings=AthenaSettings(
            local_root=tmp_path / "runtime",
        )
    )
    app.start()
    return app


def _complete_snapshot_count(
    app: AthenaApplication,
    target_id,
) -> int:
    row = app.database.connection.execute(
        """
        SELECT COUNT(*)
        FROM backup_snapshots
        WHERE target_id = ?
          AND state = 'complete'
        """,
        (uuid_to_blob(target_id),),
    ).fetchone()

    assert row is not None
    return int(row[0])


def test_daily_backup_slot_is_deterministic_utc() -> None:
    day_us = 86_400_000_000
    hour_us = 3_600_000_000

    before_quiet = 10 * day_us + 2 * hour_us
    after_quiet = 10 * day_us + 4 * hour_us

    assert daily_backup_slot_us(
        before_quiet,
        quiet_hour_utc=3,
    ) == 9 * day_us + 3 * hour_us

    assert daily_backup_slot_us(
        after_quiet,
        quiet_hour_utc=3,
    ) == 10 * day_us + 3 * hour_us


def test_due_target_gets_one_catchup_job_without_duplicates(
    tmp_path,
) -> None:
    app = _app(tmp_path)

    try:
        target = app.backup.register_target(
            tmp_path / "backup"
        )

        now_us = utc_now_us()

        first = app.backup_worker.schedule_due(
            now_us=now_us,
        )
        second = app.backup_worker.schedule_due(
            now_us=now_us,
        )

        assert len(first) == 1
        assert second == ()

        job = first[0]

        assert job.job_type == BACKUP_CREATE_JOB_TYPE

        assert job.requested_scope_json is not None
        scope = json.loads(
            job.requested_scope_json
        )

        assert scope == {
            "schedule_slot_us": daily_backup_slot_us(
                now_us,
            ),
            "target_id": str(target.target_id),
        }

        active = app.jobs.active_for_type(
            BACKUP_CREATE_JOB_TYPE,
            limit=16,
        )

        assert len(active) == 1
        assert active[0].job_id == job.job_id

    finally:
        app.stop()


def test_target_lock_prevents_parallel_scheduler_enqueue(
    tmp_path,
) -> None:
    app = _app(tmp_path)

    try:
        target_root = tmp_path / "backup"

        app.backup.register_target(
            target_root
        )

        with backup_target_lock(target_root):
            assert app.backup_worker.schedule_due(
                now_us=utc_now_us(),
            ) == ()

        scheduled = app.backup_worker.schedule_due(
            now_us=utc_now_us(),
        )

        assert len(scheduled) == 1

    finally:
        app.stop()


def test_successful_backup_suppresses_current_slot_and_catches_up_next_day(
    tmp_path,
) -> None:
    app = _app(tmp_path)

    try:
        target = app.backup.register_target(
            tmp_path / "backup"
        )

        app.backup.create_snapshot(
            target_id=target.target_id,
        )

        now_us = utc_now_us()

        assert app.backup_worker.schedule_due(
            now_us=now_us,
        ) == ()

        future_us = now_us + _DAY_US + 1

        scheduled = app.backup_worker.schedule_due(
            now_us=future_us,
        )

        assert len(scheduled) == 1

        assert scheduled[0].requested_scope_json is not None
        scope = json.loads(
            scheduled[0].requested_scope_json
        )

        assert scope["schedule_slot_us"] == (
            daily_backup_slot_us(future_us)
        )

    finally:
        app.stop()


def test_queued_job_is_idempotent_if_manual_backup_already_satisfied_slot(
    tmp_path,
) -> None:
    app = _app(tmp_path)

    try:
        target = app.backup.register_target(
            tmp_path / "backup"
        )

        scheduled = app.backup_worker.schedule_due(
            now_us=utc_now_us(),
        )

        assert len(scheduled) == 1

        app.backup.create_snapshot(
            target_id=target.target_id,
        )

        before = _complete_snapshot_count(
            app,
            target.target_id,
        )

        leased = app.jobs.acquire(
            scheduled[0].job_id,
            worker_id="backup-idempotence-test",
            lease_seconds=120,
        )

        completed = app.backup_worker.process_leased(
            leased
        )

        after = _complete_snapshot_count(
            app,
            target.target_id,
        )

        assert completed.state is JobState.COMPLETED
        assert before == 1
        assert after == before

    finally:
        app.stop()


def test_scheduler_tick_dispatches_due_backup_job(
    tmp_path,
) -> None:
    app = _app(tmp_path)

    try:
        target = app.backup.register_target(
            tmp_path / "backup"
        )

        # This test isolates scheduler dispatch from model/GPU resource policy.
        app.job_scheduler.resources = None

        result = app.job_scheduler.tick(
            worker_id="scheduled-backup-test",
            now_us=utc_now_us(),
        )

        assert result.selected_job_type == BACKUP_CREATE_JOB_TYPE
        assert result.final_state is JobState.COMPLETED

        assert _complete_snapshot_count(
            app,
            target.target_id,
        ) == 1

    finally:
        app.stop()
