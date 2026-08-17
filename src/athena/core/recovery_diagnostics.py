"""Payload-free read-only Recovery diagnostics for ATHENA."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from athena.core.derived_recovery import (
    DerivedLayerStatus,
    DerivedRecoveryService,
)
from athena.storage.paths import RuntimePaths
from athena.storage.recovery import inspect_database_read_only


class RecoveryDiagnosticStatus(str, Enum):
    """Overall operator-facing Recovery classification."""

    HEALTHY = "healthy"
    DEGRADED_DERIVED = "degraded-derived"
    RECOVERY_REQUIRED = "recovery-required"


class RecoveryIssueSeverity(str, Enum):
    """Required operator response for one payload-free issue."""

    REBUILD_REQUIRED = "rebuild-required"
    RECOVERY_REQUIRED = "recovery-required"


@dataclass(frozen=True, slots=True)
class RecoveryIssue:
    """One payload-free failure-matrix entry."""

    code: str
    layer: str
    severity: RecoveryIssueSeverity
    action: str
    count: int = 1

    def as_payload(self) -> dict[str, object]:
        return {
            "action": self.action,
            "code": self.code,
            "count": self.count,
            "layer": self.layer,
            "severity": self.severity.value,
        }


@dataclass(frozen=True, slots=True)
class RecoveryDiagnosticReport:
    """Machine-readable Recovery status without semantic payload content."""

    status: RecoveryDiagnosticStatus
    canonical_database: str
    canonical_integrity_confirmed: bool
    normal_core_start_allowed: bool
    protected_scopes_locked: bool
    optional_components_required: bool
    issues: tuple[RecoveryIssue, ...]
    canonical_embedding_profiles: int
    archive_embedding_profiles: int

    @property
    def exit_code(self) -> int:
        if self.status is RecoveryDiagnosticStatus.HEALTHY:
            return 0
        if self.status is RecoveryDiagnosticStatus.DEGRADED_DERIVED:
            return 3
        return 4

    def as_payload(self) -> dict[str, object]:
        return {
            "archive_embedding_profiles": (
                self.archive_embedding_profiles
            ),
            "canonical_database": self.canonical_database,
            "canonical_embedding_profiles": (
                self.canonical_embedding_profiles
            ),
            "canonical_integrity_confirmed": (
                self.canonical_integrity_confirmed
            ),
            "issues": [
                issue.as_payload()
                for issue in self.issues
            ],
            "normal_core_start_allowed": (
                self.normal_core_start_allowed
            ),
            "optional_components_required": (
                self.optional_components_required
            ),
            "protected_scopes_locked": (
                self.protected_scopes_locked
            ),
            "status": self.status.value,
        }


class RecoveryDiagnosticsService:
    """Classify canonical and Derived State without intentional mutation."""

    def __init__(
        self,
        *,
        paths: RuntimePaths,
    ) -> None:
        self.paths = paths

    def inspect(self) -> RecoveryDiagnosticReport:
        """Return the complete payload-free Recovery failure matrix."""

        try:
            preflight = inspect_database_read_only(
                self.paths.database_path
            )
        except Exception:
            return RecoveryDiagnosticReport(
                status=(
                    RecoveryDiagnosticStatus.RECOVERY_REQUIRED
                ),
                canonical_database="invalid-or-incompatible",
                canonical_integrity_confirmed=False,
                normal_core_start_allowed=False,
                protected_scopes_locked=True,
                optional_components_required=False,
                issues=(
                    RecoveryIssue(
                        code=(
                            "canonical."
                            "database_invalid_or_incompatible"
                        ),
                        layer="canonical",
                        severity=(
                            RecoveryIssueSeverity.RECOVERY_REQUIRED
                        ),
                        action="restore-or-investigate-canonical-db",
                    ),
                ),
                canonical_embedding_profiles=0,
                archive_embedding_profiles=0,
            )

        if not preflight.exists:
            return RecoveryDiagnosticReport(
                status=(
                    RecoveryDiagnosticStatus.RECOVERY_REQUIRED
                ),
                canonical_database="missing",
                canonical_integrity_confirmed=False,
                normal_core_start_allowed=False,
                protected_scopes_locked=True,
                optional_components_required=False,
                issues=(
                    RecoveryIssue(
                        code="canonical.database_missing",
                        layer="canonical",
                        severity=(
                            RecoveryIssueSeverity.RECOVERY_REQUIRED
                        ),
                        action="restore-canonical-db",
                    ),
                ),
                canonical_embedding_profiles=0,
                archive_embedding_profiles=0,
            )

        try:
            derived = DerivedRecoveryService(
                database_path=self.paths.database_path,
                derived_root=self.paths.derived_root,
            ).inspect()
        except Exception:
            return RecoveryDiagnosticReport(
                status=(
                    RecoveryDiagnosticStatus.RECOVERY_REQUIRED
                ),
                canonical_database="healthy",
                canonical_integrity_confirmed=True,
                normal_core_start_allowed=False,
                protected_scopes_locked=True,
                optional_components_required=False,
                issues=(
                    RecoveryIssue(
                        code="derived.inspection_failed",
                        layer="derived",
                        severity=(
                            RecoveryIssueSeverity.RECOVERY_REQUIRED
                        ),
                        action="investigate-derived-state",
                    ),
                ),
                canonical_embedding_profiles=0,
                archive_embedding_profiles=0,
            )

        issues: list[RecoveryIssue] = []

        self._append_layer_issue(
            issues,
            code_prefix="derived.canonical_fts",
            layer="derived-canonical-fts",
            status=derived.canonical_fts.status,
            stale_action="rebuild-canonical-fts",
            missing_action="investigate-canonical-fts",
            invalid_action="investigate-canonical-fts",
            stale_requires_recovery=False,
        )

        self._append_layer_issue(
            issues,
            code_prefix="derived.archive_store",
            layer="derived-archive-store",
            status=derived.archive_store_status,
            stale_action="regenerate-source-chunks",
            missing_action="regenerate-source-chunks",
            invalid_action="investigate-archive-store",
            stale_requires_recovery=True,
        )

        if (
            derived.archive_store_status
            is DerivedLayerStatus.CURRENT
        ):
            self._append_layer_issue(
                issues,
                code_prefix="derived.archive_fts",
                layer="derived-archive-fts",
                status=derived.archive_fts.status,
                stale_action="rebuild-archive-fts",
                missing_action="investigate-archive-fts",
                invalid_action="investigate-archive-fts",
                stale_requires_recovery=False,
            )

        canonical_embedding_rebuilds = sum(
            1
            for item in derived.canonical_embeddings
            if item.embedding_rebuild_required
        )

        canonical_hnsw_rebuilds = sum(
            1
            for item in derived.canonical_embeddings
            if (
                not item.embedding_rebuild_required
                and item.hnsw_rebuild_required
            )
        )

        archive_embedding_rebuilds = sum(
            1
            for item in derived.archive_embeddings
            if item.embedding_rebuild_required
        )

        archive_hnsw_rebuilds = sum(
            1
            for item in derived.archive_embeddings
            if (
                not item.embedding_rebuild_required
                and item.hnsw_rebuild_required
            )
        )

        if canonical_embedding_rebuilds:
            issues.append(
                RecoveryIssue(
                    code=(
                        "derived."
                        "canonical_embeddings_rebuild_required"
                    ),
                    layer="derived-canonical-embeddings",
                    severity=(
                        RecoveryIssueSeverity.REBUILD_REQUIRED
                    ),
                    action=(
                        "rebuild-canonical-embeddings-"
                        "after-recovery"
                    ),
                    count=canonical_embedding_rebuilds,
                )
            )

        if canonical_hnsw_rebuilds:
            issues.append(
                RecoveryIssue(
                    code=(
                        "derived."
                        "canonical_hnsw_rebuild_required"
                    ),
                    layer="derived-canonical-hnsw",
                    severity=(
                        RecoveryIssueSeverity.REBUILD_REQUIRED
                    ),
                    action=(
                        "rebuild-canonical-hnsw-"
                        "from-persisted-vectors"
                    ),
                    count=canonical_hnsw_rebuilds,
                )
            )

        if archive_embedding_rebuilds:
            issues.append(
                RecoveryIssue(
                    code=(
                        "derived."
                        "archive_embeddings_rebuild_required"
                    ),
                    layer="derived-archive-embeddings",
                    severity=(
                        RecoveryIssueSeverity.REBUILD_REQUIRED
                    ),
                    action=(
                        "rebuild-archive-embeddings-"
                        "after-recovery"
                    ),
                    count=archive_embedding_rebuilds,
                )
            )

        if archive_hnsw_rebuilds:
            issues.append(
                RecoveryIssue(
                    code=(
                        "derived."
                        "archive_hnsw_rebuild_required"
                    ),
                    layer="derived-archive-hnsw",
                    severity=(
                        RecoveryIssueSeverity.REBUILD_REQUIRED
                    ),
                    action=(
                        "rebuild-archive-hnsw-"
                        "from-persisted-vectors"
                    ),
                    count=archive_hnsw_rebuilds,
                )
            )

        if any(
            issue.severity
            is RecoveryIssueSeverity.RECOVERY_REQUIRED
            for issue in issues
        ):
            status = (
                RecoveryDiagnosticStatus.RECOVERY_REQUIRED
            )
        elif issues:
            status = (
                RecoveryDiagnosticStatus.DEGRADED_DERIVED
            )
        else:
            status = RecoveryDiagnosticStatus.HEALTHY

        return RecoveryDiagnosticReport(
            status=status,
            canonical_database="healthy",
            canonical_integrity_confirmed=True,
            normal_core_start_allowed=(
                status
                is not RecoveryDiagnosticStatus.RECOVERY_REQUIRED
            ),
            protected_scopes_locked=True,
            optional_components_required=False,
            issues=tuple(issues),
            canonical_embedding_profiles=len(
                derived.canonical_embeddings
            ),
            archive_embedding_profiles=len(
                derived.archive_embeddings
            ),
        )

    @staticmethod
    def _append_layer_issue(
        issues: list[RecoveryIssue],
        *,
        code_prefix: str,
        layer: str,
        status: DerivedLayerStatus,
        stale_action: str,
        missing_action: str,
        invalid_action: str,
        stale_requires_recovery: bool,
    ) -> None:
        if status is DerivedLayerStatus.CURRENT:
            return

        if status is DerivedLayerStatus.STALE:
            severity = (
                RecoveryIssueSeverity.RECOVERY_REQUIRED
                if stale_requires_recovery
                else RecoveryIssueSeverity.REBUILD_REQUIRED
            )
            action = stale_action

        elif status is DerivedLayerStatus.MISSING:
            severity = (
                RecoveryIssueSeverity.REBUILD_REQUIRED
            )
            action = missing_action

        else:
            severity = (
                RecoveryIssueSeverity.RECOVERY_REQUIRED
            )
            action = invalid_action

        issues.append(
            RecoveryIssue(
                code=(
                    f"{code_prefix}_"
                    f"{status.value.replace('-', '_')}"
                ),
                layer=layer,
                severity=severity,
                action=action,
            )
        )
