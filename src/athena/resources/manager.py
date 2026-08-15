"""Conservative resource probes and scheduler admission policy."""

from __future__ import annotations

import ctypes
import json
import os
import shutil
import uuid
from dataclasses import dataclass, replace
from enum import Enum
from typing import Protocol

from athena.chat.service import ChatService
from athena.common.ids import new_uuid7, uuid_from_blob, uuid_to_blob
from athena.common.time import utc_now_us
from athena.jobs.models import JobPriority, JobRecord
from athena.model.ports import ChatModelProvider
from athena.storage.database import SQLiteDatabase
from athena.storage.paths import RuntimePaths


class ResourceMode(str, Enum):
    BALANCED = "balanced"
    QUIET = "quiet"
    PERFORMANCE = "performance"
    PAUSE_BACKGROUND = "pause_background"


@dataclass(frozen=True, slots=True)
class ResourceSnapshot:
    snapshot_id: uuid.UUID
    captured_at_us: int
    ram_total_bytes: int | None
    ram_available_bytes: int | None
    disk_free_bytes: int
    cpu_load_fraction: float | None
    gpu_utilization_fraction: float | None
    vram_total_bytes: int | None
    vram_available_bytes: int | None
    model_loaded: bool | None
    degraded_metrics: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ResourcePolicy:
    mode: ResourceMode
    ram_headroom_bytes: int
    disk_headroom_bytes: int
    gpu_background_threshold: float
    updated_at_us: int
    updated_by_actor_id: uuid.UUID | None


@dataclass(frozen=True, slots=True)
class AdmissionDecision:
    admitted: bool
    reason: str | None
    retry_after_seconds: int


class ResourceProbe(Protocol):
    def sample(self, paths: RuntimePaths) -> ResourceSnapshot:
        """Return best-effort local metrics; unavailable metrics stay None."""
        ...


class PortableResourceProbe:
    """Portable CPU/RAM/disk probe; GPU metrics intentionally degrade when unavailable."""

    def sample(self, paths: RuntimePaths) -> ResourceSnapshot:
        degraded: list[str] = []
        ram_total, ram_available = _memory_status()
        if ram_total is None or ram_available is None:
            degraded.append("ram")
        cpu_load = _cpu_load_fraction()
        if cpu_load is None:
            degraded.append("cpu")
        disk = shutil.disk_usage(paths.local_root)
        degraded.extend(("gpu_utilization", "vram"))
        return ResourceSnapshot(
            snapshot_id=new_uuid7(),
            captured_at_us=utc_now_us(),
            ram_total_bytes=ram_total,
            ram_available_bytes=ram_available,
            disk_free_bytes=disk.free,
            cpu_load_fraction=cpu_load,
            gpu_utilization_fraction=None,
            vram_total_bytes=None,
            vram_available_bytes=None,
            model_loaded=None,
            degraded_metrics=tuple(degraded),
        )


class StaticResourceProbe:
    """Deterministic probe for tests and explicit diagnostics."""

    def __init__(self, snapshot: ResourceSnapshot) -> None:
        self.snapshot = snapshot

    def sample(self, paths: RuntimePaths) -> ResourceSnapshot:
        del paths
        return replace(
            self.snapshot,
            snapshot_id=new_uuid7(),
            captured_at_us=utc_now_us(),
        )


