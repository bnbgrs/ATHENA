"""Explicit physical purge for logically deleted ATHENA Source payloads."""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass

from athena.chat.service import ChatService
from athena.common.ids import (
    new_uuid7,
    uuid_from_blob,
    uuid_to_blob,
)
from athena.common.time import utc_now_us
from athena.lifecycle.runtime_lock import runtime_data_lock
from athena.source.blob_store import (
    ArchiveStorageUnavailableError,
    BlobIntegrityError,
    BlobStore,
    BlobStoreError,
)
from athena.storage.database import (
    DatabaseSnapshotChangedError,
    SQLiteDatabase,
)
from athena.storage.paths import RuntimePaths


class PhysicalPurgeError(RuntimeError):
    """Base error for explicit physical deletion."""


class PhysicalPurgeNotDeletedError(
    PhysicalPurgeError
):
    """Entity must be logically deleted before physical purge."""


class PhysicalPurgeBlockedError(
    PhysicalPurgeError
):
    """Physical purge cannot yet prove safe removal."""


class ProtectedPhysicalPurgeRequiredError(
    PhysicalPurgeError
):
    """Protected data requires the protected-scope purge path."""


@dataclass(
    frozen=True,
    slots=True,
)
class SourceBlobPurgeResult:
    source_id: uuid.UUID
    blob_id: uuid.UUID
    sanitized_source_ids: tuple[
        uuid.UUID,
        ...,
    ]
    deleted_replica_count: int
    audit_commit_id: uuid.UUID | None


