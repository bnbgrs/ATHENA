"""Verified SQLite/blob backups and restore into a new isolated runtime root."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import sqlite3
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from athena.backup.deletion_storage import DeletionLedgerStorageMixin
from athena.backup.errors import (
    BackupRestoreError as BackupRestoreError,
)
from athena.backup.json_codec import _canonical_json
from athena.backup.retention import (
    BackupRetentionPlan,
    BackupRetentionPolicy,
    BackupRetentionResult,
    BackupTargetRecord,
    RetentionCandidate,
)
from athena.backup.retention import (
    plan_retention as calculate_retention_plan,
)
from athena.backup.target_lock import (
    BackupTargetBusyError,
    backup_target_lock,
)
from athena.chat.service import ChatService
from athena.common.ids import new_uuid7, uuid_from_blob, uuid_to_blob
from athena.common.time import utc_now_us
from athena.jobs.recovery import reconcile_jobs_after_restore
from athena.lifecycle.deletion import (
    DeletionLedgerRecord,
    apply_deletion_records,
    current_deletion_watermark,
    read_deletion_records,
)
from athena.lifecycle.runtime_lock import runtime_data_lock
from athena.source.blob_store import BlobStore
from athena.source.models import BlobStorageArea
from athena.storage.database import SQLiteDatabase
from athena.storage.durable_fs import (
    durable_mkdir,
    durable_replace,
    fsync_directory,
)
from athena.storage.paths import RuntimePaths
from athena.storage.schema import (
    DELETION_LEDGER_SCHEMA_VERSION,
    SCHEMA_VERSION,
    initialize_schema,
)

logger = logging.getLogger(__name__)



@dataclass(frozen=True, slots=True)
class BackupSnapshotRecord:
    snapshot_id: uuid.UUID
    target_id: uuid.UUID
    state: str
    verification_status: str
    relative_path: str
    snapshot_commit_seq: int | None
    schema_version: int | None
    db_sha256: bytes | None
    manifest_sha256: bytes | None
    object_count: int
    created_at_us: int
    completed_at_us: int | None
    last_verified_at_us: int | None
    pruned_at_us: int | None
    deletion_ledger_watermark: int = 0


class BackupService(DeletionLedgerStorageMixin):
    """Create complete-marker backups and restore them only into a new root."""

    FORMAT_VERSION = 1
    TARGET_FORMAT_VERSION = 1
    TARGET_DESCRIPTOR_NAME = ".athena-backup-target.json"
    RETENTION_TRASH_NAME = ".retention-trash"
    DELETION_LEDGER_DIR = "deletion-ledger"
    DELETION_LEDGER_RECORDS_DIR = "records"
    DELETION_LEDGER_RECORD_FORMAT_VERSION = 1
    DELETION_LEDGER_HEAD_NAME = "head.json"
    DELETION_LEDGER_HEAD_FORMAT_VERSION = 1

    def __init__(
        self,
        *,
        database: SQLiteDatabase,
        blob_store: BlobStore,
        paths: RuntimePaths,
        chat: ChatService,
        runtime_lock_root: Path | None = None,
    ) -> None:
        self.database = database
        self.blob_store = blob_store
        self.paths = paths
        self.chat = chat
        self.runtime_lock_root = runtime_lock_root


    def sync_deletion_ledger(
        self,
        target_id: uuid.UUID,
    ) -> BackupTargetRecord:
        """Bring one reachable backup target to the current deletion watermark."""
        record = self.get_target(
            target_id
        )

        if record.status == "retired":
            return record

        target = record.root_path

        if not target.is_dir():
            self._set_target_status(
                target_id,
                "offline",
            )
            return self.get_target(
                target_id
            )

        with backup_target_lock(
            target
        ):
            current = self.get_target(
                target_id
            )

            self._assert_target_available(
                current,
                target,
            )

            self._sync_deletion_ledger_locked(
                target_id=target_id,
                target=target,
            )

        return self.get_target(
            target_id
        )

    def sync_all_deletion_ledgers(
        self,
    ) -> tuple[
        BackupTargetRecord,
        ...,
    ]:
        """Best-effort fan-out; one unavailable target never blocks other targets."""
        results: list[
            BackupTargetRecord
        ] = []

        for target in self.list_targets():
            if target.status == "retired":
                results.append(
                    target
                )
                continue

            try:
                results.append(
                    self.sync_deletion_ledger(
                        target.target_id
                    )
                )

            except BackupTargetBusyError:
                logger.info(
                    "Deletion ledger target busy; propagation remains pending",
                    extra={
                        "event": "backup.deletion_sync_busy",
                        "target_id": str(
                            target.target_id
                        ),
                    },
                )
                results.append(
                    self.get_target(
                        target.target_id
                    )
                )

            except (
                BackupRestoreError,
                OSError,
            ) as exc:
                self._set_target_status(
                    target.target_id,
                    "offline",
                )

                logger.warning(
                    "Deletion ledger propagation failed for backup target",
                    extra={
                        "event": "backup.deletion_sync_failed",
                        "target_id": str(
                            target.target_id
                        ),
                        "error": type(exc).__name__,
                    },
                )

                results.append(
                    self.get_target(
                        target.target_id
                    )
                )

            except Exception:
                # Deletion itself has already committed. A replication
                # implementation fault must remain visible as pending,
                # but must not make the user retry the semantic deletion.
                logger.exception(
                    "Unexpected deletion-ledger propagation failure",
                    extra={
                        "event": "backup.deletion_sync_unexpected",
                        "target_id": str(
                            target.target_id
                        ),
                    },
                )

                results.append(
                    self.get_target(
                        target.target_id
                    )
                )

        return tuple(
            results
        )

    def _sync_deletion_ledger_locked(
        self,
        *,
        target_id: uuid.UUID,
        target: Path,
    ) -> int:
        local = read_deletion_records(
            self.database.connection
        )

        remote = (
            self._read_target_deletion_records(
                target
            )
        )

        if len(remote) > len(local):
            raise BackupRestoreError(
                "Backup target deletion ledger is ahead "
                "of the local durable ledger."
            )

        for index, remote_record in enumerate(
            remote
        ):
            if remote_record != local[index]:
                raise BackupRestoreError(
                    "Backup target deletion ledger "
                    "does not match the local ledger prefix."
                )

        for record in local[
            len(remote):
        ]:
            self._write_target_deletion_record(
                target,
                record,
            )

        self._write_target_deletion_head(
            target=target,
            target_id=target_id,
            records=local,
        )

        verified = (
            self._read_target_deletion_records(
                target
            )
        )

        if verified != local:
            raise BackupRestoreError(
                "Backup target deletion ledger "
                "failed post-write verification."
            )

        watermark = (
            local[-1].ledger_seq
            if local
            else 0
        )

        with self.database.write_transaction() as connection:
            connection.execute(
                """
                UPDATE backup_targets
                SET deletion_ledger_watermark = ?
                WHERE target_id = ?
                """,
                (
                    watermark,
                    uuid_to_blob(
                        target_id
                    ),
                ),
            )

        return watermark











    @staticmethod
    def _merge_restore_deletion_records(
        *groups: tuple[
            DeletionLedgerRecord,
            ...,
        ],
    ) -> tuple[
        DeletionLedgerRecord,
        ...,
    ]:
        by_sequence: dict[
            int,
            DeletionLedgerRecord,
        ] = {}

        by_entity: dict[
            uuid.UUID,
            DeletionLedgerRecord,
        ] = {}

        by_deletion: dict[
            uuid.UUID,
            DeletionLedgerRecord,
        ] = {}

        for group in groups:
            for record in group:
                existing_sequence = (
                    by_sequence.get(
                        record.ledger_seq
                    )
                )

                if (
                    existing_sequence is not None
                    and existing_sequence != record
                ):
                    raise BackupRestoreError(
                        "Conflicting deletion ledger sequence "
                        "between restore sources."
                    )

                existing_entity = (
                    by_entity.get(
                        record.entity_id
                    )
                )

                if (
                    existing_entity is not None
                    and existing_entity != record
                ):
                    raise BackupRestoreError(
                        "Conflicting deletion ledger entity "
                        "between restore sources."
                    )

                existing_deletion = (
                    by_deletion.get(
                        record.deletion_id
                    )
                )

                if (
                    existing_deletion is not None
                    and existing_deletion != record
                ):
                    raise BackupRestoreError(
                        "Conflicting deletion ID "
                        "between restore sources."
                    )

                by_sequence[
                    record.ledger_seq
                ] = record

                by_entity[
                    record.entity_id
                ] = record

                by_deletion[
                    record.deletion_id
                ] = record

        return tuple(
            by_sequence[
                sequence
            ]
            for sequence in sorted(
                by_sequence
            )
        )


    def create_snapshot(
        self,
        *,
        target_root: Path | None = None,
        target_id: uuid.UUID | None = None,
    ) -> BackupSnapshotRecord:
        self.recover_incomplete()
        actor_id = self.chat.ensure_local_user()
        target, resolved_target_id = self._resolve_target_for_create(
            target_root=target_root,
            target_id=target_id,
            actor_id=actor_id,
        )

        with runtime_data_lock(
            self.runtime_lock_root
        ):
            with backup_target_lock(target):
                self._sync_deletion_ledger_locked(
                    target_id=resolved_target_id,
                    target=target,
                )
                self._recover_retention_locked(
                    target_id=resolved_target_id,
                    target=target,
                )
                return self._create_snapshot_locked(
                    target=target,
                    target_id=resolved_target_id,
                )

    def _create_snapshot_locked(
        self,
        *,
        target: Path,
        target_id: uuid.UUID,
    ) -> BackupSnapshotRecord:
        snapshot_id = new_uuid7()
        created_at_us = utc_now_us()
        relative_path = f"snapshots/{snapshot_id}"
        snapshot_root = target / relative_path
        staging_root = target / "snapshots" / f".{snapshot_id}.partial"
        durable_mkdir(
            staging_root.parent,
            parents=True,
            exist_ok=True,
        )
        staging_root.mkdir(
            parents=False,
            exist_ok=False,
        )
        snapshot_db = staging_root / "athena.db"

        with self.database.write_transaction() as connection:
            connection.execute(
                """
                INSERT INTO backup_snapshots (
                    snapshot_id, target_id, state, verification_status,
                    relative_path, snapshot_commit_seq, schema_version,
                    db_sha256, manifest_sha256, object_count,
                    created_at_us, completed_at_us, failure_detail
                ) VALUES (?, ?, 'creating', 'unverified', ?, NULL, NULL,
                          NULL, NULL, 0, ?, NULL, NULL)
                """,
                (
                    uuid_to_blob(snapshot_id),
                    uuid_to_blob(target_id),
                    relative_path,
                    created_at_us,
                ),
            )

        try:
            destination = sqlite3.connect(snapshot_db)
            try:
                self.database.connection.backup(destination)
                destination.commit()
            finally:
                destination.close()
            _fsync_existing(snapshot_db)

            snap = sqlite3.connect(snapshot_db)
            snap.row_factory = sqlite3.Row
            try:
                integrity = str(snap.execute("PRAGMA integrity_check").fetchone()[0])
                if integrity.lower() != "ok":
                    raise BackupRestoreError(
                        f"SQLite backup integrity_check failed: {integrity}"
                    )
                schema_version = int(snap.execute("PRAGMA user_version").fetchone()[0])
                if schema_version != SCHEMA_VERSION:
                    raise BackupRestoreError(
                        f"Backup schema drifted: {schema_version} != {SCHEMA_VERSION}."
                    )
                row = snap.execute(
                    "SELECT COALESCE(MAX(commit_seq), 0) FROM commit_records"
                ).fetchone()
                snapshot_commit_seq = int(row[0]) if row is not None else 0
                deletion_ledger_watermark = (
                    current_deletion_watermark(
                        snap
                    )
                )
                blobs = tuple(
                    snap.execute(
                        """
                        SELECT
                            b.blob_id,
                            b.byte_length,
                            b.storage_area,
                            b.storage_locator,
                            b.integrity_sha256,
                            b.encryption_state
                        FROM blob_records AS b
                        WHERE EXISTS (
                            SELECT 1
                            FROM sources AS source
                            JOIN entity_registry AS source_entity
                              ON source_entity.entity_id = source.source_id
                            WHERE source.blob_id = b.blob_id
                              AND source_entity.lifecycle_state != 'deleted'
                        )
                        ORDER BY b.integrity_sha256, b.blob_id
                        """
                    ).fetchall()
                )
            finally:
                snap.close()

            with self.database.write_transaction() as connection:
                for row in blobs:
                    connection.execute(
                        """
                        INSERT INTO backup_snapshot_pins (
                            snapshot_id, blob_id, pinned_at_us
                        ) VALUES (?, ?, ?)
                        """,
                        (
                            uuid_to_blob(snapshot_id),
                            bytes(row["blob_id"]),
                            utc_now_us(),
                        ),
                    )
                connection.execute(
                    """
                    UPDATE backup_snapshots
                    SET snapshot_commit_seq = ?,
                        schema_version = ?,
                        deletion_ledger_watermark = ?
                    WHERE snapshot_id = ?
                    """,
                    (
                        snapshot_commit_seq,
                        schema_version,
                        deletion_ledger_watermark,
                        uuid_to_blob(snapshot_id),
                    ),
                )

            object_entries: list[dict[str, Any]] = []
            for row in blobs:
                digest = bytes(row["integrity_sha256"])
                expected_length = int(row["byte_length"])
                source_path = self.blob_store.verify_blob(
                    storage_area=BlobStorageArea(str(row["storage_area"])),
                    storage_locator=str(row["storage_locator"]),
                    expected_sha256=digest,
                    expected_length=expected_length,
                )
                object_relative = _object_relative_path(digest)
                destination_path = target / object_relative
                _copy_verified(
                    source_path,
                    destination_path,
                    expected_sha256=digest,
                    expected_length=expected_length,
                )
                object_entries.append(
                    {
                        "blob_id": str(uuid_from_blob(bytes(row["blob_id"]))),
                        "sha256": digest.hex(),
                        "byte_length": expected_length,
                        "object_path": object_relative.as_posix(),
                        "storage_locator": str(row["storage_locator"]),
                        "encryption_state": str(row["encryption_state"]),
                    }
                )

            db_sha256, _ = _hash_file(snapshot_db)
            manifest = {
                "format_version": self.FORMAT_VERSION,
                "snapshot_id": str(snapshot_id),
                "snapshot_commit_seq": snapshot_commit_seq,
                "schema_version": schema_version,
                "deletion_ledger_watermark": (
                    deletion_ledger_watermark
                ),
                "database": {
                    "path": "athena.db",
                    "sha256": db_sha256.hex(),
                },
                "objects": object_entries,
            }
            manifest_bytes = _canonical_json(manifest).encode("utf-8")
            manifest_sha256 = hashlib.sha256(manifest_bytes).digest()
            manifest_path = staging_root / "manifest.json"
            _write_fsynced(manifest_path, manifest_bytes)

            if not self._verify_payload_path(
                target=target,
                snapshot_root=staging_root,
                expected_manifest_sha256=manifest_sha256,
                expected_snapshot_id=snapshot_id,
            ):
                raise BackupRestoreError(
                    "Backup payload verification failed before completion marker."
                )
            if snapshot_root.exists():
                raise BackupRestoreError("Backup snapshot destination already exists.")
            durable_replace(staging_root, snapshot_root)
            if not self._verify_payload_path(
                target=target,
                snapshot_root=snapshot_root,
                expected_manifest_sha256=manifest_sha256,
                expected_snapshot_id=snapshot_id,
            ):
                raise BackupRestoreError(
                    "Final backup payload verification failed before completion marker."
                )
            _write_fsynced(
                snapshot_root / "complete.marker",
                (manifest_sha256.hex() + "\n").encode("ascii"),
            )
            if not self._verify_path(
                target=target,
                snapshot_root=snapshot_root,
                expected_manifest_sha256=manifest_sha256,
                expected_snapshot_id=snapshot_id,
            ):
                raise BackupRestoreError("Final backup verification failed.")

            completed_at_us = utc_now_us()
            with self.database.write_transaction() as connection:
                connection.execute(
                    """
                    UPDATE backup_snapshots
                    SET state = 'complete',
                        verification_status = 'verified_light',
                        db_sha256 = ?,
                        manifest_sha256 = ?,
                        object_count = ?,
                        completed_at_us = ?,
                        last_verified_at_us = ?,
                        failure_detail = NULL
                    WHERE snapshot_id = ?
                    """,
                    (
                        db_sha256,
                        manifest_sha256,
                        len(object_entries),
                        completed_at_us,
                        completed_at_us,
                        uuid_to_blob(snapshot_id),
                    ),
                )
                connection.execute(
                    "DELETE FROM backup_snapshot_pins WHERE snapshot_id = ?",
                    (uuid_to_blob(snapshot_id),),
                )
                connection.execute(
                    """
                    UPDATE backup_targets
                    SET deletion_ledger_watermark = MAX(
                        deletion_ledger_watermark,
                        ?
                    )
                    WHERE target_id = ?
                    """,
                    (
                        deletion_ledger_watermark,
                        uuid_to_blob(
                            target_id
                        ),
                    ),
                )
            return self.get_snapshot(snapshot_id)
        except BaseException as exc:
            shutil.rmtree(staging_root, ignore_errors=True)
            marker_published = (snapshot_root / "complete.marker").is_file()
            if not marker_published:
                # No completion marker means there is no restore point. Clean
                # any partially published directory and release pins.
                shutil.rmtree(snapshot_root, ignore_errors=True)
                with self.database.write_transaction() as connection:
                    connection.execute(
                        "DELETE FROM backup_snapshot_pins WHERE snapshot_id = ?",
                        (uuid_to_blob(snapshot_id),),
                    )
                    connection.execute(
                        """
                        UPDATE backup_snapshots
                        SET state = 'failed',
                            verification_status = 'failed',
                            failure_detail = ?
                        WHERE snapshot_id = ?
                        """,
                        (
                            type(exc).__name__,
                            uuid_to_blob(snapshot_id),
                        ),
                    )
            # If a complete.marker was already fsynced, preserve the row in
            # creating state and preserve its pins. Startup recovery verifies
            # the payload and either finalizes it or fails it deterministically.
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            if isinstance(exc, BackupRestoreError):
                raise
            raise BackupRestoreError(f"Backup failed: {type(exc).__name__}: {exc}") from exc

    def recover_incomplete(self) -> tuple[uuid.UUID, ...]:
        """Resolve interrupted backups without touching an active writer."""
        rows = self.database.connection.execute(
            """
            SELECT
                snapshot.snapshot_id,
                snapshot.target_id,
                snapshot.relative_path,
                target.root_path
            FROM backup_snapshots AS snapshot
            JOIN backup_targets AS target
              ON target.target_id = snapshot.target_id
            WHERE snapshot.state = 'creating'
            ORDER BY snapshot.created_at_us, snapshot.snapshot_id
            """
        ).fetchall()

        recovered: list[uuid.UUID] = []

        for row in rows:
            snapshot_id = uuid_from_blob(
                bytes(row["snapshot_id"])
            )
            target_id = uuid_from_blob(
                bytes(row["target_id"])
            )
            target = Path(
                str(row["root_path"])
            )

            if not target.is_absolute() or not target.is_dir():
                self._set_target_status(
                    target_id,
                    "offline",
                )
                continue

            try:
                with backup_target_lock(target):
                    try:
                        record = self.get_target(target_id)
                        self._assert_target_available(
                            record,
                            target,
                        )
                    except BackupRestoreError:
                        continue

                    if self._recover_incomplete_row_locked(
                        row=row,
                        target=target,
                    ):
                        recovered.append(snapshot_id)

            except BackupTargetBusyError:
                continue

        return tuple(recovered)

    def _recover_incomplete_row_locked(
        self,
        *,
        row: sqlite3.Row,
        target: Path,
    ) -> bool:
        snapshot_id = uuid_from_blob(
            bytes(row["snapshot_id"])
        )
        snapshot_root = target / str(
            row["relative_path"]
        )
        staging_root = (
            target
            / "snapshots"
            / f".{snapshot_id}.partial"
        )
        marker = snapshot_root / "complete.marker"

        valid = False
        manifest_sha256: bytes | None = None
        db_sha256: bytes | None = None
        snapshot_commit_seq: int | None = None
        schema_version: int | None = None
        deletion_ledger_watermark: int | None = None
        objects: list[Any] | None = None

        if marker.is_file():
            try:
                manifest_sha256 = bytes.fromhex(
                    marker.read_text(
                        encoding="ascii"
                    ).strip()
                )
            except (OSError, ValueError):
                manifest_sha256 = None

            if (
                manifest_sha256 is not None
                and len(manifest_sha256) == 32
            ):
                valid = self._verify_path(
                    target=target,
                    snapshot_root=snapshot_root,
                    expected_manifest_sha256=(
                        manifest_sha256
                    ),
                    expected_snapshot_id=snapshot_id,
                )

        if valid and manifest_sha256 is not None:
            manifest = _read_manifest(
                snapshot_root / "manifest.json"
            )
            database_meta = manifest.get(
                "database"
            )
            raw_objects = manifest.get(
                "objects"
            )

            if (
                not isinstance(database_meta, dict)
                or not isinstance(raw_objects, list)
            ):
                valid = False
            else:
                objects = raw_objects

                try:
                    db_sha256 = bytes.fromhex(
                        _required_str(
                            database_meta,
                            "sha256",
                        )
                    )
                    snapshot_commit_seq = (
                        _required_int(
                            manifest,
                            "snapshot_commit_seq",
                        )
                    )
                    schema_version = _required_int(
                        manifest,
                        "schema_version",
                    )
                    deletion_ledger_watermark = (
                        _required_int(
                            manifest,
                            "deletion_ledger_watermark",
                        )
                        if schema_version
                        >= DELETION_LEDGER_SCHEMA_VERSION
                        else 0
                    )
                except (
                    BackupRestoreError,
                    ValueError,
                ):
                    valid = False

        if (
            valid
            and manifest_sha256 is not None
            and db_sha256 is not None
            and snapshot_commit_seq is not None
            and schema_version is not None
            and deletion_ledger_watermark is not None
            and objects is not None
        ):
            completed_at_us = utc_now_us()

            with self.database.write_transaction() as connection:
                cursor = connection.execute(
                    """
                    UPDATE backup_snapshots
                    SET state = 'complete',
                        verification_status = 'verified_light',
                        snapshot_commit_seq = ?,
                        schema_version = ?,
                        deletion_ledger_watermark = ?,
                        db_sha256 = ?,
                        manifest_sha256 = ?,
                        object_count = ?,
                        completed_at_us = ?,
                        last_verified_at_us = ?,
                        failure_detail = NULL
                    WHERE snapshot_id = ?
                      AND state = 'creating'
                    """,
                    (
                        snapshot_commit_seq,
                        schema_version,
                        deletion_ledger_watermark,
                        db_sha256,
                        manifest_sha256,
                        len(objects),
                        completed_at_us,
                        completed_at_us,
                        uuid_to_blob(snapshot_id),
                    ),
                )

                if cursor.rowcount == 1:
                    connection.execute(
                        """
                        DELETE FROM backup_snapshot_pins
                        WHERE snapshot_id = ?
                        """,
                        (
                            uuid_to_blob(
                                snapshot_id
                            ),
                        ),
                    )
                    connection.execute(
                        """
                        UPDATE backup_targets
                        SET deletion_ledger_watermark = MAX(
                            deletion_ledger_watermark,
                            ?
                        )
                        WHERE target_id = ?
                        """,
                        (
                            deletion_ledger_watermark,
                            bytes(
                                row[
                                    "target_id"
                                ]
                            ),
                        ),
                    )

            shutil.rmtree(
                staging_root,
                ignore_errors=True,
            )

            return cursor.rowcount == 1

        shutil.rmtree(
            staging_root,
            ignore_errors=True,
        )
        shutil.rmtree(
            snapshot_root,
            ignore_errors=True,
        )

        with self.database.write_transaction() as connection:
            connection.execute(
                """
                DELETE FROM backup_snapshot_pins
                WHERE snapshot_id = ?
                """,
                (
                    uuid_to_blob(
                        snapshot_id
                    ),
                ),
            )
            connection.execute(
                """
                UPDATE backup_snapshots
                SET state = 'failed',
                    verification_status = 'failed',
                    failure_detail =
                        'BackupStartupRecoveryError'
                WHERE snapshot_id = ?
                  AND state = 'creating'
                """,
                (
                    uuid_to_blob(
                        snapshot_id
                    ),
                ),
            )

        return False


    def verify_light(
        self,
        snapshot_id: uuid.UUID,
    ) -> BackupSnapshotRecord:
        """Run routine inexpensive verification of a completed restore point."""
        record = self.get_snapshot(
            snapshot_id
        )

        self._require_verifiable_snapshot(
            record
        )

        target_state = self.target_status(
            record.target_id
        )

        if target_state.status != "active":
            raise BackupRestoreError(
                f"Backup target {record.target_id} is offline."
            )

        target = self._target_for_record(
            record
        )

        snapshot_root = (
            target
            / record.relative_path
        )

        if record.manifest_sha256 is None:
            raise BackupRestoreError(
                "Backup snapshot has no recorded manifest hash."
            )

        try:
            with backup_target_lock(target):
                valid = self._verify_light_path(
                    target=target,
                    snapshot_root=snapshot_root,
                    expected_manifest_sha256=(
                        record.manifest_sha256
                    ),
                    expected_snapshot_id=(
                        record.snapshot_id
                    ),
                )

        except OSError:
            logger.warning(
                "Backup Light verification aborted by environment",
                extra={
                    "event": (
                        "backup."
                        "verification_light_environment_error"
                    ),
                    "snapshot_id": str(
                        record.snapshot_id
                    ),
                    "target_id": str(
                        record.target_id
                    ),
                },
            )
            raise

        if not valid:
            refreshed = self.target_status(
                record.target_id
            )

            if refreshed.status != "active":
                raise BackupRestoreError(
                    f"Backup target {record.target_id} "
                    "became offline during verification."
                )

            self._record_verification_failure(
                record,
                mode="light",
                detail="BackupLightVerificationError",
            )

            raise BackupRestoreError(
                "Backup Light verification failed."
            )

        verified = (
            self._record_verification_success(
                record,
                mode="light",
            )
        )

        logger.info(
            "Backup Light verification completed",
            extra={
                "event": (
                    "backup.verification_light_completed"
                ),
                "snapshot_id": str(
                    record.snapshot_id
                ),
                "target_id": str(
                    record.target_id
                ),
            },
        )

        return verified

    def verify_deep(
        self,
        snapshot_id: uuid.UUID,
    ) -> BackupSnapshotRecord:
        """Hash every object and prove isolated restore capability."""
        record = self.get_snapshot(
            snapshot_id
        )

        self._require_verifiable_snapshot(
            record
        )

        target_state = self.target_status(
            record.target_id
        )

        if target_state.status != "active":
            raise BackupRestoreError(
                f"Backup target {record.target_id} is offline."
            )

        target = self._target_for_record(
            record
        )

        snapshot_root = (
            target
            / record.relative_path
        )

        if record.manifest_sha256 is None:
            raise BackupRestoreError(
                "Backup snapshot has no recorded manifest hash."
            )

        try:
            with backup_target_lock(target):
                if not self._verify_path(
                    target=target,
                    snapshot_root=snapshot_root,
                    expected_manifest_sha256=(
                        record.manifest_sha256
                    ),
                    expected_snapshot_id=(
                        record.snapshot_id
                    ),
                ):
                    raise BackupRestoreError(
                        "Backup Deep verification failed."
                    )

                self.paths.local_root.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                with tempfile.TemporaryDirectory(
                    prefix=(
                        "athena-backup-deep-verify-"
                    ),
                    dir=self.paths.local_root.parent,
                ) as temporary_parent:
                    destination = (
                        Path(temporary_parent)
                        / "restore-smoke"
                    )

                    restored = (
                        self._restore_verified_path(
                            target=target,
                            snapshot_root=(
                                snapshot_root
                            ),
                            deletion_records=(
                                self._read_target_deletion_records(
                                    target
                                )
                            ),
                            deletion_ledger_source="target_sidecar",
                            deletion_currentness_guaranteed=False,
                            destination_root=(
                                destination
                            ),
                        )
                    )

                    if not (
                        restored
                        / "state"
                        / "restore.complete"
                    ).is_file():
                        raise BackupRestoreError(
                            "Deep verification restore smoke "
                            "did not publish restore.complete."
                        )

                    if not (
                        restored
                        / "state"
                        / "athena.db"
                    ).is_file():
                        raise BackupRestoreError(
                            "Deep verification restore smoke "
                            "did not publish athena.db."
                        )

        except OSError:
            logger.warning(
                "Backup Deep verification aborted by environment",
                extra={
                    "event": (
                        "backup."
                        "verification_deep_environment_error"
                    ),
                    "snapshot_id": str(
                        record.snapshot_id
                    ),
                    "target_id": str(
                        record.target_id
                    ),
                },
            )
            raise

        except BackupRestoreError as exc:
            refreshed = self.target_status(
                record.target_id
            )

            if refreshed.status == "active":
                self._record_verification_failure(
                    record,
                    mode="deep",
                    detail=type(exc).__name__,
                )

            logger.warning(
                "Backup Deep verification failed",
                extra={
                    "event": (
                        "backup.verification_deep_failed"
                    ),
                    "snapshot_id": str(
                        record.snapshot_id
                    ),
                    "target_id": str(
                        record.target_id
                    ),
                    "error_type": (
                        type(exc).__name__
                    ),
                },
            )

            raise

        verified = (
            self._record_verification_success(
                record,
                mode="deep",
            )
        )

        logger.info(
            "Backup Deep verification completed",
            extra={
                "event": (
                    "backup.verification_deep_completed"
                ),
                "snapshot_id": str(
                    record.snapshot_id
                ),
                "target_id": str(
                    record.target_id
                ),
            },
        )

        return verified

    def _require_verifiable_snapshot(
        self,
        record: BackupSnapshotRecord,
    ) -> None:
        row = self.database.connection.execute(
            """
            SELECT state, pruned_at_us
            FROM backup_snapshots
            WHERE snapshot_id = ?
            """,
            (
                uuid_to_blob(
                    record.snapshot_id
                ),
            ),
        ).fetchone()

        if row is None:
            raise BackupRestoreError(
                f"Backup snapshot "
                f"{record.snapshot_id} not found."
            )

        if (
            str(row["state"]) != "complete"
            or row["pruned_at_us"] is not None
        ):
            raise BackupRestoreError(
                "Backup snapshot is not an active "
                "completed restore point."
            )

    def _record_verification_success(
        self,
        record: BackupSnapshotRecord,
        *,
        mode: str,
    ) -> BackupSnapshotRecord:
        if mode not in {
            "light",
            "deep",
        }:
            raise ValueError(
                f"Unsupported verification mode: {mode!r}"
            )

        now_us = utc_now_us()

        with self.database.write_transaction() as connection:
            if mode == "light":
                cursor = connection.execute(
                    """
                    UPDATE backup_snapshots
                    SET verification_status = CASE
                            WHEN verification_status = 'verified_deep'
                                THEN 'verified_deep'
                            ELSE 'verified_light'
                        END,
                        last_verified_at_us = ?,
                        failure_detail = NULL
                    WHERE snapshot_id = ?
                      AND state = 'complete'
                      AND pruned_at_us IS NULL
                    """,
                    (
                        now_us,
                        uuid_to_blob(
                            record.snapshot_id
                        ),
                    ),
                )
            else:
                cursor = connection.execute(
                    """
                    UPDATE backup_snapshots
                    SET verification_status = 'verified_deep',
                        last_verified_at_us = ?,
                        failure_detail = NULL
                    WHERE snapshot_id = ?
                      AND state = 'complete'
                      AND pruned_at_us IS NULL
                    """,
                    (
                        now_us,
                        uuid_to_blob(
                            record.snapshot_id
                        ),
                    ),
                )

        if cursor.rowcount != 1:
            raise BackupRestoreError(
                "Backup verification result could "
                "not be persisted safely."
            )

        return self.get_snapshot(
            record.snapshot_id
        )

    def _record_verification_failure(
        self,
        record: BackupSnapshotRecord,
        *,
        mode: str,
        detail: str,
    ) -> None:
        now_us = utc_now_us()

        with self.database.write_transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE backup_snapshots
                SET state = 'failed',
                    verification_status = 'failed',
                    last_verified_at_us = ?,
                    failure_detail = ?
                WHERE snapshot_id = ?
                  AND state = 'complete'
                  AND pruned_at_us IS NULL
                """,
                (
                    now_us,
                    (
                        f"{mode} verification: "
                        f"{detail}"
                    )[:2000],
                    uuid_to_blob(
                        record.snapshot_id
                    ),
                ),
            )

        if cursor.rowcount != 1:
            raise BackupRestoreError(
                "Backup verification failure could "
                "not be persisted safely."
            )

        logger.warning(
            "Backup verification failure recorded",
            extra={
                "event": (
                    "backup.verification_failed"
                ),
                "snapshot_id": str(
                    record.snapshot_id
                ),
                "target_id": str(
                    record.target_id
                ),
                "verification_mode": mode,
            },
        )

    def verify(
        self,
        snapshot_id: uuid.UUID,
    ) -> BackupSnapshotRecord:
        record = self.get_snapshot(snapshot_id)
        target = self._target_for_record(record)

        with backup_target_lock(target):
            return self._verify_record_locked(
                record,
                target,
            )

    def _verify_record_locked(
        self,
        record: BackupSnapshotRecord,
        target: Path,
    ) -> BackupSnapshotRecord:
        if record.pruned_at_us is not None:
            raise BackupRestoreError(
                "Backup snapshot was pruned by retention."
            )

        if (
            record.state != "complete"
            or record.verification_status
            not in {
                "verified_light",
                "verified_deep",
            }
        ):
            raise BackupRestoreError(
                "Backup snapshot is not a completed restore point."
            )

        target_record = self.get_target(
            record.target_id
        )
        self._assert_target_available(
            target_record,
            target,
        )

        snapshot_root = (
            target
            / record.relative_path
        )

        if record.manifest_sha256 is None:
            raise BackupRestoreError(
                "Backup snapshot has no recorded manifest hash."
            )

        if not self._verify_path(
            target=target,
            snapshot_root=snapshot_root,
            expected_manifest_sha256=(
                record.manifest_sha256
            ),
            expected_snapshot_id=record.snapshot_id,
        ):
            raise BackupRestoreError(
                "Backup verification failed."
            )

        verified_at_us = utc_now_us()

        with self.database.write_transaction() as connection:
            connection.execute(
                """
                UPDATE backup_snapshots
                SET last_verified_at_us = ?
                WHERE snapshot_id = ?
                  AND pruned_at_us IS NULL
                """,
                (
                    verified_at_us,
                    uuid_to_blob(
                        record.snapshot_id
                    ),
                ),
            )

        return self.get_snapshot(
            record.snapshot_id
        )

    def restore_to(
        self,
        snapshot_id: uuid.UUID,
        *,
        destination_root: Path,
    ) -> Path:
        record = self.get_snapshot(snapshot_id)
        target = self._target_for_record(record)

        live_deletions = read_deletion_records(
            self.database.connection
        )

        with backup_target_lock(target):
            self._sync_deletion_ledger_locked(
                target_id=record.target_id,
                target=target,
            )

            target_deletions = (
                self._read_target_deletion_records(
                    target
                )
            )

            available_deletions = (
                self._merge_restore_deletion_records(
                    live_deletions,
                    target_deletions,
                )
            )

            verified = self._verify_record_locked(
                record,
                target,
            )

            snapshot_root = (
                target
                / verified.relative_path
            )

            return self._restore_verified_path(
                target=target,
                snapshot_root=snapshot_root,
                destination_root=destination_root,
                deletion_records=available_deletions,
                deletion_ledger_source="live_and_target",
                deletion_currentness_guaranteed=True,
            )


    @classmethod
    def restore_path_without_live_runtime(
        cls,
        snapshot_root: Path,
        *,
        destination_root: Path,
        paths: RuntimePaths,
    ) -> Path:
        """Restore a completed backup without opening the configured live database.

        The short-lived instance deliberately receives only RuntimePaths. It never
        escapes this method and may execute only restore_path(), whose verified
        restore pipeline does not require the live database, BlobStore, ChatService,
        model provider, security unlock state, or optional runtime services.
        """
        restore_only = cls.__new__(cls)
        restore_only.paths = paths
        return restore_only.restore_path(
            snapshot_root,
            destination_root=destination_root,
        )

    def restore_path(
        self,
        snapshot_root: Path,
        *,
        destination_root: Path,
    ) -> Path:
        """Restore from a self-contained completed backup path after loss of live DB metadata."""
        requested_snapshot = snapshot_root.expanduser()
        if not requested_snapshot.is_absolute():
            raise BackupRestoreError("Backup snapshot path must be absolute.")
        snapshot = requested_snapshot.resolve()
        if snapshot.parent.name != "snapshots":
            raise BackupRestoreError(
                "Backup snapshot path must be <backup-root>/snapshots/<snapshot-id>."
            )
        try:
            snapshot_id = uuid.UUID(snapshot.name)
        except ValueError as exc:
            raise BackupRestoreError(
                "Backup snapshot directory name must be its UUID."
            ) from exc
        target = snapshot.parent.parent
        marker = snapshot / "complete.marker"
        if not marker.is_file():
            raise BackupRestoreError("Backup snapshot has no complete.marker.")
        try:
            expected_manifest_sha256 = bytes.fromhex(
                marker.read_text(encoding="ascii").strip()
            )
        except (OSError, ValueError) as exc:
            raise BackupRestoreError("Backup completion marker is invalid.") from exc
        if len(expected_manifest_sha256) != 32:
            raise BackupRestoreError("Backup completion marker is not SHA-256.")
        with backup_target_lock(target):
            if not self._verify_path(
                target=target,
                snapshot_root=snapshot,
                expected_manifest_sha256=expected_manifest_sha256,
                expected_snapshot_id=snapshot_id,
            ):
                raise BackupRestoreError(
                    "Backup path verification failed."
                )

            ledger_root = (
                target
                / self.DELETION_LEDGER_DIR
            )

            target_deletions = (
                self._read_target_deletion_records(
                    target
                )
            )

            source = (
                "target_sidecar"
                if ledger_root.exists()
                else "snapshot_only"
            )

            return self._restore_verified_path(
                target=target,
                snapshot_root=snapshot,
                destination_root=destination_root,
                deletion_records=target_deletions,
                deletion_ledger_source=source,
                deletion_currentness_guaranteed=False,
            )

    def _restore_verified_path(
        self,
        *,
        target: Path,
        snapshot_root: Path,
        destination_root: Path,
        deletion_records: tuple[
            DeletionLedgerRecord,
            ...,
        ],
        deletion_ledger_source: str,
        deletion_currentness_guaranteed: bool,
    ) -> Path:
        requested_destination = destination_root.expanduser()
        if not requested_destination.is_absolute():
            raise BackupRestoreError("Restore destination must be an absolute path.")
        destination = requested_destination.resolve()
        live = self.paths.local_root.resolve()
        if destination == live or live in destination.parents or destination in live.parents:
            raise BackupRestoreError(
                "Restore destination must be isolated from live ATHENA roots."
            )
        target_resolved = target.resolve()
        if (
            destination == target_resolved
            or target_resolved in destination.parents
            or destination in target_resolved.parents
        ):
            raise BackupRestoreError(
                "Restore destination must not overlap the backup target."
            )
        if destination.exists():
            raise BackupRestoreError(
                "Restore destination must not already exist; ATHENA publishes restores atomically."
            )
        if not destination.name:
            raise BackupRestoreError("Restore destination must have a final directory name.")
        durable_mkdir(
            destination.parent,
            parents=True,
            exist_ok=True,
        )
        staging = destination.with_name(
            f".{destination.name}.{new_uuid7()}.restore-partial"
        )
        if staging.exists():
            raise BackupRestoreError("Restore staging destination already exists.")
        staging.mkdir(parents=False, exist_ok=False)
        publication_identity: tuple[int, int] | None = None

        try:
            manifest = _read_manifest(snapshot_root / "manifest.json")

            raw_snapshot_deletion_watermark = (
                manifest.get(
                    "deletion_ledger_watermark",
                    0,
                )
            )

            if (
                not isinstance(
                    raw_snapshot_deletion_watermark,
                    int,
                )
                or isinstance(
                    raw_snapshot_deletion_watermark,
                    bool,
                )
                or raw_snapshot_deletion_watermark < 0
            ):
                raise BackupRestoreError(
                    "Backup manifest deletion-ledger "
                    "watermark is invalid."
                )

            snapshot_deletion_watermark = (
                raw_snapshot_deletion_watermark
            )

            state_root = staging / "state"
            spool_root = state_root / "spool"
            durable_mkdir(
                state_root,
                parents=True,
                exist_ok=True,
            )
            durable_mkdir(
                spool_root,
                parents=True,
                exist_ok=True,
            )
            restored_db = state_root / "athena.db"
            shutil.copy2(snapshot_root / "athena.db", restored_db)
            database_meta = manifest.get("database")
            if not isinstance(database_meta, dict):
                raise BackupRestoreError("Backup manifest database metadata is invalid.")
            expected_db_sha = bytes.fromhex(_required_str(database_meta, "sha256"))
            copied_db_sha, _copied_db_length = _hash_file(restored_db)
            if copied_db_sha != expected_db_sha:
                raise BackupRestoreError(
                    "Restored SQLite copy failed SHA-256 verification."
                )

            objects = manifest.get("objects")
            if not isinstance(objects, list):
                raise BackupRestoreError("Backup manifest objects are invalid.")
            for item in objects:
                if not isinstance(item, dict):
                    raise BackupRestoreError("Backup manifest object entry is invalid.")
                digest = bytes.fromhex(_required_str(item, "sha256"))
                length = _required_int(item, "byte_length")
                object_relative = _safe_relative(_required_str(item, "object_path"))
                if object_relative != _object_relative_path(digest):
                    raise BackupRestoreError(
                        "Backup manifest object path disagrees with its content hash."
                    )
                storage_locator = _safe_relative(_required_str(item, "storage_locator"))
                _copy_verified(
                    _safe_existing_file(target, object_relative),
                    spool_root / storage_locator,
                    expected_sha256=digest,
                    expected_length=length,
                )

            restored = sqlite3.connect(restored_db, autocommit=True)
            restored.row_factory = sqlite3.Row
            try:
                restored.execute("PRAGMA foreign_keys = ON")
                restored.execute("BEGIN IMMEDIATE")
                restored.execute("UPDATE blob_records SET storage_area = 'spool'")
                restored.execute("UPDATE backup_targets SET status = 'offline'")
                restored.execute("DELETE FROM backup_snapshot_pins")
                restored.execute("COMMIT")
                initialize_schema(
                    restored,
                    created_at_us=utc_now_us(),
                )
                apply_deletion_records(
                    restored,
                    deletion_records,
                )
                self._remove_restored_deleted_source_payloads(
                    restored=restored,
                    spool_root=spool_root,
                )

                job_recovery = reconcile_jobs_after_restore(
                    restored,
                    now_us=utc_now_us(),
                )

                if job_recovery.total:
                    logger.warning(
                        "Reconciled in-flight durable jobs in restored runtime",
                        extra={
                            "event": "backup.restore_jobs_reconciled",
                            "paused_running_jobs": (
                                job_recovery.paused_running
                            ),
                            "cancelled_requested_jobs": (
                                job_recovery.cancelled_requested
                            ),
                        },
                    )

                restored_deletion_watermark = (
                    current_deletion_watermark(
                        restored
                    )
                )

                integrity = str(
                    restored.execute(
                        "PRAGMA integrity_check"
                    ).fetchone()[0]
                )
                if integrity.lower() != "ok":
                    raise BackupRestoreError(
                        f"Restored database integrity_check failed: {integrity}"
                    )
                if restored.execute("PRAGMA foreign_key_check").fetchall():
                    raise BackupRestoreError(
                        "Restored database foreign-key check failed."
                    )
                if int(restored.execute("PRAGMA user_version").fetchone()[0]) != SCHEMA_VERSION:
                    raise BackupRestoreError(
                        "Restored database schema version is incompatible."
                    )
            finally:
                if restored.in_transaction:
                    restored.execute("ROLLBACK")
                restored.close()

            deletion_status = {
                "available_watermark": (
                    restored_deletion_watermark
                ),
                "currentness_guaranteed": (
                    deletion_currentness_guaranteed
                ),
                "format_version": 1,
                "snapshot_watermark": (
                    snapshot_deletion_watermark
                ),
                "source": (
                    deletion_ledger_source
                ),
            }

            _write_fsynced(
                state_root
                / "restore.deletion-ledger.json",
                _canonical_json(
                    deletion_status
                ).encode(
                    "utf-8"
                ),
            )

            if not deletion_currentness_guaranteed:
                logger.warning(
                    "Restore deletion-ledger completeness "
                    "cannot be independently proven without "
                    "the original live runtime metadata",
                    extra={
                        "event": (
                            "backup.restore_deletion_ledger_warning"
                        ),
                        "deletion_ledger_source": (
                            deletion_ledger_source
                        ),
                        "available_watermark": (
                            restored_deletion_watermark
                        ),
                        "snapshot_watermark": (
                            snapshot_deletion_watermark
                        ),
                    },
                )

            durable_mkdir(
                staging / "derived",
                parents=True,
                exist_ok=True,
            )

            _write_fsynced(
                state_root / "restore.complete",
                b"ATHENA_RESTORE_COMPLETE_V1\n",
            )

            # state/ and derived/ are directory entries owned by the staging
            # directory. Persist them before publishing the staging directory
            # itself.
            fsync_directory(staging)

            staging_stat = staging.stat()
            publication_identity = (
                staging_stat.st_dev,
                staging_stat.st_ino,
            )

            durable_replace(
                staging,
                destination,
            )
            return destination

        except BaseException:
            shutil.rmtree(
                staging,
                ignore_errors=True,
            )

            # durable_replace may have completed the atomic rename and then
            # failed while making that rename durable. The destination was
            # required to be absent at entry. Remove it only if its filesystem
            # identity proves that it is the exact staging directory created
            # by this restore.
            if (
                publication_identity is not None
                and destination.exists()
                and destination.is_dir()
            ):
                try:
                    destination_stat = destination.stat()
                except OSError:
                    destination_stat = None

                if (
                    destination_stat is not None
                    and (
                        destination_stat.st_dev,
                        destination_stat.st_ino,
                    )
                    == publication_identity
                ):
                    shutil.rmtree(
                        destination
                    )
                    fsync_directory(
                        destination.parent
                    )

            raise


    @staticmethod
    def _remove_restored_deleted_source_payloads(
        *,
        restored: sqlite3.Connection,
        spool_root: Path,
    ) -> None:
        """Prevent logical deletion replay from reactivating Raw Source bytes."""

        restored.execute(
            """
            UPDATE sources
            SET original_name = NULL,
                original_modified_at_us = NULL,
                source_uri = NULL
            WHERE source_id IN (
                SELECT entity_id
                FROM entity_registry
                WHERE entity_type = 'source'
                  AND lifecycle_state = 'deleted'
            )
            """
        )

        rows = restored.execute(
            """
            SELECT
                b.storage_locator,
                b.integrity_sha256,
                b.byte_length
            FROM blob_records AS b
            WHERE EXISTS (
                SELECT 1
                FROM sources AS deleted_source
                JOIN entity_registry AS deleted_entity
                  ON deleted_entity.entity_id = deleted_source.source_id
                WHERE deleted_source.blob_id = b.blob_id
                  AND deleted_entity.lifecycle_state = 'deleted'
            )
              AND NOT EXISTS (
                SELECT 1
                FROM sources AS live_source
                JOIN entity_registry AS live_entity
                  ON live_entity.entity_id = live_source.source_id
                WHERE live_source.blob_id = b.blob_id
                  AND live_entity.lifecycle_state != 'deleted'
            )
            ORDER BY b.blob_id
            """
        ).fetchall()

        for row in rows:
            relative = _safe_relative(
                str(
                    row[
                        "storage_locator"
                    ]
                )
            )

            path = (
                spool_root
                / relative
            )

            if path.is_symlink():
                raise BackupRestoreError(
                    "Restored deleted Source blob "
                    "resolved to a symbolic link."
                )

            if not path.exists():
                continue

            if not path.is_file():
                raise BackupRestoreError(
                    "Restored deleted Source blob "
                    "is not a regular file."
                )

            digest, length = (
                _hash_file(
                    path
                )
            )

            if (
                digest
                != bytes(
                    row[
                        "integrity_sha256"
                    ]
                )
                or length
                != int(
                    row[
                        "byte_length"
                    ]
                )
            ):
                raise BackupRestoreError(
                    "Restored deleted Source blob "
                    "failed integrity verification "
                    "before purge."
                )

            try:
                path.unlink()

            except OSError as exc:
                raise BackupRestoreError(
                    "Restored deleted Source blob "
                    "could not be removed before activation."
                ) from exc

            if (
                path.exists()
                or path.is_symlink()
            ):
                raise BackupRestoreError(
                    "Restored deleted Source blob "
                    "still exists after purge."
                )

    def get_snapshot(self, snapshot_id: uuid.UUID) -> BackupSnapshotRecord:
        row = self.database.connection.execute(
            "SELECT * FROM backup_snapshots WHERE snapshot_id = ?",
            (uuid_to_blob(snapshot_id),),
        ).fetchone()
        if row is None:
            raise BackupRestoreError(f"Backup snapshot {snapshot_id} not found.")
        return _snapshot_from_row(row)

    def list_snapshots(self, *, limit: int = 50) -> tuple[BackupSnapshotRecord, ...]:
        if not 1 <= limit <= 500:
            raise ValueError("Backup list limit must be between 1 and 500.")
        rows = self.database.connection.execute(
            """
            SELECT * FROM backup_snapshots
            ORDER BY created_at_us DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return tuple(_snapshot_from_row(row) for row in rows)

    def register_target(
        self,
        target_root: Path,
    ) -> BackupTargetRecord:
        actor_id = self.chat.ensure_local_user()
        target = self._normalize_target_path(
            target_root
        )

        existing = self.database.connection.execute(
            """
            SELECT target_id
            FROM backup_targets
            WHERE root_path = ?
            """,
            (str(target),),
        ).fetchone()

        if (
            existing is not None
            and not target.is_dir()
        ):
            target_id = uuid_from_blob(
                bytes(existing["target_id"])
            )
            self._set_target_status(
                target_id,
                "offline",
            )
            raise BackupRestoreError(
                "Known backup target is offline; "
                "refusing to recreate its root."
            )

        if not target.exists():
            durable_mkdir(
                target,
                parents=True,
                exist_ok=False,
            )

        if not target.is_dir():
            raise BackupRestoreError(
                "Backup target is not a directory."
            )

        with backup_target_lock(target):
            registered = self._register_target_locked(
                target=target,
                actor_id=actor_id,
            )

        return self.sync_deletion_ledger(
            registered.target_id
        )

    def _register_target_locked(
        self,
        *,
        target: Path,
        actor_id: uuid.UUID,
    ) -> BackupTargetRecord:
        descriptor_id = self._read_target_descriptor(
            target
        )

        root_row = self.database.connection.execute(
            """
            SELECT target_id
            FROM backup_targets
            WHERE root_path = ?
            """,
            (str(target),),
        ).fetchone()

        root_record = (
            self.get_target(
                uuid_from_blob(
                    bytes(
                        root_row["target_id"]
                    )
                )
            )
            if root_row is not None
            else None
        )

        if (
            root_record is not None
            and descriptor_id is not None
            and descriptor_id
            != root_record.target_id
        ):
            self._set_target_status(
                root_record.target_id,
                "offline",
            )
            raise BackupRestoreError(
                "Backup target descriptor disagrees "
                "with registered target identity."
            )

        if descriptor_id is not None:
            descriptor_row = self.database.connection.execute(
                """
                SELECT target_id
                FROM backup_targets
                WHERE target_id = ?
                """,
                (
                    uuid_to_blob(
                        descriptor_id
                    ),
                ),
            ).fetchone()

            if descriptor_row is not None:
                if (
                    root_record is not None
                    and root_record.target_id
                    != descriptor_id
                ):
                    raise BackupRestoreError(
                        "Backup target path is already "
                        "owned by another target."
                    )

                with self.database.write_transaction() as connection:
                    connection.execute(
                        """
                        UPDATE backup_targets
                        SET root_path = ?,
                            status = 'active',
                            identity_initialized = 1
                        WHERE target_id = ?
                        """,
                        (
                            str(target),
                            uuid_to_blob(
                                descriptor_id
                            ),
                        ),
                    )

                return self.get_target(
                    descriptor_id
                )

            if root_record is not None:
                raise BackupRestoreError(
                    "Backup target identity is inconsistent."
                )

            with self.database.write_transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO backup_targets (
                        target_id,
                        root_path,
                        status,
                        created_at_us,
                        created_by_actor_id,
                        identity_initialized,
                        retention_daily,
                        retention_weekly,
                        retention_monthly,
                        retention_yearly
                    ) VALUES (
                        ?, ?, 'active', ?, ?, 1,
                        7, 4, 12, 5
                    )
                    """,
                    (
                        uuid_to_blob(
                            descriptor_id
                        ),
                        str(target),
                        utc_now_us(),
                        uuid_to_blob(
                            actor_id
                        ),
                    ),
                )

            return self.get_target(
                descriptor_id
            )

        if root_record is not None:
            self._assert_target_available(
                root_record,
                target,
            )
            return self.get_target(
                root_record.target_id
            )

        non_control_entries = tuple(
            item
            for item in target.iterdir()
            if item.name
            != ".athena-backup.lock"
        )

        if non_control_entries:
            raise BackupRestoreError(
                "Refusing to adopt a non-empty backup "
                "directory without an ATHENA target descriptor."
            )

        target_id = new_uuid7()

        with self.database.write_transaction() as connection:
            connection.execute(
                """
                INSERT INTO backup_targets (
                    target_id,
                    root_path,
                    status,
                    created_at_us,
                    created_by_actor_id,
                    identity_initialized,
                    retention_daily,
                    retention_weekly,
                    retention_monthly,
                    retention_yearly
                ) VALUES (
                    ?, ?, 'active', ?, ?, 0,
                    7, 4, 12, 5
                )
                """,
                (
                    uuid_to_blob(
                        target_id
                    ),
                    str(target),
                    utc_now_us(),
                    uuid_to_blob(
                        actor_id
                    ),
                ),
            )

        try:
            self._write_target_descriptor(
                target,
                target_id,
            )
        except BaseException:
            self._set_target_status(
                target_id,
                "offline",
            )
            raise

        with self.database.write_transaction() as connection:
            connection.execute(
                """
                UPDATE backup_targets
                SET identity_initialized = 1
                WHERE target_id = ?
                """,
                (
                    uuid_to_blob(
                        target_id
                    ),
                ),
            )

        return self.get_target(
            target_id
        )

    def get_target(
        self,
        target_id: uuid.UUID,
    ) -> BackupTargetRecord:
        row = self.database.connection.execute(
            """
            SELECT
                target.*,
                (
                    SELECT MAX(snapshot.completed_at_us)
                    FROM backup_snapshots AS snapshot
                    WHERE snapshot.target_id = target.target_id
                      AND snapshot.state = 'complete'
                      AND snapshot.verification_status IN (
                          'verified_light',
                          'verified_deep'
                      )
                      AND snapshot.pruned_at_us IS NULL
                ) AS last_successful_backup_at_us,
                (
                    SELECT MAX(snapshot.last_verified_at_us)
                    FROM backup_snapshots AS snapshot
                    WHERE snapshot.target_id = target.target_id
                ) AS last_verified_at_us,
                CASE
                    WHEN target.deletion_ledger_watermark < (
                        SELECT COALESCE(
                            MAX(ledger_seq),
                            0
                        )
                        FROM deletion_ledger
                    )
                    THEN 1
                    ELSE 0
                END AS deletion_sync_pending
            FROM backup_targets AS target
            WHERE target.target_id = ?
            """,
            (
                uuid_to_blob(
                    target_id
                ),
            ),
        ).fetchone()

        if row is None:
            raise BackupRestoreError(
                f"Backup target {target_id} not found."
            )

        return _target_from_row(row)

    def list_targets(
        self,
    ) -> tuple[BackupTargetRecord, ...]:
        rows = self.database.connection.execute(
            """
            SELECT
                target.*,
                (
                    SELECT MAX(snapshot.completed_at_us)
                    FROM backup_snapshots AS snapshot
                    WHERE snapshot.target_id = target.target_id
                      AND snapshot.state = 'complete'
                      AND snapshot.verification_status IN (
                          'verified_light',
                          'verified_deep'
                      )
                      AND snapshot.pruned_at_us IS NULL
                ) AS last_successful_backup_at_us,
                (
                    SELECT MAX(snapshot.last_verified_at_us)
                    FROM backup_snapshots AS snapshot
                    WHERE snapshot.target_id = target.target_id
                ) AS last_verified_at_us,
                CASE
                    WHEN target.deletion_ledger_watermark < (
                        SELECT COALESCE(
                            MAX(ledger_seq),
                            0
                        )
                        FROM deletion_ledger
                    )
                    THEN 1
                    ELSE 0
                END AS deletion_sync_pending
            FROM backup_targets AS target
            ORDER BY target.created_at_us, target.target_id
            """
        ).fetchall()

        return tuple(
            _target_from_row(row)
            for row in rows
        )

    def target_status(
        self,
        target_id: uuid.UUID,
    ) -> BackupTargetRecord:
        record = self.get_target(
            target_id
        )

        if record.status == "retired":
            return record

        target = record.root_path

        if not target.is_dir():
            self._set_target_status(
                target_id,
                "offline",
            )
            return self.get_target(
                target_id
            )

        with backup_target_lock(target):
            self._assert_target_available(
                record,
                target,
            )
            self._sync_deletion_ledger_locked(
                target_id=target_id,
                target=target,
            )

        return self.get_target(
            target_id
        )

    def set_retention_policy(
        self,
        target_id: uuid.UUID,
        *,
        daily: int,
        weekly: int,
        monthly: int,
        yearly: int,
    ) -> BackupTargetRecord:
        policy = BackupRetentionPolicy(
            daily=daily,
            weekly=weekly,
            monthly=monthly,
            yearly=yearly,
        )
        self.get_target(target_id)

        with self.database.write_transaction() as connection:
            connection.execute(
                """
                UPDATE backup_targets
                SET retention_daily = ?,
                    retention_weekly = ?,
                    retention_monthly = ?,
                    retention_yearly = ?
                WHERE target_id = ?
                """,
                (
                    policy.daily,
                    policy.weekly,
                    policy.monthly,
                    policy.yearly,
                    uuid_to_blob(
                        target_id
                    ),
                ),
            )

        return self.get_target(
            target_id
        )

    def plan_retention(
        self,
        target_id: uuid.UUID,
    ) -> BackupRetentionPlan:
        self.recover_incomplete()
        record = self.get_target(
            target_id
        )
        target = record.root_path

        if not target.is_dir():
            self._set_target_status(
                target_id,
                "offline",
            )
            raise BackupRestoreError(
                "Backup target is offline."
            )

        with backup_target_lock(target):
            self._assert_target_available(
                record,
                target,
            )
            self._recover_retention_locked(
                target_id=target_id,
                target=target,
            )
            return self._plan_retention_locked(
                target_id=target_id,
                target=target,
            )

    def apply_retention(
        self,
        target_id: uuid.UUID,
    ) -> BackupRetentionResult:
        self.recover_incomplete()
        record = self.get_target(
            target_id
        )
        target = record.root_path

        if not target.is_dir():
            self._set_target_status(
                target_id,
                "offline",
            )
            raise BackupRestoreError(
                "Backup target is offline."
            )

        with backup_target_lock(target):
            self._assert_target_available(
                record,
                target,
            )
            self._recover_retention_locked(
                target_id=target_id,
                target=target,
            )

            creating = self.database.connection.execute(
                """
                SELECT COUNT(*)
                FROM backup_snapshots
                WHERE target_id = ?
                  AND state = 'creating'
                """,
                (
                    uuid_to_blob(
                        target_id
                    ),
                ),
            ).fetchone()

            if (
                creating is None
                or int(creating[0]) != 0
            ):
                raise BackupRestoreError(
                    "Retention is blocked while a backup "
                    "snapshot is creating."
                )

            plan = self._plan_retention_locked(
                target_id=target_id,
                target=target,
            )

            pruned: list[uuid.UUID] = []

            for snapshot_id in plan.prune_snapshot_ids:
                self._prune_snapshot_locked(
                    target_id=target_id,
                    snapshot_id=snapshot_id,
                    target=target,
                )
                pruned.append(
                    snapshot_id
                )

            deleted_objects = 0

            if pruned:
                deleted_objects = (
                    self._gc_backup_objects_locked(
                        target=target
                    )
                )

            return BackupRetentionResult(
                plan=plan,
                pruned_snapshot_ids=tuple(
                    pruned
                ),
                deleted_object_count=(
                    deleted_objects
                ),
            )

    def recover_retention(
        self,
        target_id: uuid.UUID,
    ) -> None:
        record = self.get_target(
            target_id
        )
        target = record.root_path

        if not target.is_dir():
            return

        with backup_target_lock(target):
            self._recover_retention_locked(
                target_id=target_id,
                target=target,
            )

    def _plan_retention_locked(
        self,
        *,
        target_id: uuid.UUID,
        target: Path,
    ) -> BackupRetentionPlan:
        target_record = self.get_target(
            target_id
        )

        rows = self.database.connection.execute(
            """
            SELECT *
            FROM backup_snapshots
            WHERE target_id = ?
              AND state = 'complete'
              AND verification_status IN (
                  'verified_light',
                  'verified_deep'
              )
              AND pruned_at_us IS NULL
            ORDER BY completed_at_us DESC, snapshot_id DESC
            """,
            (
                uuid_to_blob(
                    target_id
                ),
            ),
        ).fetchall()

        candidates: list[RetentionCandidate] = []

        for row in rows:
            snapshot = _snapshot_from_row(
                row
            )

            if (
                snapshot.completed_at_us is None
                or snapshot.manifest_sha256 is None
            ):
                raise BackupRestoreError(
                    "Completed backup metadata is incomplete."
                )

            snapshot_root = (
                target
                / snapshot.relative_path
            )

            if not self._verify_path(
                target=target,
                snapshot_root=snapshot_root,
                expected_manifest_sha256=(
                    snapshot.manifest_sha256
                ),
                expected_snapshot_id=(
                    snapshot.snapshot_id
                ),
            ):
                raise BackupRestoreError(
                    "Retention refused because a recorded "
                    "restore point failed verification."
                )

            candidates.append(
                RetentionCandidate(
                    snapshot_id=(
                        snapshot.snapshot_id
                    ),
                    completed_at_us=(
                        snapshot.completed_at_us
                    ),
                )
            )

        return calculate_retention_plan(
            target_id=target_id,
            snapshots=tuple(candidates),
            policy=target_record.policy,
        )

    def _prune_snapshot_locked(
        self,
        *,
        target_id: uuid.UUID,
        snapshot_id: uuid.UUID,
        target: Path,
    ) -> None:
        record = self.get_snapshot(
            snapshot_id
        )

        if record.target_id != target_id:
            raise BackupRestoreError(
                "Retention snapshot belongs to another target."
            )

        if (
            record.state != "complete"
            or record.pruned_at_us is not None
            or record.manifest_sha256 is None
        ):
            raise BackupRestoreError(
                "Retention candidate is no longer prunable."
            )

        snapshot_root = (
            target
            / record.relative_path
        )

        if not self._verify_path(
            target=target,
            snapshot_root=snapshot_root,
            expected_manifest_sha256=(
                record.manifest_sha256
            ),
            expected_snapshot_id=(
                snapshot_id
            ),
        ):
            raise BackupRestoreError(
                "Retention candidate failed final verification."
            )

        trash_root = (
            target
            / self.RETENTION_TRASH_NAME
        )
        durable_mkdir(
            trash_root,
            parents=True,
            exist_ok=True,
        )
        trash_path = (
            trash_root
            / str(snapshot_id)
        )

        if trash_path.exists():
            raise BackupRestoreError(
                "Retention trash already contains snapshot."
            )

        durable_replace(
            snapshot_root,
            trash_path,
        )

        pruned_at_us = utc_now_us()

        try:
            with self.database.write_transaction() as connection:
                cursor = connection.execute(
                    """
                    UPDATE backup_snapshots
                    SET pruned_at_us = ?
                    WHERE snapshot_id = ?
                      AND target_id = ?
                      AND state = 'complete'
                      AND pruned_at_us IS NULL
                    """,
                    (
                        pruned_at_us,
                        uuid_to_blob(
                            snapshot_id
                        ),
                        uuid_to_blob(
                            target_id
                        ),
                    ),
                )

                if cursor.rowcount != 1:
                    raise BackupRestoreError(
                        "Retention database state changed "
                        "during prune."
                    )

        except BaseException:
            if (
                trash_path.exists()
                and not snapshot_root.exists()
            ):
                durable_replace(
                    trash_path,
                    snapshot_root,
                )
            raise

        shutil.rmtree(
            trash_path
        )

    def _recover_retention_locked(
        self,
        *,
        target_id: uuid.UUID,
        target: Path,
    ) -> None:
        trash_root = (
            target
            / self.RETENTION_TRASH_NAME
        )

        if not trash_root.exists():
            return

        if (
            trash_root.is_symlink()
            or not trash_root.is_dir()
        ):
            raise BackupRestoreError(
                "Backup retention trash is invalid."
            )

        for item in sorted(
            trash_root.iterdir(),
            key=lambda path: path.name,
        ):
            if item.is_symlink() or not item.is_dir():
                raise BackupRestoreError(
                    "Unexpected retention-trash entry."
                )

            try:
                snapshot_id = uuid.UUID(
                    item.name
                )
            except ValueError as exc:
                raise BackupRestoreError(
                    "Retention trash contains an "
                    "invalid snapshot identifier."
                ) from exc

            row = self.database.connection.execute(
                """
                SELECT target_id, relative_path, pruned_at_us
                FROM backup_snapshots
                WHERE snapshot_id = ?
                """,
                (
                    uuid_to_blob(
                        snapshot_id
                    ),
                ),
            ).fetchone()

            if row is None:
                raise BackupRestoreError(
                    "Retention trash contains an "
                    "unknown snapshot."
                )

            if uuid_from_blob(
                bytes(row["target_id"])
            ) != target_id:
                raise BackupRestoreError(
                    "Retention trash snapshot belongs "
                    "to another target."
                )

            snapshot_root = (
                target
                / str(
                    row["relative_path"]
                )
            )

            if row["pruned_at_us"] is None:
                if snapshot_root.exists():
                    raise BackupRestoreError(
                        "Retention recovery found both "
                        "live and trashed snapshot copies."
                    )

                durable_mkdir(
                    snapshot_root.parent,
                    parents=True,
                    exist_ok=True,
                )
                durable_replace(
                    item,
                    snapshot_root,
                )
                continue

            if snapshot_root.exists():
                raise BackupRestoreError(
                    "A pruned snapshot unexpectedly "
                    "exists outside retention trash."
                )

            shutil.rmtree(
                item
            )

        try:
            trash_root.rmdir()
        except OSError:
            pass

    def _gc_backup_objects_locked(
        self,
        *,
        target: Path,
    ) -> int:
        referenced = (
            self._collect_physical_object_refs(
                target=target
            )
        )

        if not referenced:
            return 0

        objects_root = (
            target
            / "objects"
            / "sha256"
        )

        if not objects_root.exists():
            return 0

        if (
            objects_root.is_symlink()
            or not objects_root.is_dir()
        ):
            raise BackupRestoreError(
                "Backup object store is invalid."
            )

        deleted = 0

        for path in sorted(
            objects_root.rglob("*.blob"),
            key=lambda item: item.as_posix(),
        ):
            if path.is_symlink() or not path.is_file():
                raise BackupRestoreError(
                    "Backup object store contains "
                    "an unsafe object entry."
                )

            name = path.name

            if (
                len(name) != 69
                or not name.endswith(".blob")
            ):
                continue

            try:
                digest = bytes.fromhex(
                    name[:-5]
                )
            except ValueError:
                continue

            if len(digest) != 32:
                continue

            expected = (
                target
                / _object_relative_path(
                    digest
                )
            )

            if path.resolve() != expected.resolve():
                continue

            if digest in referenced:
                continue

            path.unlink()
            deleted += 1

        directories = sorted(
            (
                path
                for path in objects_root.rglob("*")
                if path.is_dir()
            ),
            key=lambda item: len(item.parts),
            reverse=True,
        )

        for directory in directories:
            try:
                directory.rmdir()
            except OSError:
                pass

        return deleted

    def _collect_physical_object_refs(
        self,
        *,
        target: Path,
    ) -> set[bytes]:
        snapshots_root = (
            target
            / "snapshots"
        )

        if not snapshots_root.exists():
            return set()

        if (
            snapshots_root.is_symlink()
            or not snapshots_root.is_dir()
        ):
            raise BackupRestoreError(
                "Backup snapshots directory is invalid."
            )

        referenced: set[bytes] = set()
        completed_count = 0

        for snapshot_root in sorted(
            snapshots_root.iterdir(),
            key=lambda item: item.name,
        ):
            if (
                snapshot_root.name.startswith(".")
                or snapshot_root.is_symlink()
                or not snapshot_root.is_dir()
            ):
                raise BackupRestoreError(
                    "Incomplete or unexpected backup "
                    "snapshot blocks object GC."
                )

            try:
                snapshot_id = uuid.UUID(
                    snapshot_root.name
                )
            except ValueError as exc:
                raise BackupRestoreError(
                    "Unexpected snapshot directory "
                    "blocks object GC."
                ) from exc

            marker = (
                snapshot_root
                / "complete.marker"
            )

            if not marker.is_file():
                raise BackupRestoreError(
                    "Snapshot without completion marker "
                    "blocks object GC."
                )

            try:
                manifest_sha256 = bytes.fromhex(
                    marker.read_text(
                        encoding="ascii"
                    ).strip()
                )
            except (
                OSError,
                ValueError,
            ) as exc:
                raise BackupRestoreError(
                    "Invalid completion marker blocks "
                    "object GC."
                ) from exc

            if len(manifest_sha256) != 32:
                raise BackupRestoreError(
                    "Invalid completion marker blocks "
                    "object GC."
                )

            if not self._verify_path(
                target=target,
                snapshot_root=snapshot_root,
                expected_manifest_sha256=(
                    manifest_sha256
                ),
                expected_snapshot_id=(
                    snapshot_id
                ),
            ):
                raise BackupRestoreError(
                    "Corrupt completed snapshot blocks "
                    "object GC."
                )

            completed_count += 1
            manifest = _read_manifest(
                snapshot_root
                / "manifest.json"
            )
            objects = manifest.get(
                "objects"
            )

            if not isinstance(objects, list):
                raise BackupRestoreError(
                    "Invalid backup manifest blocks "
                    "object GC."
                )

            for item in objects:
                if not isinstance(item, dict):
                    raise BackupRestoreError(
                        "Invalid backup object metadata "
                        "blocks object GC."
                    )

                try:
                    digest = bytes.fromhex(
                        _required_str(
                            item,
                            "sha256",
                        )
                    )
                    relative = _safe_relative(
                        _required_str(
                            item,
                            "object_path",
                        )
                    )
                except (
                    BackupRestoreError,
                    ValueError,
                ) as exc:
                    raise BackupRestoreError(
                        "Invalid backup object metadata "
                        "blocks object GC."
                    ) from exc

                if (
                    len(digest) != 32
                    or relative
                    != _object_relative_path(
                        digest
                    )
                ):
                    raise BackupRestoreError(
                        "Non-canonical backup object "
                        "metadata blocks object GC."
                    )

                referenced.add(
                    digest
                )

        if completed_count == 0:
            return set()

        return referenced

    def _resolve_target_for_create(
        self,
        *,
        target_root: Path | None,
        target_id: uuid.UUID | None,
        actor_id: uuid.UUID,
    ) -> tuple[Path, uuid.UUID]:
        del actor_id

        if (
            target_root is not None
            and target_id is not None
        ):
            raise BackupRestoreError(
                "Specify either target_root or "
                "target_id, not both."
            )

        if target_id is not None:
            record = self.get_target(
                target_id
            )

            if record.status == "retired":
                raise BackupRestoreError(
                    "Backup target is retired."
                )

            target = record.root_path

            if not target.is_dir():
                self._set_target_status(
                    target_id,
                    "offline",
                )
                raise BackupRestoreError(
                    "Backup target is offline."
                )

            with backup_target_lock(target):
                self._assert_target_available(
                    record,
                    target,
                )

            return (
                target,
                target_id,
            )

        raw = (
            target_root
            if target_root is not None
            else self.paths.backup_root
        )

        if raw is None:
            raise BackupRestoreError(
                "No backup target configured; "
                "provide an explicit target."
            )

        target = self._normalize_target_path(
            raw
        )

        row = self.database.connection.execute(
            """
            SELECT target_id
            FROM backup_targets
            WHERE root_path = ?
            """,
            (str(target),),
        ).fetchone()

        if row is not None:
            existing_id = uuid_from_blob(
                bytes(row["target_id"])
            )
            record = self.get_target(
                existing_id
            )

            if record.status == "retired":
                raise BackupRestoreError(
                    "Backup target is retired."
                )

            if not target.is_dir():
                self._set_target_status(
                    existing_id,
                    "offline",
                )
                raise BackupRestoreError(
                    "Known backup target is offline; "
                    "refusing to recreate its root."
                )

            with backup_target_lock(target):
                self._assert_target_available(
                    record,
                    target,
                )

            return (
                target,
                existing_id,
            )

        registered = self.register_target(
            target
        )

        return (
            registered.root_path,
            registered.target_id,
        )

    def _assert_target_available(
        self,
        record: BackupTargetRecord,
        target: Path,
    ) -> None:
        if not target.is_dir():
            self._set_target_status(
                record.target_id,
                "offline",
            )
            raise BackupRestoreError(
                "Backup target is offline."
            )

        descriptor_id = (
            self._read_target_descriptor(
                target
            )
        )

        if descriptor_id is None:
            if record.identity_initialized:
                self._set_target_status(
                    record.target_id,
                    "offline",
                )
                raise BackupRestoreError(
                    "Known backup target lost its "
                    "identity descriptor."
                )

            complete_rows = (
                self.database.connection.execute(
                    """
                    SELECT relative_path
                    FROM backup_snapshots
                    WHERE target_id = ?
                      AND state = 'complete'
                      AND pruned_at_us IS NULL
                    ORDER BY created_at_us
                    """,
                    (
                        uuid_to_blob(
                            record.target_id
                        ),
                    ),
                ).fetchall()
            )

            for row in complete_rows:
                snapshot_root = (
                    target
                    / str(
                        row["relative_path"]
                    )
                )

                if not (
                    snapshot_root.is_dir()
                    and (
                        snapshot_root
                        / "complete.marker"
                    ).is_file()
                ):
                    self._set_target_status(
                        record.target_id,
                        "offline",
                    )
                    raise BackupRestoreError(
                        "Legacy backup target contents "
                        "do not match registered history."
                    )

            self._write_target_descriptor(
                target,
                record.target_id,
            )
            descriptor_id = (
                record.target_id
            )

        if descriptor_id != record.target_id:
            self._set_target_status(
                record.target_id,
                "offline",
            )
            raise BackupRestoreError(
                "Backup target identity mismatch."
            )

        with self.database.write_transaction() as connection:
            connection.execute(
                """
                UPDATE backup_targets
                SET status = 'active',
                    identity_initialized = 1
                WHERE target_id = ?
                """,
                (
                    uuid_to_blob(
                        record.target_id
                    ),
                ),
            )

    def _read_target_descriptor(
        self,
        target: Path,
    ) -> uuid.UUID | None:
        path = (
            target
            / self.TARGET_DESCRIPTOR_NAME
        )

        if not path.exists():
            return None

        if path.is_symlink() or not path.is_file():
            raise BackupRestoreError(
                "Backup target descriptor is unsafe."
            )

        try:
            value = json.loads(
                path.read_text(
                    encoding="utf-8"
                )
            )
        except (
            OSError,
            json.JSONDecodeError,
        ) as exc:
            raise BackupRestoreError(
                "Backup target descriptor is invalid."
            ) from exc

        if (
            not isinstance(value, dict)
            or value.get("format_version")
            != self.TARGET_FORMAT_VERSION
        ):
            raise BackupRestoreError(
                "Backup target descriptor format "
                "is unsupported."
            )

        raw_target_id = value.get(
            "target_id"
        )

        if not isinstance(
            raw_target_id,
            str,
        ):
            raise BackupRestoreError(
                "Backup target descriptor has no "
                "valid target_id."
            )

        try:
            return uuid.UUID(
                raw_target_id
            )
        except ValueError as exc:
            raise BackupRestoreError(
                "Backup target descriptor target_id "
                "is invalid."
            ) from exc

    def _write_target_descriptor(
        self,
        target: Path,
        target_id: uuid.UUID,
    ) -> None:
        existing = self._read_target_descriptor(
            target
        )

        if existing is not None:
            if existing != target_id:
                raise BackupRestoreError(
                    "Refusing to overwrite a different "
                    "backup target identity."
                )
            return

        encoded = (
            _canonical_json(
                {
                    "format_version": (
                        self.TARGET_FORMAT_VERSION
                    ),
                    "target_id": str(
                        target_id
                    ),
                }
            )
            + "\n"
        ).encode("utf-8")

        _write_fsynced(
            target
            / self.TARGET_DESCRIPTOR_NAME,
            encoded,
        )

    def _set_target_status(
        self,
        target_id: uuid.UUID,
        status: str,
    ) -> None:
        if status not in {
            "active",
            "offline",
            "retired",
        }:
            raise ValueError(
                "Invalid backup target status."
            )

        with self.database.write_transaction() as connection:
            connection.execute(
                """
                UPDATE backup_targets
                SET status = ?
                WHERE target_id = ?
                """,
                (
                    status,
                    uuid_to_blob(
                        target_id
                    ),
                ),
            )

    def _normalize_target_path(
        self,
        raw: Path,
    ) -> Path:
        target = raw.expanduser()

        if not target.is_absolute():
            raise BackupRestoreError(
                "Backup target must be an absolute path."
            )

        if target.exists() and target.is_symlink():
            raise BackupRestoreError(
                "Backup target root must not be a symlink."
            )

        target = target.resolve()

        live = self.paths.local_root.resolve()

        if (
            target == live
            or live in target.parents
            or target in live.parents
        ):
            raise BackupRestoreError(
                "Backup target must be separate "
                "from live local_root."
            )

        archive = self.paths.archive_root

        if archive is not None:
            archive_resolved = (
                archive.resolve()
            )

            if (
                target == archive_resolved
                or archive_resolved
                in target.parents
                or target
                in archive_resolved.parents
            ):
                raise BackupRestoreError(
                    "Backup target must not overlap "
                    "the live Raw Archive root."
                )

        return target

    def _target_root(self, target_root: Path | None) -> Path:
        raw = (
            target_root
            if target_root is not None
            else self.paths.backup_root
        )
        if raw is None:
            raise BackupRestoreError(
                "No backup target configured; "
                "provide an explicit target."
            )
        target = self._normalize_target_path(raw)
        if not target.is_dir():
            raise BackupRestoreError(
                "Backup target is offline."
            )
        return target

    def _ensure_target(
        self,
        target: Path,
        *,
        actor_id: uuid.UUID,
    ) -> uuid.UUID:
        del actor_id
        return self.register_target(
            target
        ).target_id


    def _target_for_record(self, record: BackupSnapshotRecord) -> Path:
        row = self.database.connection.execute(
            "SELECT root_path FROM backup_targets WHERE target_id = ?",
            (uuid_to_blob(record.target_id),),
        ).fetchone()
        if row is None:
            raise BackupRestoreError("Backup target metadata is missing.")
        return Path(str(row["root_path"]))

    def _verify_light_path(
        self,
        *,
        target: Path,
        snapshot_root: Path,
        expected_manifest_sha256: bytes,
        expected_snapshot_id: uuid.UUID | None = None,
    ) -> bool:
        marker = (
            snapshot_root
            / "complete.marker"
        )

        if not marker.is_file():
            return False

        try:
            marker_value = (
                marker.read_text(
                    encoding="ascii"
                ).strip()
            )
        except OSError:
            return False

        if (
            marker_value
            != expected_manifest_sha256.hex()
        ):
            return False

        manifest_path = (
            snapshot_root
            / "manifest.json"
        )

        database_path = (
            snapshot_root
            / "athena.db"
        )

        if (
            not manifest_path.is_file()
            or not database_path.is_file()
        ):
            return False

        try:
            manifest_bytes = (
                manifest_path.read_bytes()
            )
        except OSError:
            return False

        if (
            hashlib.sha256(
                manifest_bytes
            ).digest()
            != expected_manifest_sha256
        ):
            return False

        try:
            manifest = _read_manifest(
                manifest_path
            )
        except BackupRestoreError:
            return False

        if (
            expected_snapshot_id is not None
            and manifest.get(
                "snapshot_id"
            )
            != str(
                expected_snapshot_id
            )
        ):
            return False

        database = manifest.get(
            "database"
        )

        if not isinstance(
            database,
            dict,
        ):
            return False

        if (
            database.get("path")
            != "athena.db"
        ):
            return False

        try:
            expected_db_sha256 = (
                bytes.fromhex(
                    _required_str(
                        database,
                        "sha256",
                    )
                )
            )
        except (
            BackupRestoreError,
            ValueError,
        ):
            return False

        db_sha256, _ = _hash_file(
            database_path
        )

        if (
            db_sha256
            != expected_db_sha256
        ):
            return False

        if not _manifest_matches_database(
            manifest,
            database_path,
        ):
            return False

        objects = manifest.get(
            "objects"
        )

        if not isinstance(
            objects,
            list,
        ):
            return False

        for item in objects:
            if not isinstance(
                item,
                dict,
            ):
                return False

            try:
                expected_sha256 = (
                    bytes.fromhex(
                        _required_str(
                            item,
                            "sha256",
                        )
                    )
                )

                expected_length = (
                    _required_int(
                        item,
                        "byte_length",
                    )
                )

                relative = (
                    _safe_relative(
                        _required_str(
                            item,
                            "object_path",
                        )
                    )
                )

            except (
                BackupRestoreError,
                ValueError,
            ):
                return False

            if (
                relative
                != _object_relative_path(
                    expected_sha256
                )
            ):
                return False

            try:
                object_path = (
                    _safe_existing_file(
                        target,
                        relative,
                    )
                )

                actual_length = (
                    object_path.stat().st_size
                )

            except (
                BackupRestoreError,
                OSError,
            ):
                return False

            if (
                actual_length
                != expected_length
            ):
                return False

        check = sqlite3.connect(
            database_path
        )

        try:
            check.execute(
                "PRAGMA foreign_keys = ON"
            )

            quick = str(
                check.execute(
                    "PRAGMA quick_check"
                ).fetchone()[0]
            )

            if quick.lower() != "ok":
                return False

            integrity = str(
                check.execute(
                    "PRAGMA integrity_check"
                ).fetchone()[0]
            )

            if (
                integrity.lower()
                != "ok"
            ):
                return False

            if check.execute(
                "PRAGMA foreign_key_check"
            ).fetchall():
                return False

            snapshot_schema = int(
                check.execute(
                    "PRAGMA user_version"
                ).fetchone()[0]
            )

            manifest_schema = (
                manifest.get(
                    "schema_version"
                )
            )

            if (
                isinstance(
                    manifest_schema,
                    bool,
                )
                or not isinstance(
                    manifest_schema,
                    int,
                )
                or snapshot_schema
                != manifest_schema
            ):
                return False

        finally:
            check.close()

        return True

    def _verify_path(
        self,
        *,
        target: Path,
        snapshot_root: Path,
        expected_manifest_sha256: bytes,
        expected_snapshot_id: uuid.UUID | None = None,
    ) -> bool:
        marker = snapshot_root / "complete.marker"
        if not marker.is_file():
            return False
        try:
            marker_value = marker.read_text(encoding="ascii").strip()
        except OSError:
            return False
        if marker_value != expected_manifest_sha256.hex():
            return False
        return self._verify_payload_path(
            target=target,
            snapshot_root=snapshot_root,
            expected_manifest_sha256=expected_manifest_sha256,
            expected_snapshot_id=expected_snapshot_id,
        )

    def _verify_payload_path(
        self,
        *,
        target: Path,
        snapshot_root: Path,
        expected_manifest_sha256: bytes,
        expected_snapshot_id: uuid.UUID | None = None,
    ) -> bool:
        manifest_path = snapshot_root / "manifest.json"
        database_path = snapshot_root / "athena.db"
        if not manifest_path.is_file() or not database_path.is_file():
            return False
        try:
            manifest_bytes = manifest_path.read_bytes()
        except OSError:
            return False
        if hashlib.sha256(manifest_bytes).digest() != expected_manifest_sha256:
            return False
        manifest = _read_manifest(manifest_path)
        if (
            expected_snapshot_id is not None
            and manifest.get("snapshot_id") != str(expected_snapshot_id)
        ):
            return False
        database = manifest.get("database")
        if not isinstance(database, dict):
            return False
        if database.get("path") != "athena.db":
            return False
        db_digest, _ = _hash_file(database_path)
        if db_digest.hex() != database.get("sha256"):
            return False
        if not _manifest_matches_database(manifest, database_path):
            return False
        objects = manifest.get("objects")
        if not isinstance(objects, list):
            return False
        for item in objects:
            if not isinstance(item, dict):
                return False
            try:
                expected = bytes.fromhex(_required_str(item, "sha256"))
                length = _required_int(item, "byte_length")
                relative = _safe_relative(_required_str(item, "object_path"))
            except (BackupRestoreError, ValueError):
                return False
            if relative != _object_relative_path(expected):
                return False
            try:
                object_path = _safe_existing_file(target, relative)
            except BackupRestoreError:
                return False
            digest, actual_length = _hash_file(object_path)
            if digest != expected or actual_length != length:
                return False
        check = sqlite3.connect(database_path)
        try:
            check.execute("PRAGMA foreign_keys = ON")
            integrity = str(check.execute("PRAGMA integrity_check").fetchone()[0])
            if integrity.lower() != "ok":
                return False
            if check.execute("PRAGMA foreign_key_check").fetchall():
                return False
            database_schema = int(
                check.execute(
                    "PRAGMA user_version"
                ).fetchone()[0]
            )
            manifest_schema = manifest.get(
                "schema_version"
            )
            if (
                not isinstance(
                    manifest_schema,
                    int,
                )
                or isinstance(
                    manifest_schema,
                    bool,
                )
                or database_schema
                != manifest_schema
            ):
                return False
        finally:
            check.close()
        return True