class ResourceManager:
    """Persist resource mode and admit heavy durable jobs without changing semantics."""

    _RAM_MINIMUMS = {
        "source.process": 256 * 1024 * 1024,
        "source.analyze": 1024 * 1024 * 1024,
        "source.extract": 1024 * 1024 * 1024,
        "research.exhaustive": 1024 * 1024 * 1024,
        "embedding.rebuild": 512 * 1024 * 1024,
    }
    _GPU_JOBS = frozenset(
        {"source.analyze", "source.extract", "research.exhaustive", "embedding.rebuild"}
    )

    def __init__(
        self,
        *,
        database: SQLiteDatabase,
        paths: RuntimePaths,
        chat: ChatService,
        model_provider: ChatModelProvider,
        probe: ResourceProbe | None = None,
    ) -> None:
        self.database = database
        self.paths = paths
        self.chat = chat
        self.model_provider = model_provider
        self.probe = probe or PortableResourceProbe()

    def policy(self) -> ResourcePolicy:
        row = self.database.connection.execute(
            "SELECT * FROM resource_policy WHERE singleton_id = 1"
        ).fetchone()
        if row is None:
            raise RuntimeError("ATHENA resource policy row is missing.")
        return ResourcePolicy(
            mode=ResourceMode(str(row["mode"])),
            ram_headroom_bytes=int(row["ram_headroom_bytes"]),
            disk_headroom_bytes=int(row["disk_headroom_bytes"]),
            gpu_background_threshold=float(row["gpu_background_threshold"]),
            updated_at_us=int(row["updated_at_us"]),
            updated_by_actor_id=(
                uuid_from_blob(bytes(row["updated_by_actor_id"]))
                if row["updated_by_actor_id"] is not None
                else None
            ),
        )

    def set_mode(self, mode: ResourceMode) -> ResourcePolicy:
        actor_id = self.chat.ensure_local_user()
        now_us = utc_now_us()
        with self.database.write_transaction() as connection:
            connection.execute(
                """
                UPDATE resource_policy
                SET mode = ?, updated_at_us = ?, updated_by_actor_id = ?
                WHERE singleton_id = 1
                """,
                (mode.value, now_us, uuid_to_blob(actor_id)),
            )
        return self.policy()

    def snapshot(self, *, include_model: bool = True) -> ResourceSnapshot:
        try:
            sampled = self.probe.sample(self.paths)
        except Exception as exc:
            sampled = ResourceSnapshot(
                snapshot_id=new_uuid7(),
                captured_at_us=utc_now_us(),
                ram_total_bytes=None,
                ram_available_bytes=None,
                disk_free_bytes=0,
                cpu_load_fraction=None,
                gpu_utilization_fraction=None,
                vram_total_bytes=None,
                vram_available_bytes=None,
                model_loaded=None,
                degraded_metrics=("resource_probe", type(exc).__name__),
            )
        degraded = list(sampled.degraded_metrics)
        model_loaded = sampled.model_loaded
        if model_loaded is None:
            if include_model:
                try:
                    models = self.model_provider.discover_models()
                except Exception:
                    degraded.append("model_availability")
                else:
                    model_loaded = any(
                        item.loaded for item in models if item.model_type == "llm"
                    )
            else:
                degraded.append("model_availability")

        snapshot = ResourceSnapshot(
            # Persisted samples always receive a fresh identity even when a
            # third-party/static probe accidentally reuses its own sample ID.
            snapshot_id=new_uuid7(),
            captured_at_us=utc_now_us(),
            ram_total_bytes=sampled.ram_total_bytes,
            ram_available_bytes=sampled.ram_available_bytes,
            disk_free_bytes=sampled.disk_free_bytes,
            cpu_load_fraction=sampled.cpu_load_fraction,
            gpu_utilization_fraction=sampled.gpu_utilization_fraction,
            vram_total_bytes=sampled.vram_total_bytes,
            vram_available_bytes=sampled.vram_available_bytes,
            model_loaded=model_loaded,
            degraded_metrics=tuple(sorted(set(degraded))),
        )
        self._persist_snapshot(snapshot)
        return snapshot

    def admit(self, job: JobRecord) -> AdmissionDecision:
        policy = self.policy()
        if job.priority is JobPriority.DATA_SAFETY:
            return AdmissionDecision(True, None, 0)
        if (
            policy.mode is ResourceMode.PAUSE_BACKGROUND
            and job.priority >= JobPriority.BACKGROUND
        ):
            return AdmissionDecision(
                False,
                "background work paused by resource mode",
                60,
            )

        if (
            policy.mode is ResourceMode.QUIET
            and job.job_type in self._GPU_JOBS
            and job.priority >= JobPriority.NORMAL
        ):
            return AdmissionDecision(False, "quiet mode defers non-urgent GPU work", 60)

        snapshot = self.snapshot(include_model=False)
        if "resource_probe" in snapshot.degraded_metrics:
            return AdmissionDecision(False, "resource telemetry unavailable", 30)
        hard_ram = self._RAM_MINIMUMS.get(job.job_type, 256 * 1024 * 1024)
        ram_headroom = policy.ram_headroom_bytes
        disk_headroom = policy.disk_headroom_bytes
        if policy.mode is ResourceMode.QUIET:
            ram_headroom *= 2
            disk_headroom *= 2
        elif policy.mode is ResourceMode.PERFORMANCE:
            ram_headroom //= 2
            disk_headroom //= 2
        if (
            snapshot.ram_available_bytes is not None
            and snapshot.ram_available_bytes < ram_headroom + hard_ram
        ):
            return AdmissionDecision(False, "insufficient RAM headroom", 30)
        if snapshot.disk_free_bytes < disk_headroom:
            return AdmissionDecision(False, "insufficient disk headroom", 60)

        if job.job_type in self._GPU_JOBS:
            if (
                snapshot.gpu_utilization_fraction is not None
                and snapshot.gpu_utilization_fraction
                >= policy.gpu_background_threshold
                and job.priority >= JobPriority.BACKGROUND
            ):
                return AdmissionDecision(False, "GPU busy with external work", 30)
            if (
                snapshot.vram_available_bytes is not None
                and snapshot.vram_available_bytes < 2 * 1024 * 1024 * 1024
                and job.priority >= JobPriority.BACKGROUND
            ):
                return AdmissionDecision(False, "insufficient VRAM headroom", 30)

        return AdmissionDecision(True, None, 0)

    def _persist_snapshot(self, snapshot: ResourceSnapshot) -> None:
        with self.database.write_transaction() as connection:
            connection.execute(
                """
                INSERT INTO resource_runtime_snapshots (
                    snapshot_id, captured_at_us, ram_total_bytes, ram_available_bytes,
                    disk_free_bytes, cpu_load_fraction, gpu_utilization_fraction,
                    vram_total_bytes, vram_available_bytes, model_loaded,
                    degraded_metrics_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid_to_blob(snapshot.snapshot_id),
                    snapshot.captured_at_us,
                    snapshot.ram_total_bytes,
                    snapshot.ram_available_bytes,
                    snapshot.disk_free_bytes,
                    snapshot.cpu_load_fraction,
                    snapshot.gpu_utilization_fraction,
                    snapshot.vram_total_bytes,
                    snapshot.vram_available_bytes,
                    (
                        int(snapshot.model_loaded)
                        if snapshot.model_loaded is not None
                        else None
                    ),
                    json.dumps(
                        list(snapshot.degraded_metrics),
                        separators=(",", ":"),
                    ),
                ),
            )
            connection.execute(
                """
                DELETE FROM resource_runtime_snapshots
                WHERE snapshot_id NOT IN (
                    SELECT snapshot_id
                    FROM resource_runtime_snapshots
                    ORDER BY captured_at_us DESC
                    LIMIT 256
                )
                """
            )


def _memory_status() -> tuple[int | None, int | None]:
    if os.name == "nt":
        class MemoryStatusEx(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatusEx()
        status.dwLength = ctypes.sizeof(status)
        windll = getattr(ctypes, "windll", None)
        if windll is None:
            return None, None
        try:
            ok = windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
        except (AttributeError, OSError):
            return None, None
        if not ok:
            return None, None
        return int(status.ullTotalPhys), int(status.ullAvailPhys)

    sysconf = getattr(os, "sysconf", None)
    if not callable(sysconf):
        return None, None
    try:
        page_size = int(sysconf("SC_PAGE_SIZE"))
        total_pages = int(sysconf("SC_PHYS_PAGES"))
        available_pages = int(sysconf("SC_AVPHYS_PAGES"))
    except (OSError, TypeError, ValueError):
        return None, None
    return page_size * total_pages, page_size * available_pages


def _cpu_load_fraction() -> float | None:
    cpu_count = os.cpu_count()
    if not cpu_count:
        return None
    getloadavg = getattr(os, "getloadavg", None)
    if not callable(getloadavg):
        return None
    try:
        load = float(getloadavg()[0])
    except (OSError, TypeError, ValueError):
        return None
    return max(0.0, min(1.0, load / float(cpu_count)))
