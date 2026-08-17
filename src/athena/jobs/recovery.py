"""Fail-closed durable-job reconciliation for restored ATHENA runtimes."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

RECOVERY_REQUIRED_AFTER_RESTORE = "recovery_required_after_restore"
CANCELLED_AFTER_RESTORE = "recovered_cancel_after_restore"


@dataclass(frozen=True, slots=True)
class RestoredJobRecoverySummary:
    """Payload-free summary of in-flight job reconciliation during restore."""

    paused_running: int
    cancelled_requested: int

    @property
    def total(self) -> int:
        return self.paused_running + self.cancelled_requested


def reconcile_jobs_after_restore(
    connection: sqlite3.Connection,
    *,
    now_us: int,
) -> RestoredJobRecoverySummary:
    """Fence jobs whose workers cannot exist in the restored runtime.

    A restored ``running`` row is never treated as evidence that a worker is
    still executing. It is paused and requires an explicit resume after
    recovery review. A durable cancellation request is completed because the
    pre-restore worker no longer exists.

    Confirmed checkpoints, current stage, retry count, processing-run identity,
    and fencing sequence are deliberately preserved. Worker identity and lease
    material are always removed.
    """

    if now_us < 0:
        raise ValueError("Restore reconciliation timestamp must not be negative.")

    if connection.in_transaction:
        raise RuntimeError(
            "Restore job reconciliation requires transaction ownership."
        )

    transaction_started: bool = False

    try:
        connection.execute("BEGIN IMMEDIATE")
        transaction_started = True

        paused = connection.execute(
            """
            UPDATE jobs
            SET state = 'paused',
                blocked_reason = ?,
                next_run_at_us = NULL,
                worker_id = NULL,
                lease_token = NULL,
                lease_acquired_at_us = NULL,
                lease_expires_at_us = NULL,
                heartbeat_at_us = NULL,
                updated_at_us = MAX(updated_at_us, ?)
            WHERE state = 'running'
            """,
            (
                RECOVERY_REQUIRED_AFTER_RESTORE,
                now_us,
            ),
        )

        cancelled = connection.execute(
            """
            UPDATE jobs
            SET state = 'cancelled',
                blocked_reason = ?,
                next_run_at_us = NULL,
                worker_id = NULL,
                lease_token = NULL,
                lease_acquired_at_us = NULL,
                lease_expires_at_us = NULL,
                heartbeat_at_us = NULL,
                updated_at_us = MAX(updated_at_us, ?)
            WHERE state = 'cancel_requested'
            """,
            (
                CANCELLED_AFTER_RESTORE,
                now_us,
            ),
        )

        connection.execute("COMMIT")
        transaction_started = False

    except BaseException:
        if transaction_started:
            connection.execute("ROLLBACK")
        raise

    return RestoredJobRecoverySummary(
        paused_running=paused.rowcount,
        cancelled_requested=cancelled.rowcount,
    )