def _manifest_matches_database(manifest: dict[str, Any], database_path: Path) -> bool:
    manifest_schema_version = manifest.get(
        "schema_version"
    )
    if (
        not isinstance(
            manifest_schema_version,
            int,
        )
        or isinstance(
            manifest_schema_version,
            bool,
        )
        or manifest_schema_version < 1
        or manifest_schema_version > SCHEMA_VERSION
    ):
        return False
    snapshot_commit_seq = manifest.get("snapshot_commit_seq")
    if (
        not isinstance(snapshot_commit_seq, int)
        or isinstance(snapshot_commit_seq, bool)
        or snapshot_commit_seq < 0
    ):
        return False

    deletion_ledger_watermark: int | None = None

    if (
        manifest_schema_version
        >= DELETION_LEDGER_SCHEMA_VERSION
    ):
        raw_watermark = manifest.get(
            "deletion_ledger_watermark"
        )

        if (
            not isinstance(
                raw_watermark,
                int,
            )
            or isinstance(
                raw_watermark,
                bool,
            )
            or raw_watermark < 0
        ):
            return False

        deletion_ledger_watermark = (
            raw_watermark
        )

    objects = manifest.get("objects")
    if not isinstance(objects, list):
        return False
    expected: list[tuple[str, str, int, str, str]] = []
    for item in objects:
        if not isinstance(item, dict):
            return False
        try:
            blob_id = _required_str(item, "blob_id")
            digest = _required_str(item, "sha256")
            length = _required_int(item, "byte_length")
            locator = _required_str(item, "storage_locator")
            encryption = _required_str(item, "encryption_state")
            uuid.UUID(blob_id)
            if len(bytes.fromhex(digest)) != 32:
                return False
        except (BackupRestoreError, ValueError):
            return False
        expected.append((blob_id, digest, length, locator, encryption))
    expected.sort()

    check = sqlite3.connect(database_path)
    check.row_factory = sqlite3.Row
    try:
        if int(
            check.execute(
                "PRAGMA user_version"
            ).fetchone()[0]
        ) != manifest_schema_version:
            return False

        row = check.execute(
            "SELECT COALESCE(MAX(commit_seq), 0) AS commit_seq FROM commit_records"
        ).fetchone()
        if row is None or int(row["commit_seq"]) != snapshot_commit_seq:
            return False
        rows = check.execute(
            """
            SELECT
                b.blob_id,
                b.integrity_sha256,
                b.byte_length,
                b.storage_locator,
                b.encryption_state
            FROM blob_records AS b
            WHERE EXISTS (
                SELECT 1
                FROM sources AS source
                JOIN entity_registry AS source_entity
                  ON source_entity.entity_id = source.source_id
                WHERE source.blob_id = b.blob_id
                  AND source_entity.lifecycle_state != 'deleted'
            )
            ORDER BY b.blob_id
            """
        ).fetchall()
        actual = sorted(
            (
                str(uuid_from_blob(bytes(row["blob_id"]))),
                bytes(row["integrity_sha256"]).hex(),
                int(row["byte_length"]),
                str(row["storage_locator"]),
                str(row["encryption_state"]),
            )
            for row in rows
        )

        if actual != expected:
            return False

        if (
            manifest_schema_version
            >= DELETION_LEDGER_SCHEMA_VERSION
        ):
            row = check.execute(
                """
                SELECT COALESCE(
                    MAX(ledger_seq),
                    0
                )
                FROM deletion_ledger
                """
            ).fetchone()

            actual_watermark = (
                int(row[0])
                if row is not None
                else 0
            )

            if (
                actual_watermark
                != deletion_ledger_watermark
            ):
                return False

        return True
    finally:
        check.close()


