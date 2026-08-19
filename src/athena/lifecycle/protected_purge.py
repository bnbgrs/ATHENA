"""Explicit crypto-erasure of ATHENA ProtectionScopes."""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from athena.chat.service import ChatService
from athena.common.ids import (
    new_uuid7,
    uuid_from_blob,
    uuid_to_blob,
)
from athena.common.time import utc_now_us
from athena.lifecycle.deletion import (
    record_deletion,
)
from athena.lifecycle.runtime_lock import (
    runtime_data_lock,
)
from athena.security.service import (
    ProtectedContentService,
)
from athena.source.blob_store import (
    ArchiveStorageUnavailableError,
    BlobIntegrityError,
    BlobStore,
    BlobStoreError,
)
from athena.source.models import BlobStorageArea
from athena.storage.database import (
    DatabaseSnapshotChangedError,
    SQLiteDatabase,
)
from athena.storage.paths import (
    RuntimePaths,
)

logger = logging.getLogger(__name__)


class ProtectedScopeDeletionError(
    RuntimeError
):
    """Base error for explicit ProtectionScope deletion."""


class ProtectedScopeDeletionBlockedError(
    ProtectedScopeDeletionError
):
    """ProtectionScope deletion cannot currently be proven safe."""


class ProtectedScopeDeletionPreviewStaleError(
    ProtectedScopeDeletionError
):
    """ProtectionScope dependencies changed after user review."""


class ProtectedScopeAlreadyDeletedError(
    ProtectedScopeDeletionError
):
    """ProtectionScope has already entered pending_delete."""


class ProtectedScopePhysicalCleanupError(
    ProtectedScopeDeletionError
):
    """Crypto-erasure committed but ciphertext cleanup is incomplete."""


@dataclass(
    frozen=True,
    slots=True,
)
class ProtectedScopeDeletionPreview:
    protection_scope_id: uuid.UUID
    lifecycle_state: str
    source_count: int
    protected_payload_count: int
    protected_blob_count: int
    scope_key_count: int
    preview_digest: str


@dataclass(
    frozen=True,
    slots=True,
)
class ProtectedScopeDeletionResult:
    protection_scope_id: uuid.UUID
    deleted_source_ids: tuple[
        uuid.UUID,
        ...,
    ]
    destroyed_scope_key_count: int
    removed_payload_count: int
    removed_blob_envelope_count: int
    deleted_replica_count: int
    commit_id: uuid.UUID
    preview_digest: str


@dataclass(
    frozen=True,
    slots=True,
)
class _ScopeSource:
    source_id: uuid.UUID
    blob_id: uuid.UUID
    lifecycle_state: str


@dataclass(
    frozen=True,
    slots=True,
)
class _ScopeBlob:
    blob_id: uuid.UUID
    storage_locator: str
    integrity_sha256: bytes
    byte_length: int


@dataclass(
    frozen=True,
    slots=True,
)
class _ScopeState:
    protection_scope_id: uuid.UUID
    lifecycle_state: str
    current_scope_key_id: uuid.UUID | None
    sources: tuple[
        _ScopeSource,
        ...,
    ]
    blobs: tuple[
        _ScopeBlob,
        ...,
    ]
    payload_ids: tuple[
        uuid.UUID,
        ...,
    ]
    scope_key_ids: tuple[
        uuid.UUID,
        ...,
    ]
    preview_digest: str


