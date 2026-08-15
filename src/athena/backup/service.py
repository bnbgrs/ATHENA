"""Verified SQLite/blob backups and restore into a new isolated runtime root."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from athena.chat.service import ChatService
from athena.common.ids import new_uuid7, uuid_from_blob, uuid_to_blob
from athena.common.time import utc_now_us
from athena.source.blob_store import BlobStore
from athena.source.models import BlobStorageArea
from athena.storage.database import SQLiteDatabase
from athena.storage.paths import RuntimePaths
from athena.storage.schema import SCHEMA_VERSION


class BackupRestoreError(RuntimeError):
    """Raised when backup/restore cannot complete with verified integrity."""


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


class BackupService:
    """Create complete-marker backups and restore them only into a new root."""

    FORMAT_VERSION = 1

    def __init__(
        self,
        *,
        database: SQLiteDatabase,
        blob_store: BlobStore,
        paths: RuntimePaths,
        chat: ChatService,
    ) -> None:
        self.database = database
        self.blob_store = blob_store
        self.paths = paths
        self.chat = chat

    def create_snapshot(self, *, target_root: Path | None = None) -> BackupSnapshotRecord:
        # Resolve leftovers from a previous hard process/power interruption
        # before publishing another restore point.
        self.recover_incomplete()
        actor_id = self.chat.ensure_local_user()
        target = self._target_root(target_root)
        target_id = self._ensure_target(target, actor_id=actor_id)
        snapshot_id = new_uuid7()
        created_at_us = utc_now_us()
        relative_path = f"snapshots/{snapshot_id}"
        snapshot_root = target / relative_path
        staging_root = target / "snapshots" / f".{snapshot_id}.partial"
        staging_root.mkdir(parents=True, exist_ok=False)
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
                blobs = tuple(
                    snap.execute(
                        """
                        SELECT blob_id, byte_length, storage_area, storage_locator,
                               integrity_sha256, encryption_state
                        FROM blob_records
                        ORDER BY integrity_sha256, blob_id
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
                    SET snapshot_commit_seq = ?, schema_version = ?
                    WHERE snapshot_id = ?
                    """,
                    (
                        snapshot_commit_seq,
                        schema_version,
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
            os.replace(staging_root, snapshot_root)
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
                        failure_detail = NULL
                    WHERE snapshot_id = ?
                    """,
                    (
                        db_sha256,
                        manifest_sha256,
                        len(object_entries),
                        completed_at_us,
                        uuid_to_blob(snapshot_id),
                    ),
                )
                connection.execute(
                    "DELETE FROM backup_snapshot_pins WHERE snapshot_id = ?",
                    (uuid_to_blob(snapshot_id),),
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
                            f"{type(exc).__name__}: {exc}"[:2000],
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
        """Resolve creating backups left behind by hard process/power interruption."""
        rows = self.database.connection.execute(
            """
            SELECT snapshot.snapshot_id, snapshot.relative_path, target.root_path
            FROM backup_snapshots AS snapshot
            JOIN backup_targets AS target ON target.target_id = snapshot.target_id
            WHERE snapshot.state = 'creating'
            ORDER BY snapshot.created_at_us, snapshot.snapshot_id
            """
        ).fetchall()
        recovered: list[uuid.UUID] = []
        for row in rows:
            snapshot_id = uuid_from_blob(bytes(row["snapshot_id"]))
            target = Path(str(row["root_path"]))
            # An offline backup target is not evidence of corruption. Keep the
            # creating row and pins so a later recovery can decide safely.
            if not target.is_absolute() or not target.is_dir():
                continue
            snapshot_root = target / str(row["relative_path"])
            staging_root = target / "snapshots" / f".{snapshot_id}.partial"
            marker = snapshot_root / "complete.marker"
            valid = False
            manifest_sha256: bytes | None = None
            db_sha256: bytes | None = None
            snapshot_commit_seq: int | None = None
            schema_version: int | None = None
            objects: list[Any] | None = None
            if marker.is_file():
                try:
                    manifest_sha256 = bytes.fromhex(
                        marker.read_text(encoding="ascii").strip()
                    )
                except (OSError, ValueError):
                    manifest_sha256 = None
                if manifest_sha256 is not None and len(manifest_sha256) == 32:
                    valid = self._verify_path(
                        target=target,
                        snapshot_root=snapshot_root,
                        expected_manifest_sha256=manifest_sha256,
                        expected_snapshot_id=snapshot_id,
                    )
            if valid and manifest_sha256 is not None:
                manifest = _read_manifest(snapshot_root / "manifest.json")
                database_meta = manifest.get("database")
                raw_objects = manifest.get("objects")
                if not isinstance(database_meta, dict) or not isinstance(raw_objects, list):
                    valid = False
                else:
                    objects = raw_objects
                    try:
                        db_sha256 = bytes.fromhex(
                            _required_str(database_meta, "sha256")
                        )
                        snapshot_commit_seq = _required_int(
                            manifest, "snapshot_commit_seq"
                        )
                        schema_version = _required_int(manifest, "schema_version")
                    except (BackupRestoreError, ValueError):
                        valid = False
            if (
                valid
                and manifest_sha256 is not None
                and db_sha256 is not None
                and snapshot_commit_seq is not None
                and schema_version is not None
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
                            db_sha256 = ?,
                            manifest_sha256 = ?,
                            object_count = ?,
                            completed_at_us = ?,
                            failure_detail = NULL
                        WHERE snapshot_id = ? AND state = 'creating'
                        """,
                        (
                            snapshot_commit_seq,
                            schema_version,
                            db_sha256,
                            manifest_sha256,
                            len(objects),
                            completed_at_us,
                            uuid_to_blob(snapshot_id),
                        ),
                    )
                    if cursor.rowcount == 1:
                        connection.execute(
                            "DELETE FROM backup_snapshot_pins WHERE snapshot_id = ?",
                            (uuid_to_blob(snapshot_id),),
                        )
                        recovered.append(snapshot_id)
                shutil.rmtree(staging_root, ignore_errors=True)
                continue

            # No valid complete marker: this is not a restore point.
            shutil.rmtree(staging_root, ignore_errors=True)
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
                        failure_detail = 'startup recovery: incomplete or invalid backup'
                    WHERE snapshot_id = ? AND state = 'creating'
                    """,
                    (uuid_to_blob(snapshot_id),),
                )
        return tuple(recovered)


    def verify(self, snapshot_id: uuid.UUID) -> BackupSnapshotRecord:
        record = self.get_snapshot(snapshot_id)
        if record.state != "complete" or record.verification_status not in {
            "verified_light",
            "verified_deep",
        }:
            raise BackupRestoreError("Backup snapshot is not a completed restore point.")
        target = self._target_for_record(record)
        snapshot_root = target / record.relative_path
        if record.manifest_sha256 is None:
            raise BackupRestoreError("Backup snapshot has no recorded manifest hash.")
        if not self._verify_path(
            target=target,
            snapshot_root=snapshot_root,
            expected_manifest_sha256=record.manifest_sha256,
            expected_snapshot_id=record.snapshot_id,
        ):
            raise BackupRestoreError("Backup verification failed.")
        return record

    def restore_to(
        self,
        snapshot_id: uuid.UUID,
        *,
        destination_root: Path,
    ) -> Path:
        record = self.verify(snapshot_id)
        target = self._target_for_record(record)
        snapshot_root = target / record.relative_path
        return self._restore_verified_path(
            target=target,
            snapshot_root=snapshot_root,
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
        if not self._verify_path(
            target=target,
            snapshot_root=snapshot,
            expected_manifest_sha256=expected_manifest_sha256,
            expected_snapshot_id=snapshot_id,
        ):
            raise BackupRestoreError("Backup path verification failed.")
        return self._restore_verified_path(
            target=target,
            snapshot_root=snapshot,
            destination_root=destination_root,
        )

    def _restore_verified_path(
        self,
        *,
        target: Path,
        snapshot_root: Path,
        destination_root: Path,
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
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = destination.with_name(
            f".{destination.name}.{new_uuid7()}.restore-partial"
        )
        if staging.exists():
            raise BackupRestoreError("Restore staging destination already exists.")
        staging.mkdir(parents=False, exist_ok=False)

        try:
            manifest = _read_manifest(snapshot_root / "manifest.json")
            state_root = staging / "state"
            spool_root = state_root / "spool"
            state_root.mkdir(parents=True, exist_ok=True)
            spool_root.mkdir(parents=True, exist_ok=True)
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
            try:
                restored.execute("PRAGMA foreign_keys = ON")
                restored.execute("BEGIN IMMEDIATE")
                restored.execute("UPDATE blob_records SET storage_area = 'spool'")
                restored.execute("UPDATE backup_targets SET status = 'offline'")
                restored.execute("DELETE FROM backup_snapshot_pins")
                restored.execute("COMMIT")
                integrity = str(restored.execute("PRAGMA integrity_check").fetchone()[0])
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

            (staging / "derived").mkdir(parents=True, exist_ok=True)
            _write_fsynced(
                state_root / "restore.complete",
                b"ATHENA_RESTORE_COMPLETE_V1\n",
            )
            os.replace(staging, destination)
            return destination
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise


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

    def _target_root(self, target_root: Path | None) -> Path:
        raw = target_root if target_root is not None else self.paths.backup_root
        if raw is None:
            raise BackupRestoreError(
                "No backup target configured; provide an explicit absolute target."
            )
        target = raw.expanduser()
        if not target.is_absolute():
            raise BackupRestoreError("Backup target must be an absolute path.")
        target = target.resolve()
        live = self.paths.local_root.resolve()
        if target == live or live in target.parents or target in live.parents:
            raise BackupRestoreError(
                "Backup target must be physically/logically separate from live local_root."
            )
        archive = self.paths.archive_root
        if archive is not None:
            archive_resolved = archive.resolve()
            if (
                target == archive_resolved
                or archive_resolved in target.parents
                or target in archive_resolved.parents
            ):
                raise BackupRestoreError(
                    "Backup target must not overlap the live Raw Archive root."
                )
        target.mkdir(parents=True, exist_ok=True)
        return target

    def _ensure_target(self, target: Path, *, actor_id: uuid.UUID) -> uuid.UUID:
        row = self.database.connection.execute(
            "SELECT target_id FROM backup_targets WHERE root_path = ?",
            (str(target),),
        ).fetchone()
        if row is not None:
            return uuid_from_blob(bytes(row["target_id"]))
        target_id = new_uuid7()
        with self.database.write_transaction() as connection:
            connection.execute(
                """
                INSERT INTO backup_targets (
                    target_id, root_path, status, created_at_us, created_by_actor_id
                ) VALUES (?, ?, 'active', ?, ?)
                """,
                (
                    uuid_to_blob(target_id),
                    str(target),
                    utc_now_us(),
                    uuid_to_blob(actor_id),
                ),
            )
        return target_id

    def _target_for_record(self, record: BackupSnapshotRecord) -> Path:
        row = self.database.connection.execute(
            "SELECT root_path FROM backup_targets WHERE target_id = ?",
            (uuid_to_blob(record.target_id),),
        ).fetchone()
        if row is None:
            raise BackupRestoreError("Backup target metadata is missing.")
        return Path(str(row["root_path"]))

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
            if int(check.execute("PRAGMA user_version").fetchone()[0]) != SCHEMA_VERSION:
                return False
        finally:
            check.close()
        return True



def _manifest_matches_database(manifest: dict[str, Any], database_path: Path) -> bool:
    if manifest.get("schema_version") != SCHEMA_VERSION:
        return False
    snapshot_commit_seq = manifest.get("snapshot_commit_seq")
    if (
        not isinstance(snapshot_commit_seq, int)
        or isinstance(snapshot_commit_seq, bool)
        or snapshot_commit_seq < 0
    ):
        return False
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
        row = check.execute(
            "SELECT COALESCE(MAX(commit_seq), 0) AS commit_seq FROM commit_records"
        ).fetchone()
        if row is None or int(row["commit_seq"]) != snapshot_commit_seq:
            return False
        rows = check.execute(
            """
            SELECT blob_id, integrity_sha256, byte_length, storage_locator,
                   encryption_state
            FROM blob_records
            ORDER BY blob_id
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
        return actual == expected
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
            int(row["completed_at_us"]) if row["completed_at_us"] is not None else None
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
    destination.parent.mkdir(parents=True, exist_ok=True)
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
        os.replace(temporary, destination)
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
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
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