def _safe_existing_file(root: Path, relative: Path) -> Path:
    root_resolved = root.resolve()
    candidate = root_resolved / relative
    if candidate.is_symlink():
        raise BackupRestoreError(f"Backup object must not be a symlink: {candidate}.")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise BackupRestoreError(f"Backup object is unavailable: {candidate}.") from exc
    if root_resolved != resolved and root_resolved not in resolved.parents:
        raise BackupRestoreError("Backup object resolved outside the backup target.")
    if not resolved.is_file():
        raise BackupRestoreError(f"Backup object is not a regular file: {resolved}.")
    return resolved


def _snapshot_from_row(row: sqlite3.Row) -> BackupSnapshotRecord:
    return BackupSnapshotRecord(
        snapshot_id=uuid_from_blob(bytes(row["snapshot_id"])),
        target_id=uuid_from_blob(bytes(row["target_id"])),
        state=str(row["state"]),
        verification_status=str(row["verification_status"]),
        relative_path=str(row["relative_path"]),
        snapshot_commit_seq=(
            int(row["snapshot_commit_seq"])
            if row["snapshot_commit_seq"] is not None
            else None
        ),
        schema_version=(
            int(row["schema_version"]) if row["schema_version"] is not None else None
        ),
        db_sha256=bytes(row["db_sha256"]) if row["db_sha256"] is not None else None,
        manifest_sha256=(
            bytes(row["manifest_sha256"])
            if row["manifest_sha256"] is not None
            else None
        ),
        object_count=int(row["object_count"]),
        created_at_us=int(row["created_at_us"]),
        completed_at_us=(
            int(row["completed_at_us"])
            if row["completed_at_us"] is not None
            else None
        ),
        last_verified_at_us=(
            int(row["last_verified_at_us"])
            if row["last_verified_at_us"] is not None
            else None
        ),
        pruned_at_us=(
            int(row["pruned_at_us"])
            if row["pruned_at_us"] is not None
            else None
        ),
        deletion_ledger_watermark=int(
            row[
                "deletion_ledger_watermark"
            ]
        ),
    )