class LifecyclePurgeService:
    """Physically remove deleted Raw Source bytes without unsafe cascades."""

    _ALLOWED_REFERENCE_TABLES = frozenset(
        {
            "archive_replication_outbox",
            "backup_snapshot_pins",
            "blob_records",
            "sources",
        }
    )

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

    def purge_deleted_source_blob(
        self,
        source_id: uuid.UUID,
    ) -> SourceBlobPurgeResult:
        actor_id = (
            self.chat.ensure_local_user()
        )

        with runtime_data_lock(
            self.paths.state_root
        ):
            (
                blob_id,
                storage_locator,
                integrity_sha256,
                byte_length,
                source_ids,
                needs_audit,
            ) = self._preflight(
                source_id
            )

            # Prove all configured physical replicas are
            # reachable, regular and hash-correct before
            # altering database payload metadata.
            try:
                self.blob_store.verified_replica_paths(
                    storage_locator=storage_locator,
                    expected_sha256=integrity_sha256,
                    expected_length=byte_length,
                )

            except ArchiveStorageUnavailableError as exc:
                raise PhysicalPurgeBlockedError(
                    "Archive Root is unavailable; "
                    "ATHENA cannot prove that every "
                    "Source replica can be deleted."
                ) from exc

            except (
                BlobIntegrityError,
                BlobStoreError,
            ) as exc:
                raise PhysicalPurgeBlockedError(
                    "Raw Source storage failed purge "
                    "preflight integrity verification."
                ) from exc

            (
                checked_preflight,
                snapshot,
            ) = self.database.stable_read(
                lambda connection: self._preflight_connection(
                    connection,
                    source_id,
                )
            )
            (
                checked_blob_id,
                checked_locator,
                checked_sha256,
                checked_length,
                checked_source_ids,
                checked_needs_audit,
            ) = checked_preflight

            if (
                checked_blob_id
                != blob_id
                or checked_locator
                != storage_locator
                or checked_sha256
                != integrity_sha256
                or checked_length
                != byte_length
                or checked_source_ids
                != source_ids
            ):
                raise PhysicalPurgeBlockedError(
                    "Source purge dependencies changed "
                    "during physical-delete preflight."
                )

            needs_audit = (
                needs_audit
                or checked_needs_audit
            )

            audit_commit_id: (
                uuid.UUID
                | None
            ) = None

            with self.database.write_transaction() as connection:
                try:
                    self.database.assert_snapshot_current(
                        connection,
                        snapshot,
                    )
                except DatabaseSnapshotChangedError as exc:
                    raise PhysicalPurgeBlockedError(
                        "Source purge dependencies changed "
                        "during physical-delete preflight."
                    ) from exc

                if needs_audit:
                    audit_commit_id = (
                        new_uuid7()
                    )

                    commit_seq = (
                        self._insert_commit(
                            connection,
                            commit_id=(
                                audit_commit_id
                            ),
                            actor_id=actor_id,
                        )
                    )

                    for deleted_source_id in source_ids:
                        connection.execute(
                            """
                            INSERT INTO commit_changes (
                                commit_seq,
                                entity_id,
                                revision_id,
                                change_type
                            ) VALUES (
                                ?, ?, NULL, 'update'
                            )
                            """,
                            (
                                commit_seq,
                                uuid_to_blob(
                                    deleted_source_id
                                ),
                            ),
                        )

                # Remove user-identifying/public Source
                # metadata but preserve technical identity,
                # timestamps, hashes and provenance linkage.
                placeholders = ", ".join(
                    "?"
                    for _source_id
                    in source_ids
                )

                connection.execute(
                    f"""
                    UPDATE sources
                    SET original_name = NULL,
                        original_modified_at_us = NULL,
                        source_uri = NULL
                    WHERE source_id IN (
                        {placeholders}
                    )
                    """,
                    tuple(
                        uuid_to_blob(
                            deleted_source_id
                        )
                        for deleted_source_id
                        in source_ids
                    ),
                )

                connection.execute(
                    """
                    DELETE FROM archive_replication_outbox
                    WHERE blob_id = ?
                    """,
                    (
                        uuid_to_blob(
                            blob_id
                        ),
                    ),
                )

                self._advance_archive_watermark(
                    connection
                )

            # The DB now contains no public filename/URI for
            # these deleted Sources and future backups exclude
            # this orphaned Raw Blob. Remove physical bytes.
            try:
                deleted_paths = (
                    self.blob_store
                    .purge_verified_replicas(
                        storage_locator=storage_locator,
                        expected_sha256=integrity_sha256,
                        expected_length=byte_length,
                    )
                )

            except (
                ArchiveStorageUnavailableError,
                BlobIntegrityError,
                BlobStoreError,
            ) as exc:
                raise PhysicalPurgeError(
                    "Source payload metadata was sanitized "
                    "but physical replica removal did not "
                    "complete; retry the purge."
                ) from exc

        return SourceBlobPurgeResult(
            source_id=source_id,
            blob_id=blob_id,
            sanitized_source_ids=source_ids,
            deleted_replica_count=len(
                deleted_paths
            ),
            audit_commit_id=(
                audit_commit_id
            ),
        )

    def _preflight(
        self,
        source_id: uuid.UUID,
    ) -> tuple[
        uuid.UUID,
        str,
        bytes,
        int,
        tuple[
            uuid.UUID,
            ...,
        ],
        bool,
    ]:
        preflight, _snapshot = self.database.stable_read(
            lambda connection: self._preflight_connection(
                connection,
                source_id,
            )
        )
        return preflight

    def _preflight_connection(
        self,
        connection: sqlite3.Connection,
        source_id: uuid.UUID,
    ) -> tuple[
        uuid.UUID,
        str,
        bytes,
        int,
        tuple[
            uuid.UUID,
            ...,
        ],
        bool,
    ]:
        requested = connection.execute(
            """
            SELECT
                source.source_id,
                source.blob_id,
                source_entity.lifecycle_state,
                source_entity.protection_scope_id,
                blob.storage_locator,
                blob.integrity_sha256,
                blob.byte_length,
                blob.encryption_state,
                blob_entity.protection_scope_id
                    AS blob_protection_scope_id
            FROM sources AS source
            JOIN entity_registry AS source_entity
              ON source_entity.entity_id = source.source_id
            JOIN blob_records AS blob
              ON blob.blob_id = source.blob_id
            JOIN entity_registry AS blob_entity
              ON blob_entity.entity_id = blob.blob_id
            WHERE source.source_id = ?
            """,
            (
                uuid_to_blob(
                    source_id
                ),
            ),
        ).fetchone()

        if requested is None:
            raise LookupError(
                str(
                    source_id
                )
            )

        if (
            str(
                requested[
                    "lifecycle_state"
                ]
            )
            != "deleted"
        ):
            raise PhysicalPurgeNotDeletedError(
                "Source must be logically deleted "
                "before physical purge."
            )

        if (
            requested[
                "protection_scope_id"
            ]
            is not None
            or requested[
                "blob_protection_scope_id"
            ]
            is not None
            or str(
                requested[
                    "encryption_state"
                ]
            )
            != "none"
        ):
            raise ProtectedPhysicalPurgeRequiredError(
                "Protected Source deletion requires "
                "the protected-scope physical purge path."
            )

        blob_id = uuid_from_blob(
            bytes(
                requested[
                    "blob_id"
                ]
            )
        )

        source_rows = connection.execute(
            """
            SELECT
                source.source_id,
                source.original_name,
                source.original_modified_at_us,
                source.source_uri,
                entity.lifecycle_state,
                entity.protection_scope_id
            FROM sources AS source
            JOIN entity_registry AS entity
              ON entity.entity_id = source.source_id
            WHERE source.blob_id = ?
            ORDER BY source.source_id
            """,
            (
                uuid_to_blob(
                    blob_id
                ),
            ),
        ).fetchall()

        if not source_rows:
            raise PhysicalPurgeBlockedError(
                "BlobRecord has no Source ownership rows."
            )

        for row in source_rows:
            if (
                str(
                    row[
                        "lifecycle_state"
                    ]
                )
                != "deleted"
            ):
                raise PhysicalPurgeBlockedError(
                    "Raw Blob is still referenced by "
                    "a non-deleted Source."
                )

            if (
                row[
                    "protection_scope_id"
                ]
                is not None
            ):
                raise ProtectedPhysicalPurgeRequiredError(
                    "Shared Raw Blob has protected "
                    "Source membership."
                )

        source_ids = tuple(
            uuid_from_blob(
                bytes(
                    row[
                        "source_id"
                    ]
                )
            )
            for row in source_rows
        )

        transition = connection.execute(
            """
            SELECT 1
            FROM source_protection_transitions AS transition
            WHERE transition.old_blob_id = ?
               OR transition.target_blob_id = ?
               OR transition.source_id IN (
                    SELECT source_id
                    FROM sources
                    WHERE blob_id = ?
               )
            LIMIT 1
            """,
            (
                uuid_to_blob(
                    blob_id
                ),
                uuid_to_blob(
                    blob_id
                ),
                uuid_to_blob(
                    blob_id
                ),
            ),
        ).fetchone()

        if transition is not None:
            raise PhysicalPurgeBlockedError(
                "Source Protection transition is "
                "still active for this Raw Blob."
            )

        creating_backup = connection.execute(
            """
            SELECT 1
            FROM backup_snapshots
            WHERE state = 'creating'
            LIMIT 1
            """
        ).fetchone()

        if creating_backup is not None:
            raise PhysicalPurgeBlockedError(
                "Physical purge is blocked while "
                "a backup snapshot is creating."
            )

        pinned = connection.execute(
            """
            SELECT 1
            FROM backup_snapshot_pins
            WHERE blob_id = ?
            LIMIT 1
            """,
            (
                uuid_to_blob(
                    blob_id
                ),
            ),
        ).fetchone()

        if pinned is not None:
            raise PhysicalPurgeBlockedError(
                "Raw Blob is pinned by an incomplete "
                "backup snapshot."
            )

        blockers = (
            self._payload_reference_blockers(
                connection,
                blob_id=blob_id,
                source_ids=source_ids,
            )
        )

        if blockers:
            raise PhysicalPurgeBlockedError(
                "Physical Source purge is blocked by "
                "persisted dependent Source payload state: "
                + ", ".join(
                    blockers
                )
            )

        outbox = connection.execute(
            """
            SELECT 1
            FROM archive_replication_outbox
            WHERE blob_id = ?
            LIMIT 1
            """,
            (
                uuid_to_blob(
                    blob_id
                ),
            ),
        ).fetchone()

        needs_audit = (
            outbox is not None
            or any(
                row[
                    "original_name"
                ]
                is not None
                or row[
                    "original_modified_at_us"
                ]
                is not None
                or row[
                    "source_uri"
                ]
                is not None
                for row in source_rows
            )
        )

        return (
            blob_id,
            str(
                requested[
                    "storage_locator"
                ]
            ),
            bytes(
                requested[
                    "integrity_sha256"
                ]
            ),
            int(
                requested[
                    "byte_length"
                ]
            ),
            source_ids,
            needs_audit,
        )

    @classmethod
    def _payload_reference_blockers(
        cls,
        connection: sqlite3.Connection,
        *,
        blob_id: uuid.UUID,
        source_ids: tuple[
            uuid.UUID,
            ...,
        ],
    ) -> tuple[
        str,
        ...,
    ]:
        rows = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        ).fetchall()

        blockers: set[
            str
        ] = set()

        source_blobs = tuple(
            uuid_to_blob(
                source_id
            )
            for source_id
            in source_ids
        )

        source_placeholders = ", ".join(
            "?"
            for _source_id
            in source_ids
        )

        for table_row in rows:
            table = str(
                table_row[
                    "name"
                ]
            )

            if (
                table
                in cls._ALLOWED_REFERENCE_TABLES
            ):
                continue

            quoted_table = (
                cls._quote_identifier(
                    table
                )
            )

            columns = {
                str(
                    column[
                        "name"
                    ]
                )
                for column
                in connection.execute(
                    f"PRAGMA table_info({quoted_table})"
                ).fetchall()
            }

            if "source_id" in columns:
                quoted_column = (
                    cls._quote_identifier(
                        "source_id"
                    )
                )

                count = int(
                    connection.execute(
                        f"""
                        SELECT COUNT(*)
                        FROM {quoted_table}
                        WHERE {quoted_column} IN (
                            {source_placeholders}
                        )
                        """,
                        source_blobs,
                    ).fetchone()[0]
                )

                if count:
                    blockers.add(
                        f"{table}.source_id={count}"
                    )

            if "blob_id" in columns:
                quoted_column = (
                    cls._quote_identifier(
                        "blob_id"
                    )
                )

                count = int(
                    connection.execute(
                        f"""
                        SELECT COUNT(*)
                        FROM {quoted_table}
                        WHERE {quoted_column} = ?
                        """,
                        (
                            uuid_to_blob(
                                blob_id
                            ),
                        ),
                    ).fetchone()[0]
                )

                if count:
                    blockers.add(
                        f"{table}.blob_id={count}"
                    )

        return tuple(
            sorted(
                blockers
            )
        )

    @staticmethod
    def _quote_identifier(
        value: str,
    ) -> str:
        if "\x00" in value:
            raise PhysicalPurgeError(
                "Unsafe SQLite identifier."
            )

        return (
            '"'
            + value.replace(
                '"',
                '""',
            )
            + '"'
        )

    @staticmethod
    def _insert_commit(
        connection: sqlite3.Connection,
        *,
        commit_id: uuid.UUID,
        actor_id: uuid.UUID,
    ) -> int:
        cursor = connection.execute(
            """
            INSERT INTO commit_records (
                commit_id,
                committed_at_us,
                actor_id,
                operation_type,
                reason
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                uuid_to_blob(
                    commit_id
                ),
                utc_now_us(),
                uuid_to_blob(
                    actor_id
                ),
                "lifecycle.purge.source_payload",
                "explicit user physical purge",
            ),
        )

        if cursor.lastrowid is None:
            raise PhysicalPurgeError(
                "SQLite did not return a "
                "physical-purge commit sequence."
            )

        return int(
            cursor.lastrowid
        )

    @staticmethod
    def _advance_archive_watermark(
        connection: sqlite3.Connection,
    ) -> None:
        pending = connection.execute(
            """
            SELECT MIN(outbox_seq) AS first_pending
            FROM archive_replication_outbox
            WHERE state = 'pending'
            """
        ).fetchone()

        maximum = connection.execute(
            """
            SELECT COALESCE(MAX(outbox_seq), 0) AS maximum
            FROM archive_replication_outbox
            """
        ).fetchone()

        current = connection.execute(
            """
            SELECT contiguous_verified_seq
            FROM archive_replication_watermark
            WHERE singleton_id = 1
            """
        ).fetchone()

        if (
            pending is None
            or maximum is None
            or current is None
        ):
            raise PhysicalPurgeError(
                "Archive replication watermark "
                "state is incomplete."
            )

        first_pending = (
            pending[
                "first_pending"
            ]
        )

        candidate = (
            int(
                maximum[
                    "maximum"
                ]
            )
            if first_pending is None
            else int(
                first_pending
            )
            - 1
        )

        previous = int(
            current[
                "contiguous_verified_seq"
            ]
        )

        connection.execute(
            """
            UPDATE archive_replication_watermark
            SET contiguous_verified_seq = ?,
                updated_at_us = ?
            WHERE singleton_id = 1
            """,
            (
                max(
                    previous,
                    candidate,
                ),
                utc_now_us(),
            ),
        )