class ProtectedScopePurgeService:
    """Preview and explicitly crypto-erase one ProtectionScope."""

    _SOURCE_REFERENCE_ALLOWLIST = frozenset(
        {
            "protected_sources",
            "source_protection_transitions",
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
        protected_content: ProtectedContentService,
        deletion_sync: Callable[
            [],
            object,
        ]
        | None = None,
    ) -> None:
        self.database = database
        self.blob_store = blob_store
        self.paths = paths
        self.chat = chat
        self.protected_content = (
            protected_content
        )
        self.deletion_sync = (
            deletion_sync
        )

    def preview(
        self,
        protection_scope_id: uuid.UUID,
    ) -> ProtectedScopeDeletionPreview:
        state, _snapshot = self.database.stable_read(
            lambda connection: self._state(
                connection,
                protection_scope_id,
            )
        )

        if (
            state.lifecycle_state
            == "pending_delete"
        ):
            raise (
                ProtectedScopeAlreadyDeletedError(
                    str(
                        protection_scope_id
                    )
                )
            )

        return (
            ProtectedScopeDeletionPreview(
                protection_scope_id=(
                    protection_scope_id
                ),
                lifecycle_state=(
                    state.lifecycle_state
                ),
                source_count=len(
                    state.sources
                ),
                protected_payload_count=len(
                    state.payload_ids
                ),
                protected_blob_count=len(
                    state.blobs
                ),
                scope_key_count=len(
                    state.scope_key_ids
                ),
                preview_digest=(
                    state.preview_digest
                ),
            )
        )

    def delete(
        self,
        protection_scope_id: uuid.UUID,
        *,
        preview_digest: str,
    ) -> ProtectedScopeDeletionResult:
        normalized_digest = (
            preview_digest
            .strip()
            .lower()
        )

        if (
            len(
                normalized_digest
            )
            != 64
            or any(
                character
                not in (
                    "0123456789abcdef"
                )
                for character
                in normalized_digest
            )
        ):
            raise ValueError(
                "preview_digest must be "
                "a SHA-256 hex digest."
            )

        actor_id = (
            self.chat.ensure_local_user()
        )

        with runtime_data_lock(
            self.paths.state_root
        ):
            state, _initial_snapshot = self.database.stable_read(
                lambda connection: self._state(
                    connection,
                    protection_scope_id,
                )
            )

            if (
                state.lifecycle_state
                == "pending_delete"
            ):
                raise (
                    ProtectedScopeAlreadyDeletedError(
                        str(
                            protection_scope_id
                        )
                    )
                )

            if (
                state.preview_digest
                != normalized_digest
            ):
                raise (
                    ProtectedScopeDeletionPreviewStaleError(
                        "ProtectionScope dependencies "
                        "changed after preview."
                    )
                )

            # Before key destruction, every known
            # ciphertext replica must be reachable
            # and integrity-verifiable.
            # Before key destruction, at least one actual current
            # ciphertext replica must be reachable and verified.
            # A merely configured but unavailable Archive Root is
            # not treated as an existing replica.
            for blob in state.blobs:
                try:
                    self._verify_reachable_ciphertext_replicas(
                        blob
                    )

                except (
                    BlobIntegrityError,
                    BlobStoreError,
                ) as exc:
                    raise (
                        ProtectedScopeDeletionBlockedError(
                            "Protected ciphertext "
                            "failed deletion preflight."
                        )
                    ) from exc

            # Destroy the runtime plaintext Scope Key
            # before persistent key reachability.
            self.protected_content.lock_scope(
                protection_scope_id
            )

            (
                locked_state,
                snapshot,
            ) = self.database.stable_read(
                lambda connection: self._state(
                    connection,
                    protection_scope_id,
                )
            )

            if (
                locked_state.lifecycle_state
                == "pending_delete"
            ):
                raise (
                    ProtectedScopeAlreadyDeletedError(
                        str(
                            protection_scope_id
                        )
                    )
                )

            if (
                locked_state.preview_digest
                != state.preview_digest
            ):
                raise (
                    ProtectedScopeDeletionPreviewStaleError(
                        "ProtectionScope dependencies "
                        "changed during deletion."
                    )
                )

            commit_id = new_uuid7()
            deleted_at_us = utc_now_us()

            with (
                self.database
                .write_transaction()
                as connection
            ):
                try:
                    self.database.assert_snapshot_current(
                        connection,
                        snapshot,
                    )
                except DatabaseSnapshotChangedError as exc:
                    raise (
                        ProtectedScopeDeletionPreviewStaleError(
                            "ProtectionScope dependencies "
                            "changed during deletion."
                        )
                    ) from exc

                commit_seq = (
                    self._insert_commit(
                        connection,
                        commit_id=commit_id,
                        actor_id=actor_id,
                        committed_at_us=(
                            deleted_at_us
                        ),
                    )
                )

                for source in (
                    locked_state.sources
                ):
                    was_deleted = (
                        source.lifecycle_state
                        == "deleted"
                    )

                    if not was_deleted:
                        self._mark_source_deleted(
                            connection,
                            source_id=(
                                source.source_id
                            ),
                            actor_id=actor_id,
                            commit_seq=(
                                commit_seq
                            ),
                        )

                    existing = (
                        connection.execute(
                            """
                            SELECT entity_type
                            FROM deletion_ledger
                            WHERE entity_id = ?
                            """,
                            (
                                uuid_to_blob(
                                    source.source_id
                                ),
                            ),
                        ).fetchone()
                    )

                    if existing is None:
                        record_deletion(
                            connection,
                            entity_id=(
                                source.source_id
                            ),
                            entity_type="source",
                            deleted_at_us=(
                                deleted_at_us
                            ),
                            deletion_commit_seq=(
                                commit_seq
                            ),
                            deleted_by_actor_id=(
                                actor_id
                            ),
                        )

                    elif (
                        str(
                            existing[
                                "entity_type"
                            ]
                        )
                        != "source"
                    ):
                        raise (
                            ProtectedScopeDeletionError(
                                "Existing deletion "
                                "ledger entry conflicts "
                                "with protected Source."
                            )
                        )

                    if not was_deleted:
                        connection.execute(
                            """
                            INSERT INTO commit_changes (
                                commit_seq,
                                entity_id,
                                revision_id,
                                change_type
                            ) VALUES (
                                ?, ?, NULL, 'deleted'
                            )
                            """,
                            (
                                commit_seq,
                                uuid_to_blob(
                                    source.source_id
                                ),
                            ),
                        )

                for blob in locked_state.blobs:
                    blob_deleted = self._mark_blob_deleted(
                        connection,
                        blob_id=blob.blob_id,
                        actor_id=actor_id,
                        commit_seq=commit_seq,
                    )

                    if blob_deleted:
                        connection.execute(
                            """
                            INSERT INTO commit_changes (
                                commit_seq,
                                entity_id,
                                revision_id,
                                change_type
                            ) VALUES (
                                ?, ?, NULL, 'deleted'
                            )
                            """,
                            (
                                commit_seq,
                                uuid_to_blob(
                                    blob.blob_id
                                ),
                            ),
                        )

                scope_existing = (
                    connection.execute(
                        """
                        SELECT entity_type
                        FROM deletion_ledger
                        WHERE entity_id = ?
                        """,
                        (
                            uuid_to_blob(
                                protection_scope_id
                            ),
                        ),
                    ).fetchone()
                )

                if scope_existing is None:
                    record_deletion(
                        connection,
                        entity_id=(
                            protection_scope_id
                        ),
                        entity_type=(
                            "protection_scope"
                        ),
                        deleted_at_us=(
                            deleted_at_us
                        ),
                        deletion_commit_seq=(
                            commit_seq
                        ),
                        deleted_by_actor_id=(
                            actor_id
                        ),
                    )

                elif (
                    str(
                        scope_existing[
                            "entity_type"
                        ]
                    )
                    != "protection_scope"
                ):
                    raise (
                        ProtectedScopeDeletionError(
                            "Existing deletion ledger "
                            "entry conflicts with "
                            "ProtectionScope."
                        )
                    )

                source_ids = tuple(
                    source.source_id
                    for source
                    in locked_state.sources
                )

                if source_ids:
                    placeholders = ", ".join(
                        "?"
                        for _source_id
                        in source_ids
                    )

                    # Protected Source rows already
                    # withhold original name/URI.
                    # Remove remaining descriptive type
                    # metadata as part of purge.
                    connection.execute(
                        f"""
                        UPDATE sources
                        SET
                            source_type = 'other',
                            original_name = NULL,
                            original_modified_at_us = NULL,
                            mime_type = NULL,
                            source_uri = NULL
                        WHERE source_id IN (
                            {placeholders}
                        )
                        """,
                        tuple(
                            uuid_to_blob(
                                source_id
                            )
                            for source_id
                            in source_ids
                        ),
                    )

                blob_ids = tuple(
                    blob.blob_id
                    for blob
                    in locked_state.blobs
                )

                if blob_ids:
                    placeholders = ", ".join(
                        "?"
                        for _blob_id
                        in blob_ids
                    )

                    connection.execute(
                        f"""
                        DELETE FROM
                            archive_replication_outbox
                        WHERE blob_id IN (
                            {placeholders}
                        )
                        """,
                        tuple(
                            uuid_to_blob(
                                blob_id
                            )
                            for blob_id
                            in blob_ids
                        ),
                    )

                # No active transition is allowed by
                # _state(), but stale terminal rows must
                # not preserve references during erase.
                connection.execute(
                    """
                    DELETE FROM
                        source_protection_transitions
                    WHERE protection_scope_id = ?
                    """,
                    (
                        uuid_to_blob(
                            protection_scope_id
                        ),
                    ),
                )

                # protected_sources references the
                # encrypted metadata payload, therefore
                # remove Source membership first.
                connection.execute(
                    """
                    DELETE FROM protected_sources
                    WHERE protection_scope_id = ?
                    """,
                    (
                        uuid_to_blob(
                            protection_scope_id
                        ),
                    ),
                )

                # Destroy wrapped per-Blob DEKs.
                connection.execute(
                    """
                    DELETE FROM
                        protected_blob_envelopes
                    WHERE protection_scope_id = ?
                    """,
                    (
                        uuid_to_blob(
                            protection_scope_id
                        ),
                    ),
                )

                # Destroy ciphertext + wrapped DEKs for
                # structured Protected Content.
                connection.execute(
                    """
                    DELETE FROM protected_payloads
                    WHERE protection_scope_id = ?
                    """,
                    (
                        uuid_to_blob(
                            protection_scope_id
                        ),
                    ),
                )

                # Break the current-key FK before
                # deleting wrapped Scope Key rows.
                updated = connection.execute(
                    """
                    UPDATE protection_scopes
                    SET
                        lifecycle_state =
                            'pending_delete',
                        current_scope_key_id = NULL,
                        neutral_label = NULL
                    WHERE protection_scope_id = ?
                    """,
                    (
                        uuid_to_blob(
                            protection_scope_id
                        ),
                    ),
                )

                if updated.rowcount != 1:
                    raise (
                        ProtectedScopeDeletionError(
                            "ProtectionScope "
                            "disappeared during "
                            "crypto-erasure."
                        )
                    )

                # Decisive persistent crypto-erasure:
                # the Root Key no longer has a wrapped
                # Scope Key to recover.
                connection.execute(
                    """
                    DELETE FROM
                        protection_scope_keys
                    WHERE protection_scope_id = ?
                    """,
                    (
                        uuid_to_blob(
                            protection_scope_id
                        ),
                    ),
                )

                self._advance_archive_watermark(
                    connection
                )

            # Propagate deletion intent as early as
            # possible after the durable DB commit.
            # BackupService handles ordinary per-target
            # offline failures internally.
            if (
                self.deletion_sync
                is not None
            ):
                try:
                    self.deletion_sync()

                except Exception:
                    logger.exception(
                        "ProtectionScope deletion "
                        "ledger propagation failed",
                        extra={
                            "event": (
                                "lifecycle."
                                "protection_scope."
                                "deletion_sync_failed"
                            )
                        },
                    )

            deleted_replica_count = 0

            try:
                for blob in state.blobs:
                    deleted_replica_count += (
                        self._purge_reachable_ciphertext_replicas(
                            blob
                        )
                    )

            except (
                ArchiveStorageUnavailableError,
                BlobIntegrityError,
                BlobStoreError,
            ) as exc:
                # Keys and envelopes are already
                # destroyed. Residual bytes are now
                # ciphertext without current key
                # reachability and cleanup is retryable.
                raise (
                    ProtectedScopePhysicalCleanupError(
                        "ProtectionScope "
                        "crypto-erasure committed, "
                        "but residual ciphertext "
                        "cleanup did not complete."
                    )
                ) from exc

        return ProtectedScopeDeletionResult(
            protection_scope_id=(
                protection_scope_id
            ),
            deleted_source_ids=tuple(
                source.source_id
                for source
                in state.sources
            ),
            destroyed_scope_key_count=len(
                state.scope_key_ids
            ),
            removed_payload_count=len(
                state.payload_ids
            ),
            removed_blob_envelope_count=len(
                state.blobs
            ),
            deleted_replica_count=(
                deleted_replica_count
            ),
            commit_id=commit_id,
            preview_digest=(
                state.preview_digest
            ),
        )

    def _verify_reachable_ciphertext_replicas(
        self,
        blob: _ScopeBlob,
    ) -> tuple[Path, ...]:
        """Verify every currently reachable active ciphertext replica.

        A configured but unavailable Archive Root is not itself proof that
        an Archive replica exists. At least one actual current replica must
        remain reachable and integrity-verifiable before key destruction.
        """

        relative = Path(
            blob.storage_locator
        )

        if (
            relative.is_absolute()
            or ".." in relative.parts
        ):
            raise ProtectedScopeDeletionBlockedError(
                "Protected ciphertext has an unsafe "
                "storage locator."
            )

        verified: list[
            Path
        ] = []

        spool_path = (
            self.paths.spool_root
            / relative
        )

        if spool_path.is_file():
            verified.append(
                self.blob_store.verify_blob(
                    storage_area=(
                        BlobStorageArea.SPOOL
                    ),
                    storage_locator=(
                        blob.storage_locator
                    ),
                    expected_sha256=(
                        blob.integrity_sha256
                    ),
                    expected_length=(
                        blob.byte_length
                    ),
                )
            )

        archive_root = (
            self.paths.archive_root
        )

        if (
            archive_root is not None
            and archive_root.is_dir()
        ):
            archive_path = (
                archive_root
                / relative
            )

            if archive_path.is_file():
                verified.append(
                    self.blob_store.verify_blob(
                        storage_area=(
                            BlobStorageArea.ARCHIVE
                        ),
                        storage_locator=(
                            blob.storage_locator
                        ),
                        expected_sha256=(
                            blob.integrity_sha256
                        ),
                        expected_length=(
                            blob.byte_length
                        ),
                    )
                )

        if not verified:
            raise ProtectedScopeDeletionBlockedError(
                "Protected ciphertext has no "
                "reachable integrity-verified "
                "active replica."
            )

        resolved: set[
            Path
        ] = set()

        unique: list[
            Path
        ] = []

        for candidate in verified:
            canonical = candidate.resolve()

            if canonical in resolved:
                continue

            resolved.add(
                canonical
            )

            unique.append(
                candidate
            )

        return tuple(
            unique
        )

    def _purge_reachable_ciphertext_replicas(
        self,
        blob: _ScopeBlob,
    ) -> int:
        """Re-verify and remove every currently reachable active replica."""

        relative = Path(
            blob.storage_locator
        )

        if (
            relative.is_absolute()
            or ".." in relative.parts
        ):
            raise BlobStoreError(
                "Protected ciphertext has an unsafe "
                "storage locator."
            )

        candidates: list[
            tuple[BlobStorageArea, Path]
        ] = [
            (
                BlobStorageArea.SPOOL,
                self.paths.spool_root
                / relative,
            )
        ]

        archive_root = (
            self.paths.archive_root
        )

        if (
            archive_root is not None
            and archive_root.is_dir()
        ):
            candidates.append(
                (
                    BlobStorageArea.ARCHIVE,
                    archive_root
                    / relative,
                )
            )

        deleted = 0

        resolved: set[
            Path
        ] = set()

        for (
            storage_area,
            candidate,
        ) in candidates:
            if not candidate.is_file():
                continue

            verified = (
                self.blob_store.verify_blob(
                    storage_area=storage_area,
                    storage_locator=(
                        blob.storage_locator
                    ),
                    expected_sha256=(
                        blob.integrity_sha256
                    ),
                    expected_length=(
                        blob.byte_length
                    ),
                )
            )

            canonical = (
                verified.resolve()
            )

            if canonical in resolved:
                continue

            resolved.add(
                canonical
            )

            try:
                verified.unlink()

            except OSError as exc:
                raise BlobStoreError(
                    "Verified Protected ciphertext "
                    "replica could not be removed."
                ) from exc

            deleted += 1

        return deleted

    def _state(
        self,
        connection: sqlite3.Connection,
        protection_scope_id: uuid.UUID,
    ) -> _ScopeState:
        scope_blob = uuid_to_blob(
            protection_scope_id
        )

        scope = connection.execute(
            """
            SELECT
                lifecycle_state,
                current_scope_key_id
            FROM protection_scopes
            WHERE protection_scope_id = ?
            """,
            (
                scope_blob,
            ),
        ).fetchone()

        if scope is None:
            raise LookupError(
                str(
                    protection_scope_id
                )
            )

        lifecycle_state = str(
            scope[
                "lifecycle_state"
            ]
        )

        raw_current_key = (
            scope[
                "current_scope_key_id"
            ]
        )

        current_scope_key_id = (
            None
            if raw_current_key is None
            else uuid_from_blob(
                bytes(
                    raw_current_key
                )
            )
        )
        if lifecycle_state == "pending_delete":
            return self._pending_delete_state(
                connection,
                protection_scope_id=(
                    protection_scope_id
                ),
                current_scope_key_id=(
                    current_scope_key_id
                ),
            )


        transition = (
            connection.execute(
                """
                SELECT 1
                FROM
                    source_protection_transitions
                WHERE
                    protection_scope_id = ?
                LIMIT 1
                """,
                (
                    scope_blob,
                ),
            ).fetchone()
        )

        if transition is not None:
            raise (
                ProtectedScopeDeletionBlockedError(
                    "ProtectionScope has an "
                    "active Source protection "
                    "transition."
                )
            )

        source_rows = (
            connection.execute(
                """
                SELECT DISTINCT
                    source.source_id,
                    source.blob_id,
                    entity.lifecycle_state,
                    blob.encryption_state
                FROM sources AS source
                JOIN entity_registry AS entity
                  ON entity.entity_id =
                     source.source_id
                JOIN blob_records AS blob
                  ON blob.blob_id =
                     source.blob_id
                WHERE
                    entity.protection_scope_id = ?
                    OR EXISTS (
                        SELECT 1
                        FROM protected_sources
                            AS protected
                        WHERE
                            protected.source_id =
                                source.source_id
                            AND
                            protected.protection_scope_id = ?
                    )
                ORDER BY source.source_id
                """,
                (
                    scope_blob,
                    scope_blob,
                ),
            ).fetchall()
        )

        sources: list[
            _ScopeSource
        ] = []

        source_blob_ids: set[
            uuid.UUID
        ] = set()

        for row in source_rows:
            if (
                str(
                    row[
                        "encryption_state"
                    ]
                )
                != "protected_v1"
            ):
                raise (
                    ProtectedScopeDeletionBlockedError(
                        "ProtectionScope Source "
                        "references non-protected "
                        "Raw Archive bytes."
                    )
                )

            source = _ScopeSource(
                source_id=uuid_from_blob(
                    bytes(
                        row[
                            "source_id"
                        ]
                    )
                ),
                blob_id=uuid_from_blob(
                    bytes(
                        row[
                            "blob_id"
                        ]
                    )
                ),
                lifecycle_state=str(
                    row[
                        "lifecycle_state"
                    ]
                ),
            )

            sources.append(
                source
            )

            source_blob_ids.add(
                source.blob_id
            )

        envelope_rows = (
            connection.execute(
                """
                SELECT
                    envelope.blob_id,
                    blob.storage_locator,
                    blob.integrity_sha256,
                    blob.byte_length,
                    blob.encryption_state
                FROM protected_blob_envelopes
                    AS envelope
                JOIN blob_records AS blob
                  ON blob.blob_id =
                     envelope.blob_id
                WHERE
                    envelope.protection_scope_id = ?
                ORDER BY envelope.blob_id
                """,
                (
                    scope_blob,
                ),
            ).fetchall()
        )

        blobs: list[
            _ScopeBlob
        ] = []

        envelope_blob_ids: set[
            uuid.UUID
        ] = set()

        for row in envelope_rows:
            if (
                str(
                    row[
                        "encryption_state"
                    ]
                )
                != "protected_v1"
            ):
                raise (
                    ProtectedScopeDeletionBlockedError(
                        "ProtectionScope envelope "
                        "references non-protected "
                        "Blob storage."
                    )
                )

            blob = _ScopeBlob(
                blob_id=uuid_from_blob(
                    bytes(
                        row[
                            "blob_id"
                        ]
                    )
                ),
                storage_locator=str(
                    row[
                        "storage_locator"
                    ]
                ),
                integrity_sha256=bytes(
                    row[
                        "integrity_sha256"
                    ]
                ),
                byte_length=int(
                    row[
                        "byte_length"
                    ]
                ),
            )

            blobs.append(
                blob
            )

            envelope_blob_ids.add(
                blob.blob_id
            )

        if not (
            source_blob_ids
            <= envelope_blob_ids
        ):
            raise (
                ProtectedScopeDeletionBlockedError(
                    "Protected Source Blob has "
                    "no matching Scope envelope."
                )
            )

        payload_ids = tuple(
            uuid_from_blob(
                bytes(
                    row[
                        "protected_payload_id"
                    ]
                )
            )
            for row
            in connection.execute(
                """
                SELECT protected_payload_id
                FROM protected_payloads
                WHERE protection_scope_id = ?
                ORDER BY protected_payload_id
                """,
                (
                    scope_blob,
                ),
            ).fetchall()
        )

        scope_key_ids = tuple(
            uuid_from_blob(
                bytes(
                    row[
                        "scope_key_id"
                    ]
                )
            )
            for row
            in connection.execute(
                """
                SELECT scope_key_id
                FROM protection_scope_keys
                WHERE protection_scope_id = ?
                ORDER BY
                    key_version,
                    scope_key_id
                """,
                (
                    scope_blob,
                ),
            ).fetchall()
        )

        if (
            lifecycle_state
            != "pending_delete"
            and (
                current_scope_key_id
                is None
                or current_scope_key_id
                not in scope_key_ids
            )
        ):
            raise (
                ProtectedScopeDeletionBlockedError(
                    "ProtectionScope current "
                    "key state is inconsistent."
                )
            )

        # The current implementation only knows how
        # to purge canonical protected Source and
        # BlobRecord entities. Any future protected
        # canonical type must get its own explicit
        # purge semantics before key destruction.
        allowed_member_ids = {
            source.source_id
            for source
            in sources
        } | envelope_blob_ids

        active_members = (
            connection.execute(
                """
                SELECT
                    entity_id,
                    entity_type
                FROM entity_registry
                WHERE protection_scope_id = ?
                  AND lifecycle_state != 'deleted'
                ORDER BY entity_id
                """,
                (
                    scope_blob,
                ),
            ).fetchall()
        )

        unsupported = [
            (
                uuid_from_blob(
                    bytes(
                        row[
                            "entity_id"
                        ]
                    )
                ),
                str(
                    row[
                        "entity_type"
                    ]
                ),
            )
            for row
            in active_members
            if uuid_from_blob(
                bytes(
                    row[
                        "entity_id"
                    ]
                )
            )
            not in allowed_member_ids
        ]

        if unsupported:
            raise (
                ProtectedScopeDeletionBlockedError(
                    "ProtectionScope contains "
                    "active canonical entities "
                    "outside the supported "
                    "protected Source/Blob "
                    "lifecycle."
                )
            )

        blockers = (
            self._source_reference_blockers(
                connection,
                sources=tuple(
                    sources
                ),
            )
        )

        if blockers:
            raise (
                ProtectedScopeDeletionBlockedError(
                    "Protected Source has "
                    "retained dependent state: "
                    + ", ".join(
                        blockers
                    )
                )
            )

        for blob_id in (
            envelope_blob_ids
        ):
            outside_live_source = (
                connection.execute(
                    """
                    SELECT 1
                    FROM sources AS source
                    JOIN entity_registry AS entity
                      ON entity.entity_id =
                         source.source_id
                    WHERE source.blob_id = ?
                      AND entity.lifecycle_state
                          != 'deleted'
                      AND (
                          entity.protection_scope_id IS NULL
                          OR entity.protection_scope_id != ?
                      )
                      AND NOT EXISTS (
                          SELECT 1
                          FROM protected_sources
                              AS protected
                          WHERE
                              protected.source_id =
                                  source.source_id
                              AND
                              protected.protection_scope_id = ?
                      )
                    LIMIT 1
                    """,
                    (
                        uuid_to_blob(
                            blob_id
                        ),
                        scope_blob,
                        scope_blob,
                    ),
                ).fetchone()
            )

            if (
                outside_live_source
                is not None
            ):
                raise (
                    ProtectedScopeDeletionBlockedError(
                        "Protected ciphertext "
                        "Blob is referenced by "
                        "a live Source outside "
                        "this scope."
                    )
                )

        creating_backup = (
            connection.execute(
                """
                SELECT 1
                FROM backup_snapshots
                WHERE state = 'creating'
                LIMIT 1
                """
            ).fetchone()
        )

        if creating_backup is not None:
            raise (
                ProtectedScopeDeletionBlockedError(
                    "ProtectionScope deletion "
                    "is blocked while a backup "
                    "snapshot is creating."
                )
            )

        for blob in blobs:
            pinned = (
                connection.execute(
                    """
                    SELECT 1
                    FROM backup_snapshot_pins
                    WHERE blob_id = ?
                    LIMIT 1
                    """,
                    (
                        uuid_to_blob(
                            blob.blob_id
                        ),
                    ),
                ).fetchone()
            )

            if pinned is not None:
                raise (
                    ProtectedScopeDeletionBlockedError(
                        "Protected ciphertext "
                        "Blob is pinned by an "
                        "incomplete backup."
                    )
                )

        preview_digest = (
            self._preview_digest(
                protection_scope_id=(
                    protection_scope_id
                ),
                lifecycle_state=(
                    lifecycle_state
                ),
                current_scope_key_id=(
                    current_scope_key_id
                ),
                sources=tuple(
                    sources
                ),
                blobs=tuple(
                    blobs
                ),
                payload_ids=(
                    payload_ids
                ),
                scope_key_ids=(
                    scope_key_ids
                ),
            )
        )

        return _ScopeState(
            protection_scope_id=(
                protection_scope_id
            ),
            lifecycle_state=(
                lifecycle_state
            ),
            current_scope_key_id=(
                current_scope_key_id
            ),
            sources=tuple(
                sources
            ),
            blobs=tuple(
                blobs
            ),
            payload_ids=(
                payload_ids
            ),
            scope_key_ids=(
                scope_key_ids
            ),
            preview_digest=(
                preview_digest
            ),
        )

    def _pending_delete_state(
        self,
        connection: sqlite3.Connection,
        *,
        protection_scope_id: uuid.UUID,
        current_scope_key_id: uuid.UUID | None,
    ) -> _ScopeState:
        """Validate and represent an already crypto-erased scope."""

        scope_blob = uuid_to_blob(
            protection_scope_id
        )

        if current_scope_key_id is not None:
            raise ProtectedScopeDeletionBlockedError(
                "pending_delete ProtectionScope "
                "still has a current Scope Key."
            )

        retained_tables = (
            "protection_scope_keys",
            "protected_payloads",
            "protected_blob_envelopes",
            "protected_sources",
            "source_protection_transitions",
        )

        for table in retained_tables:
            quoted = self._quote_identifier(
                table
            )

            retained = int(
                connection.execute(
                    f"""
                    SELECT COUNT(*)
                    FROM {quoted}
                    WHERE protection_scope_id = ?
                    """,
                    (
                        scope_blob,
                    ),
                ).fetchone()[0]
            )

            if retained != 0:
                raise ProtectedScopeDeletionBlockedError(
                    "pending_delete ProtectionScope "
                    "retains forbidden state: "
                    f"{table}={retained}"
                )

        incomplete_source = connection.execute(
            """
            SELECT source.source_id
            FROM sources AS source
            JOIN entity_registry AS entity
              ON entity.entity_id =
                 source.source_id
            WHERE entity.protection_scope_id = ?
              AND (
                  entity.lifecycle_state
                      != 'deleted'
                  OR source.source_type
                      != 'other'
                  OR source.original_name
                      IS NOT NULL
                  OR source.original_modified_at_us
                      IS NOT NULL
                  OR source.mime_type
                      IS NOT NULL
                  OR source.source_uri
                      IS NOT NULL
              )
            LIMIT 1
            """,
            (
                scope_blob,
            ),
        ).fetchone()

        if incomplete_source is not None:
            raise ProtectedScopeDeletionBlockedError(
                "pending_delete ProtectionScope "
                "contains an incompletely deleted "
                "or unsanitized Source."
            )

        incomplete_blob = connection.execute(
            """
            SELECT blob.blob_id
            FROM blob_records AS blob
            JOIN entity_registry AS entity
              ON entity.entity_id = blob.blob_id
            WHERE entity.protection_scope_id = ?
              AND blob.encryption_state = 'protected_v1'
              AND entity.lifecycle_state != 'deleted'
            LIMIT 1
            """,
            (
                scope_blob,
            ),
        ).fetchone()

        if incomplete_blob is not None:
            raise ProtectedScopeDeletionBlockedError(
                "pending_delete ProtectionScope "
                "contains an active Protected Blob."
            )

        preview_digest = (
            self._preview_digest(
                protection_scope_id=(
                    protection_scope_id
                ),
                lifecycle_state=(
                    "pending_delete"
                ),
                current_scope_key_id=None,
                sources=(),
                blobs=(),
                payload_ids=(),
                scope_key_ids=(),
            )
        )

        return _ScopeState(
            protection_scope_id=(
                protection_scope_id
            ),
            lifecycle_state=(
                "pending_delete"
            ),
            current_scope_key_id=None,
            sources=(),
            blobs=(),
            payload_ids=(),
            scope_key_ids=(),
            preview_digest=(
                preview_digest
            ),
        )

    def _source_reference_blockers(
        self,
        connection: sqlite3.Connection,
        *,
        sources: tuple[
            _ScopeSource,
            ...,
        ],
    ) -> tuple[
        str,
        ...,
    ]:
        if not sources:
            return ()

        source_ids = tuple(
            uuid_to_blob(
                source.source_id
            )
            for source
            in sources
        )

        placeholders = ", ".join(
            "?"
            for _source
            in sources
        )

        tables = tuple(
            str(
                row[
                    "name"
                ]
            )
            for row
            in connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                  AND name NOT LIKE 'sqlite_%'
                ORDER BY name
                """
            ).fetchall()
        )

        blockers: list[
            str
        ] = []

        for table in tables:
            if (
                table
                in self
                ._SOURCE_REFERENCE_ALLOWLIST
            ):
                continue

            quoted = (
                self._quote_identifier(
                    table
                )
            )

            columns = {
                str(
                    row[
                        "name"
                    ]
                )
                for row
                in connection.execute(
                    f"PRAGMA table_info({quoted})"
                ).fetchall()
            }

            if "source_id" not in columns:
                continue

            count = int(
                connection.execute(
                    f"""
                    SELECT COUNT(*)
                    FROM {quoted}
                    WHERE source_id IN (
                        {placeholders}
                    )
                    """,
                    source_ids,
                ).fetchone()[0]
            )

            if count:
                blockers.append(
                    f"{table}.source_id={count}"
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
            raise (
                ProtectedScopeDeletionError(
                    "Unsafe SQLite identifier."
                )
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
    def _preview_digest(
        *,
        protection_scope_id: uuid.UUID,
        lifecycle_state: str,
        current_scope_key_id: uuid.UUID | None,
        sources: tuple[
            _ScopeSource,
            ...,
        ],
        blobs: tuple[
            _ScopeBlob,
            ...,
        ],
        payload_ids: tuple[
            uuid.UUID,
            ...,
        ],
        scope_key_ids: tuple[
            uuid.UUID,
            ...,
        ],
    ) -> str:
        payload = {
            "blobs": [
                {
                    "blob_id": str(
                        blob.blob_id
                    ),
                    "byte_length": (
                        blob.byte_length
                    ),
                    "integrity_sha256": (
                        blob.integrity_sha256
                        .hex()
                    ),
                }
                for blob in blobs
            ],
            "current_scope_key_id": (
                None
                if current_scope_key_id
                is None
                else str(
                    current_scope_key_id
                )
            ),
            "lifecycle_state": (
                lifecycle_state
            ),
            "payload_ids": [
                str(
                    payload_id
                )
                for payload_id
                in payload_ids
            ],
            "protection_scope_id": str(
                protection_scope_id
            ),
            "scope_key_ids": [
                str(
                    scope_key_id
                )
                for scope_key_id
                in scope_key_ids
            ],
            "sources": [
                {
                    "blob_id": str(
                        source.blob_id
                    ),
                    "lifecycle_state": (
                        source.lifecycle_state
                    ),
                    "source_id": str(
                        source.source_id
                    ),
                }
                for source
                in sources
            ],
        }

        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(
                ",",
                ":",
            ),
            allow_nan=False,
        ).encode(
            "utf-8"
        )

        return hashlib.sha256(
            encoded
        ).hexdigest()

    @staticmethod
    def _insert_commit(
        connection: sqlite3.Connection,
        *,
        commit_id: uuid.UUID,
        actor_id: uuid.UUID,
        committed_at_us: int,
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
                committed_at_us,
                uuid_to_blob(
                    actor_id
                ),
                (
                    "lifecycle.delete."
                    "protection_scope"
                ),
                (
                    "explicit user "
                    "ProtectionScope "
                    "crypto-erasure"
                ),
            ),
        )

        if cursor.lastrowid is None:
            raise (
                ProtectedScopeDeletionError(
                    "SQLite did not return "
                    "a ProtectionScope deletion "
                    "commit sequence."
                )
            )

        return int(
            cursor.lastrowid
        )

    @staticmethod
    def _mark_blob_deleted(
        connection: sqlite3.Connection,
        *,
        blob_id: uuid.UUID,
        actor_id: uuid.UUID,
        commit_seq: int,
    ) -> bool:
        """Logically retire a crypto-erased technical Protected Blob."""

        blob = uuid_to_blob(
            blob_id
        )

        row = connection.execute(
            """
            SELECT
                entity_type,
                lifecycle_state,
                protection_scope_id
            FROM entity_registry
            WHERE entity_id = ?
            """,
            (
                blob,
            ),
        ).fetchone()

        if row is None:
            raise ProtectedScopeDeletionError(
                "Protected Blob entity disappeared "
                "during crypto-erasure."
            )

        if str(
            row[
                "entity_type"
            ]
        ) != "blob_record":
            raise ProtectedScopeDeletionError(
                "Protected Blob registry type "
                "is inconsistent."
            )

        if str(
            row[
                "lifecycle_state"
            ]
        ) == "deleted":
            return False

        closed = connection.execute(
            """
            UPDATE entity_state_history
            SET valid_to_commit_seq = ?
            WHERE entity_id = ?
              AND valid_to_commit_seq IS NULL
            """,
            (
                commit_seq,
                blob,
            ),
        )

        if closed.rowcount != 1:
            raise ProtectedScopeDeletionError(
                "Protected Blob has ambiguous "
                "open lifecycle history."
            )

        raw_scope = row[
            "protection_scope_id"
        ]

        connection.execute(
            """
            INSERT INTO entity_state_history (
                entity_id,
                valid_from_commit_seq,
                valid_to_commit_seq,
                lifecycle_state,
                protection_scope_id,
                changed_by_actor_id,
                reason
            ) VALUES (
                ?, ?, NULL, 'deleted',
                ?, ?, ?
            )
            """,
            (
                blob,
                commit_seq,
                (
                    None
                    if raw_scope is None
                    else bytes(
                        raw_scope
                    )
                ),
                uuid_to_blob(
                    actor_id
                ),
                (
                    "explicit ProtectionScope "
                    "Blob crypto-erasure"
                ),
            ),
        )

        updated = connection.execute(
            """
            UPDATE entity_registry
            SET lifecycle_state = 'deleted'
            WHERE entity_id = ?
            """,
            (
                blob,
            ),
        )

        if updated.rowcount != 1:
            raise ProtectedScopeDeletionError(
                "Protected Blob registry "
                "tombstone failed."
            )

        return True

    @staticmethod
    def _mark_source_deleted(
        connection: sqlite3.Connection,
        *,
        source_id: uuid.UUID,
        actor_id: uuid.UUID,
        commit_seq: int,
    ) -> None:
        source_blob = uuid_to_blob(
            source_id
        )

        row = connection.execute(
            """
            SELECT
                lifecycle_state,
                protection_scope_id
            FROM entity_registry
            WHERE entity_id = ?
            """,
            (
                source_blob,
            ),
        ).fetchone()

        if row is None:
            raise (
                ProtectedScopeDeletionError(
                    "Protected Source "
                    "disappeared during deletion."
                )
            )

        if (
            str(
                row[
                    "lifecycle_state"
                ]
            )
            == "deleted"
        ):
            return

        closed = connection.execute(
            """
            UPDATE entity_state_history
            SET valid_to_commit_seq = ?
            WHERE entity_id = ?
              AND valid_to_commit_seq IS NULL
            """,
            (
                commit_seq,
                source_blob,
            ),
        )

        if closed.rowcount != 1:
            raise (
                ProtectedScopeDeletionError(
                    "Protected Source has "
                    "ambiguous open lifecycle "
                    "history."
                )
            )

        raw_scope = row[
            "protection_scope_id"
        ]

        connection.execute(
            """
            INSERT INTO entity_state_history (
                entity_id,
                valid_from_commit_seq,
                valid_to_commit_seq,
                lifecycle_state,
                protection_scope_id,
                changed_by_actor_id,
                reason
            ) VALUES (
                ?, ?, NULL, 'deleted',
                ?, ?, ?
            )
            """,
            (
                source_blob,
                commit_seq,
                (
                    None
                    if raw_scope is None
                    else bytes(
                        raw_scope
                    )
                ),
                uuid_to_blob(
                    actor_id
                ),
                (
                    "explicit ProtectionScope "
                    "deletion"
                ),
            ),
        )

        updated = connection.execute(
            """
            UPDATE entity_registry
            SET lifecycle_state = 'deleted'
            WHERE entity_id = ?
            """,
            (
                source_blob,
            ),
        )

        if updated.rowcount != 1:
            raise (
                ProtectedScopeDeletionError(
                    "Protected Source "
                    "registry deletion failed."
                )
            )

    @staticmethod
    def _advance_archive_watermark(
        connection: sqlite3.Connection,
    ) -> None:
        pending = connection.execute(
            """
            SELECT
                MIN(outbox_seq)
                AS first_pending
            FROM archive_replication_outbox
            WHERE state = 'pending'
            """
        ).fetchone()

        maximum = connection.execute(
            """
            SELECT
                COALESCE(
                    MAX(outbox_seq),
                    0
                ) AS maximum
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
            raise (
                ProtectedScopeDeletionError(
                    "Archive replication "
                    "watermark state is "
                    "incomplete."
                )
            )

        first_pending = pending[
            "first_pending"
        ]

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
            UPDATE
                archive_replication_watermark
            SET
                contiguous_verified_seq = ?,
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
