"""Logical runtime paths used by ATHENA."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from athena.config.settings import AthenaSettings


@dataclass(frozen=True, slots=True)
class RuntimePaths:
    """Physical local paths grouped by persistence semantics."""

    local_root: Path
    state_root: Path
    database_path: Path
    spool_root: Path
    derived_root: Path
    log_root: Path
    temp_root: Path
    archive_root: Path | None
    backup_root: Path | None
    projection_root: Path | None

    @classmethod
    def from_settings(cls, settings: AthenaSettings) -> "RuntimePaths":
        local = settings.local_root
        state = local / "state"

        return cls(
            local_root=local,
            state_root=state,
            database_path=state / "athena.db",
            # Durable pending bytes belong underneath non-reconstructible state.
            spool_root=state / "spool",
            # Reconstructible indexes/caches are physically separate.
            derived_root=local / "derived",
            log_root=local / "logs",
            temp_root=local / "tmp",
            archive_root=settings.archive_root,
            backup_root=settings.backup_root,
            projection_root=settings.projection_root,
        )

    @property
    def required_local_directories(self) -> tuple[Path, ...]:
        return (
            self.local_root,
            self.state_root,
            self.spool_root,
            self.derived_root,
            self.log_root,
            self.temp_root,
        )