def _target_from_row(
    row: sqlite3.Row,
) -> BackupTargetRecord:
    return BackupTargetRecord(
        target_id=uuid_from_blob(
            bytes(row["target_id"])
        ),
        root_path=Path(
            str(row["root_path"])
        ),
        status=str(
            row["status"]
        ),
        policy=BackupRetentionPolicy(
            daily=int(
                row["retention_daily"]
            ),
            weekly=int(
                row["retention_weekly"]
            ),
            monthly=int(
                row["retention_monthly"]
            ),
            yearly=int(
                row["retention_yearly"]
            ),
        ),
        identity_initialized=bool(
            int(
                row["identity_initialized"]
            )
        ),
        created_at_us=int(
            row["created_at_us"]
        ),
        last_successful_backup_at_us=(
            int(
                row[
                    "last_successful_backup_at_us"
                ]
            )
            if row[
                "last_successful_backup_at_us"
            ] is not None
            else None
        ),
        last_verified_at_us=(
            int(
                row["last_verified_at_us"]
            )
            if row[
                "last_verified_at_us"
            ] is not None
            else None
        ),
        deletion_ledger_watermark=int(
            row[
                "deletion_ledger_watermark"
            ]
        ),
        deletion_sync_pending=bool(
            int(
                row[
                    "deletion_sync_pending"
                ]
            )
        ),
    )



