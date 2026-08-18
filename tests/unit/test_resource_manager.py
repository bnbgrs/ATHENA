from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from athena.common.ids import new_uuid7
from athena.common.time import utc_now_us
from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.jobs.capabilities import requires_provider_isolation
from athena.jobs.models import JobPriority, JobState, WaitingReason
from athena.news.models import NEWS_JOB_TYPE, NEWS_PERIOD_JOB_TYPE
from athena.resources.manager import (
    ResourceManager,
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

def test_interactive_demand_lease_is_visible_and_released(tmp_path: Path) -> None:
    app = AthenaApplication(
        settings=AthenaSettings(local_root=tmp_path / "interactive-runtime")
    )
    app.start()

    observer = ResourceManager(
        database=app.database,
        paths=app.paths,
        chat=app.chat,
        model_provider=app.model_provider,
        interactive_lease_seconds=app.resources.interactive_lease_seconds,
    )

    assert not observer.interactive_demand_active()

    with app.resources.interactive_session(
        purpose="unit_test_chat"
    ) as lease:
        assert observer.interactive_demand_active()
        lease_path = (
            app.paths.state_root
            / "interactive-demand"
            / f"{lease.lease_id}.json"
        )
        assert lease_path.is_file()

    assert not observer.interactive_demand_active()
    app.stop()


def test_expired_interactive_demand_does_not_block_background_work(
    tmp_path: Path,
) -> None:
    app = AthenaApplication(
        settings=AthenaSettings(local_root=tmp_path / "expiry-runtime")
    )
    app.start()

    lease = app.resources.acquire_interactive_demand(
        purpose="stale_test",
        lease_seconds=1,
        now_us=1_000_000,
    )
    assert app.resources.interactive_demand_active(
        now_us=1_500_000
    )
    assert not app.resources.interactive_demand_active(
        now_us=2_000_001
    )

    app.resources.release_interactive_demand(lease.lease_id)
    app.stop()


def test_interactive_chat_defers_background_gpu_job_but_not_data_safety(
    tmp_path: Path,
) -> None:
    app = AthenaApplication(
        settings=AthenaSettings(local_root=tmp_path / "priority-runtime")
    )
    app.start()

    background = app.jobs.create(
        job_type="research.exhaustive",
        priority=JobPriority.BACKGROUND,
        requested_scope={"sentinel": "background"},
        pinned_configuration={"sentinel": "background"},
    )
    data_safety = app.jobs.create(
        job_type="research.exhaustive",
        priority=JobPriority.DATA_SAFETY,
        requested_scope={"sentinel": "data-safety"},
        pinned_configuration={"sentinel": "data-safety"},
    )

    with app.resources.interactive_session(purpose="priority_test"):
        deferred = app.resources.admit(background)
        protected = app.resources.admit(data_safety)

    assert not deferred.admitted
    assert deferred.reason == "interactive chat demand has priority"
    assert deferred.retry_after_seconds == 5

    assert protected.admitted
    assert protected.reason is None
    assert protected.retry_after_seconds == 0

    app.stop()


def test_interactive_demand_renewal_extends_live_lease(
    tmp_path: Path,
) -> None:
    app = AthenaApplication(
        settings=AthenaSettings(
            local_root=tmp_path / "renew-runtime"
        )
    )
    app.start()

    lease = app.resources.acquire_interactive_demand(
        purpose="renew-test",
        lease_seconds=10,
        now_us=1_000_000,
    )

    # Before half-life: no durable renewal needed.
    same = app.resources.renew_interactive_demand(
        lease,
        now_us=5_000_000,
    )
    assert same == lease

    # After half-life: extend ten seconds from renewal time.
    renewed = app.resources.renew_interactive_demand(
        same,
        now_us=6_000_001,
    )
    assert renewed.lease_id == lease.lease_id
    assert renewed.acquired_at_us == lease.acquired_at_us
    assert renewed.lease_seconds == 10
    assert renewed.expires_at_us == 16_000_001

    # Original lease would already be expired here.
    assert app.resources.interactive_demand_active(
        now_us=12_000_000
    )

    app.resources.release_interactive_demand(
        lease.lease_id
    )
    assert not app.resources.interactive_demand_active(
        now_us=12_000_000
    )

    app.stop()


def test_multiple_interactive_chat_leases_are_independent(
    tmp_path: Path,
) -> None:
    app = AthenaApplication(
        settings=AthenaSettings(
            local_root=tmp_path / "multi-chat-runtime"
        )
    )
    app.start()

    first = app.resources.acquire_interactive_demand(
        purpose="chat-one"
    )
    second = app.resources.acquire_interactive_demand(
        purpose="chat-two"
    )

    assert first.lease_id != second.lease_id
    assert app.resources.interactive_demand_active()

    app.resources.release_interactive_demand(
        first.lease_id
    )

    # Releasing one chat must not re-enable background work while
    # another interactive chat is still active.
    assert app.resources.interactive_demand_active()

    app.resources.release_interactive_demand(
        second.lease_id
    )

    assert not app.resources.interactive_demand_active()

    app.stop()


def test_forced_interactive_renewal_refreshes_before_retry(
    tmp_path: Path,
) -> None:
    app = AthenaApplication(
        settings=AthenaSettings(
            local_root=tmp_path / "force-renew-runtime"
        )
    )
    app.start()

    lease = app.resources.acquire_interactive_demand(
        purpose="retry-test",
        lease_seconds=10,
        now_us=1_000_000,
    )

    renewed = app.resources.renew_interactive_demand(
        lease,
        now_us=2_000_000,
        force=True,
    )

    assert renewed.expires_at_us == 12_000_000
    assert renewed.expires_at_us > lease.expires_at_us

    app.resources.release_interactive_demand(
        lease.lease_id
    )
    app.stop()

def test_interactive_demand_fail_closed_for_news_and_future_provider_jobs(
    tmp_path: Path,
) -> None:
    app = AthenaApplication(
        settings=AthenaSettings(
            local_root=tmp_path / "provider-guard-runtime"
        )
    )
    app.start()
    try:
        base = app.jobs.create(
            job_type="source.process",
            priority=JobPriority.BACKGROUND,
            requested_scope={"sentinel": "classification-template"},
            pinned_configuration={"sentinel": "classification-template"},
        )
        provider_jobs = tuple(
            replace(
                base,
                job_type=job_type,
            )
            for job_type in (
                NEWS_JOB_TYPE,
                NEWS_PERIOD_JOB_TYPE,
                "future.provider-bound",
            )
        )

        with app.resources.interactive_session(
            purpose="provider_guard_test"
        ):
            decisions = tuple(
                app.resources.admit(job)
                for job in provider_jobs
            )

        assert all(
            not decision.admitted
            for decision in decisions
        )
        assert all(
            decision.reason
            == "interactive chat demand has priority"
            for decision in decisions
        )
        assert not requires_provider_isolation("source.process")
        assert not requires_provider_isolation("backup.create")
        assert not requires_provider_isolation("archive.replicate")
        assert requires_provider_isolation(NEWS_JOB_TYPE)
        assert requires_provider_isolation(NEWS_PERIOD_JOB_TYPE)
        assert requires_provider_isolation("future.provider-bound")
    finally:
        app.stop()
