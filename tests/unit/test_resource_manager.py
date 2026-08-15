from __future__ import annotations

from pathlib import Path

from athena.common.ids import new_uuid7
from athena.common.time import utc_now_us
from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.jobs.models import JobPriority, JobState, WaitingReason
from athena.resources.manager import (
    ResourceMode,
    ResourceSnapshot,
    StaticResourceProbe,
)


def test_scheduler_waits_background_job_when_background_is_paused(
    tmp_path: Path,
) -> None:
    app = AthenaApplication(settings=AthenaSettings(local_root=tmp_path / "runtime"))
    app.start()
    snapshot = ResourceSnapshot(
        snapshot_id=new_uuid7(),
        captured_at_us=utc_now_us(),
        ram_total_bytes=32 * 1024**3,
        ram_available_bytes=24 * 1024**3,
        disk_free_bytes=100 * 1024**3,
        cpu_load_fraction=0.1,
        gpu_utilization_fraction=None,
        vram_total_bytes=None,
        vram_available_bytes=None,
        model_loaded=None,
        degraded_metrics=("gpu_utilization", "vram"),
    )
    app.resources.probe = StaticResourceProbe(snapshot)
    app.resources.set_mode(ResourceMode.PAUSE_BACKGROUND)
    job = app.jobs.create(
        job_type="embedding.rebuild",
        priority=JobPriority.BACKGROUND,
        requested_scope={"model_id": "unused"},
        pinned_configuration={"batch_size": 1},
    )

    tick = app.job_scheduler.tick(worker_id="resource-test", now_us=utc_now_us())
    current = app.jobs.get(job.job_id)
    assert tick.selected_job_id == job.job_id
    assert current.state is JobState.WAITING
    assert current.blocked_reason == WaitingReason.RESOURCE.value
    assert current.next_run_at_us is not None
    assert current.retry_count == 0

    policy = app.resources.set_mode(ResourceMode.BALANCED)
    assert policy.mode is ResourceMode.BALANCED
    app.stop()

def test_quiet_mode_defers_normal_gpu_research_without_mutating_payload(
    tmp_path: Path,
) -> None:
    app = AthenaApplication(settings=AthenaSettings(local_root=tmp_path / "quiet-runtime"))
    app.start()
    snapshot = ResourceSnapshot(
        snapshot_id=new_uuid7(),
        captured_at_us=utc_now_us(),
        ram_total_bytes=32 * 1024**3,
        ram_available_bytes=24 * 1024**3,
        disk_free_bytes=100 * 1024**3,
        cpu_load_fraction=0.1,
        gpu_utilization_fraction=0.1,
        vram_total_bytes=24 * 1024**3,
        vram_available_bytes=20 * 1024**3,
        model_loaded=True,
        degraded_metrics=(),
    )
    app.resources.probe = StaticResourceProbe(snapshot)
    app.resources.set_mode(ResourceMode.QUIET)
    job = app.jobs.create(
        job_type="research.exhaustive",
        priority=JobPriority.NORMAL,
        requested_scope={"sentinel": "unchanged"},
        pinned_configuration={"sentinel": "unchanged"},
    )
    before = app.jobs.get(job.job_id)

    tick = app.job_scheduler.tick(worker_id="quiet-resource-test", now_us=utc_now_us())
    after = app.jobs.get(job.job_id)

    assert tick.action == "waiting_resource"
    assert after.state is JobState.WAITING
    assert after.blocked_reason == WaitingReason.RESOURCE.value
    assert after.requested_scope_json == before.requested_scope_json
    assert after.pinned_configuration_json == before.pinned_configuration_json
    app.stop()


def test_reused_probe_identity_cannot_collide_in_persisted_snapshots(
    tmp_path: Path,
) -> None:
    app = AthenaApplication(settings=AthenaSettings(local_root=tmp_path / "identity-runtime"))
    app.start()
    fixed = ResourceSnapshot(
        snapshot_id=new_uuid7(),
        captured_at_us=1,
        ram_total_bytes=32 * 1024**3,
        ram_available_bytes=24 * 1024**3,
        disk_free_bytes=100 * 1024**3,
        cpu_load_fraction=0.1,
        gpu_utilization_fraction=None,
        vram_total_bytes=None,
        vram_available_bytes=None,
        model_loaded=None,
        degraded_metrics=("gpu_utilization", "vram"),
    )
    app.resources.probe = StaticResourceProbe(fixed)
    first = app.resources.snapshot(include_model=False)
    second = app.resources.snapshot(include_model=False)
    assert first.snapshot_id != second.snapshot_id
    count = app.database.connection.execute(
        "SELECT COUNT(*) FROM resource_runtime_snapshots"
    ).fetchone()
    assert count is not None and int(count[0]) >= 2
    app.stop()


class _BrokenProbe:
    def sample(self, paths):
        del paths
        raise RuntimeError("synthetic telemetry failure")


def test_probe_failure_degrades_to_resource_wait_instead_of_scheduler_crash(
    tmp_path: Path,
) -> None:
    app = AthenaApplication(settings=AthenaSettings(local_root=tmp_path / "broken-runtime"))
    app.start()
    app.resources.probe = _BrokenProbe()
    job = app.jobs.create(
        job_type="embedding.rebuild",
        priority=JobPriority.BACKGROUND,
        requested_scope={"model_id": "unused"},
        pinned_configuration={"batch_size": 1},
    )

    tick = app.job_scheduler.tick(worker_id="broken-resource-test", now_us=utc_now_us())
    current = app.jobs.get(job.job_id)
    assert tick.action == "waiting_resource"
    assert current.state is JobState.WAITING
    latest = app.database.connection.execute(
        """
        SELECT degraded_metrics_json
        FROM resource_runtime_snapshots
        ORDER BY captured_at_us DESC
        LIMIT 1
        """
    ).fetchone()
    assert latest is not None
    assert "resource_probe" in str(latest["degraded_metrics_json"])
    app.stop()