def _object_relative_path(digest: bytes) -> Path:
    value = digest.hex()
    return Path("objects") / "sha256" / value[:2] / value[2:4] / f"{value}.blob"


def _hash_file(path: Path) -> tuple[bytes, int]:
    digest = hashlib.sha256()
    length = 0
    try:
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                length += len(chunk)
    except OSError as exc:
        raise BackupRestoreError(f"Cannot read backup object {path}.") from exc
    return digest.digest(), length


def _copy_verified(
    source: Path,
    destination: Path,
    *,
    expected_sha256: bytes,
    expected_length: int,
) -> None:
    if destination.exists():
        digest, length = _hash_file(destination)
        if digest != expected_sha256 or length != expected_length:
            raise BackupRestoreError(f"Existing backup object is corrupt: {destination}.")
        return
    durable_mkdir(
        destination.parent,
        parents=True,
        exist_ok=True,
    )
    temporary = destination.with_name(f".{destination.name}.{new_uuid7()}.partial")
    try:
        with source.open("rb") as src, temporary.open("xb") as dst:
            while True:
                chunk = src.read(1024 * 1024)
                if not chunk:
                    break
                dst.write(chunk)
            dst.flush()
            os.fsync(dst.fileno())
        digest, length = _hash_file(temporary)
        if digest != expected_sha256 or length != expected_length:
            raise BackupRestoreError(f"Copied backup object failed hash verification: {source}.")
        durable_replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _fsync_existing(path: Path) -> None:
    try:
        with path.open("rb+") as handle:
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise BackupRestoreError(f"Cannot fsync backup file {path}.") from exc


