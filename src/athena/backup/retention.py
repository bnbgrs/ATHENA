"""Deterministic backup retention policy and planning."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class BackupRetentionPolicy:
    daily: int = 7
    weekly: int = 4
    monthly: int = 12
    yearly: int = 5

    def __post_init__(self) -> None:
        for name, value in (
            ("daily", self.daily),
            ("weekly", self.weekly),
            ("monthly", self.monthly),
            ("yearly", self.yearly),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(
                    f"Backup retention {name} must be a non-negative integer."
                )


@dataclass(frozen=True, slots=True)
class BackupTargetRecord:
    target_id: uuid.UUID
    root_path: Path
    status: str
    policy: BackupRetentionPolicy
    identity_initialized: bool
    created_at_us: int
    last_successful_backup_at_us: int | None
    last_verified_at_us: int | None
    deletion_ledger_watermark: int = 0
    deletion_sync_pending: bool = False


@dataclass(frozen=True, slots=True)
class RetentionCandidate:
    snapshot_id: uuid.UUID
    completed_at_us: int


@dataclass(frozen=True, slots=True)
class BackupRetentionPlan:
    target_id: uuid.UUID
    keep_snapshot_ids: tuple[uuid.UUID, ...]
    prune_snapshot_ids: tuple[uuid.UUID, ...]


@dataclass(frozen=True, slots=True)
class BackupRetentionResult:
    plan: BackupRetentionPlan
    pruned_snapshot_ids: tuple[uuid.UUID, ...]
    deleted_object_count: int


def plan_retention(
    *,
    target_id: uuid.UUID,
    snapshots: tuple[RetentionCandidate, ...],
    policy: BackupRetentionPolicy,
) -> BackupRetentionPlan:
    ordered = sorted(
        snapshots,
        key=lambda item: (
            item.completed_at_us,
            item.snapshot_id.int,
        ),
        reverse=True,
    )

    if not ordered:
        return BackupRetentionPlan(
            target_id=target_id,
            keep_snapshot_ids=(),
            prune_snapshot_ids=(),
        )

    keep: set[uuid.UUID] = {ordered[0].snapshot_id}

    def stamp(item: RetentionCandidate) -> datetime:
        seconds = item.completed_at_us // 1_000_000
        return datetime.fromtimestamp(seconds, tz=UTC)

    def retain_slots(limit: int, kind: str) -> None:
        if limit <= 0:
            return

        seen: set[object] = set()

        for item in ordered:
            value = stamp(item)

            if kind == "daily":
                bucket: object = (
                    value.year,
                    value.month,
                    value.day,
                )
            elif kind == "weekly":
                iso = value.isocalendar()
                bucket = (
                    iso.year,
                    iso.week,
                )
            elif kind == "monthly":
                bucket = (
                    value.year,
                    value.month,
                )
            elif kind == "yearly":
                bucket = value.year
            else:
                raise AssertionError(kind)

            if bucket in seen:
                continue

            if len(seen) >= limit:
                continue

            seen.add(bucket)
            keep.add(item.snapshot_id)

    retain_slots(policy.daily, "daily")
    retain_slots(policy.weekly, "weekly")
    retain_slots(policy.monthly, "monthly")
    retain_slots(policy.yearly, "yearly")

    keep_ordered = tuple(
        item.snapshot_id
        for item in ordered
        if item.snapshot_id in keep
    )
    prune_ordered = tuple(
        item.snapshot_id
        for item in ordered
        if item.snapshot_id not in keep
    )

    return BackupRetentionPlan(
        target_id=target_id,
        keep_snapshot_ids=keep_ordered,
        prune_snapshot_ids=prune_ordered,
    )