def _write_fsynced(path: Path, data: bytes) -> None:
    """Write and durably publish one new backup metadata file."""

    if path.exists() or path.is_symlink():
        raise FileExistsError(
            f"Durable backup metadata destination already exists: {path}."
        )

    temporary = path.with_name(
        f".{path.name}.{new_uuid7()}.partial"
    )

    try:
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())

        # Publish only after the bytes themselves are stable. This also makes
        # the new directory entry durable rather than relying on file fsync
        # alone.
        durable_replace(
            temporary,
            path,
        )
    finally:
        temporary.unlink(
            missing_ok=True
        )




def _read_manifest(path: Path) -> dict[str, Any]:
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BackupRestoreError("Backup manifest is unreadable or invalid.") from exc
    if not isinstance(parsed, dict) or parsed.get("format_version") != 1:
        raise BackupRestoreError("Backup manifest format is unsupported.")
    return parsed


def _safe_relative(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or path.drive or path.root or ".." in path.parts:
        raise BackupRestoreError(f"Unsafe relative backup path: {value!r}.")
    return path


def _required_str(value: dict[str, Any], key: str) -> str:
    raw = value.get(key)
    if not isinstance(raw, str) or not raw:
        raise BackupRestoreError(f"Backup manifest field {key!r} is invalid.")
    return raw


def _required_int(value: dict[str, Any], key: str) -> int:
    raw = value.get(key)
    if not isinstance(raw, int) or isinstance(raw, bool) or raw < 0:
        raise BackupRestoreError(f"Backup manifest field {key!r} is invalid.")
    return raw
