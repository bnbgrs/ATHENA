"""Application service for safe Raw Archive source capture."""

from __future__ import annotations

import uuid
from pathlib import Path

from athena.chat.service import ChatService
from athena.common.time import utc_now_us
from athena.lifecycle.runtime_lock import runtime_data_lock
from athena.security.service import (
    ProtectedContentIntegrityError,
    ProtectedContentService,
    ProtectionScopeLockedError,
)
from athena.source.blob_store import (
    ORPHAN_BLOB_SAFETY_HORIZON_US,
    BlobOrphanReconciliationResult,
    BlobStore,
)
from athena.source.models import BlobRecord, SourceCaptureResult, SourceRecord, SourceType
from athena.source.protected_blob import ProtectedBlobStore, ProtectedSourceMetadata
from athena.source.protection_transition import SourceProtectionTransitionService
from athena.source.repository import (
    CaptureTransactionFinalizer,
    ProtectedSourceInvariantError,
    SourceRepository,
)


class ProtectedSourcePersistentPathUnavailableError(RuntimeError):
    """Protected plaintext never has a persistent filesystem path."""


class SourceCaptureService:
    """Coordinate durable blob capture with authoritative Source persistence."""

    def __init__(
        self,
        *,
        repository: SourceRepository,
        blob_store: BlobStore,
        chat: ChatService,
        protected_content: ProtectedContentService,
        protection_transitions: SourceProtectionTransitionService | None = None,
        runtime_lock_root: Path | None = None,
    ) -> None:
        self.repository = repository
        self.blob_store = blob_store
        self.chat = chat
        self.protected_content = protected_content
        self.protection_transitions = protection_transitions
        self.runtime_lock_root = runtime_lock_root
        self.protected_blobs = ProtectedBlobStore(
            blob_store=blob_store,
            protected_content=protected_content,
        )

    def capture_file(self, path: Path) -> SourceCaptureResult:
        with runtime_data_lock(self.runtime_lock_root):
            source_path = path.expanduser()
            prepared_blob = self.blob_store.capture_file(source_path)
            source_path = source_path.resolve()
            existing_blob = self.repository.find_blob_by_integrity(
                integrity_sha256=prepared_blob.integrity_sha256,
                byte_length=prepared_blob.byte_length,
            )
            if existing_blob is not None:
                self.blob_store.verify_blob(
                    storage_area=existing_blob.storage_area,
                    storage_locator=existing_blob.storage_locator,
                    expected_sha256=existing_blob.integrity_sha256,
                    expected_length=existing_blob.byte_length,
                )
            actor_id = self.chat.ensure_local_user()
            return self.repository.capture_file(
                actor_id=actor_id,
                original_name=source_path.name,
                source_uri=source_path.as_uri(),
                prepared_blob=prepared_blob,
            )

    def capture_protected_file(
        self,
        path: Path,
        *,
        protection_scope_id: uuid.UUID,
    ) -> SourceCaptureResult:
        with runtime_data_lock(self.runtime_lock_root):
            prepared = self.protected_blobs.capture_file(
                path,
                protection_scope_id=protection_scope_id,
                source_type=SourceType.FILE,
            )
            metadata_record = self.protected_content.store_payload(
                protection_scope_id,
                prepared.metadata.to_payload(),
            )
            actor_id = self.chat.ensure_local_user()
            return self.repository.capture_protected_file(
                actor_id=actor_id,
                prepared=prepared,
                protected_metadata_payload_id=metadata_record.protected_payload_id,
            )

    def protect_existing_source(
        self,
        source_id: uuid.UUID,
        protection_scope_id: uuid.UUID,
    ) -> SourceCaptureResult:
        if self.protection_transitions is None:
            raise RuntimeError(
                "Source protection transitions are not configured."
            )
        return self.protection_transitions.protect_existing_source(
            source_id,
            protection_scope_id,
        )

    def capture_external_snapshot(
        self,
        path: Path,
        *,
        source_uri: str,
        original_name: str | None = None,
        transactional_finalize: CaptureTransactionFinalizer | None = None,
    ) -> SourceCaptureResult:
        """Capture already-fetched external bytes as immutable web_snapshot Source."""
        with runtime_data_lock(self.runtime_lock_root):
            normalized_uri = source_uri.strip()
            if not normalized_uri:
                raise ValueError("External Source URI must not be empty.")
            source_path = path.expanduser()
            prepared_blob = self.blob_store.capture_file(source_path)
            source_path = source_path.resolve()
            existing_blob = self.repository.find_blob_by_integrity(
                integrity_sha256=prepared_blob.integrity_sha256,
                byte_length=prepared_blob.byte_length,
            )
            if existing_blob is not None:
                self.blob_store.verify_blob(
                    storage_area=existing_blob.storage_area,
                    storage_locator=existing_blob.storage_locator,
                    expected_sha256=existing_blob.integrity_sha256,
                    expected_length=existing_blob.byte_length,
                )
            actor_id = self.chat.ensure_local_user()
            return self.repository.capture_file(
                actor_id=actor_id,
                original_name=original_name or source_path.name,
                source_uri=normalized_uri,
                prepared_blob=prepared_blob,
                source_type=SourceType.WEB_SNAPSHOT,
                transactional_finalize=transactional_finalize,
            )

    def reconcile_orphaned_blobs(
        self,
        *,
        now_us: int | None = None,
        safety_horizon_us: int = ORPHAN_BLOB_SAFETY_HORIZON_US,
    ) -> BlobOrphanReconciliationResult:
        """Recover durable blob publications that never reached SQLite."""
        with runtime_data_lock(self.runtime_lock_root):
            referenced_locators = (
                self.repository.list_blob_storage_locators()
            )
            return self.blob_store.reconcile_orphaned_blobs(
                referenced_locators=referenced_locators,
                now_us=(
                    utc_now_us()
                    if now_us is None
                    else now_us
                ),
                safety_horizon_us=safety_horizon_us,
            )

    def get(self, source_id: uuid.UUID) -> tuple[SourceRecord, BlobRecord]:
        return self.repository.get(source_id)

    def list(
        self,
        *,
        limit: int = 50,
    ) -> tuple[tuple[SourceRecord, BlobRecord], ...]:
        return self.repository.list(limit=limit)

    def load_protected_metadata(
        self,
        source_id: uuid.UUID,
    ) -> ProtectedSourceMetadata:
        source, _blob = self.repository.get(source_id)
        scope_id = source.protection_scope_id
        payload_id = source.protected_metadata_payload_id
        if scope_id is None or payload_id is None:
            raise ProtectedSourceInvariantError("Source is not protected.")
        payload = self.protected_content.load_payload(payload_id)
        metadata = ProtectedSourceMetadata.from_payload(payload)
        if metadata.source_type is not source.source_type:
            raise ProtectedContentIntegrityError(
                "Protected Source type metadata disagrees with its public row."
            )
        return metadata

    def read_protected_bytes(self, source_id: uuid.UUID) -> bytes:
        source, blob = self.repository.get(source_id)
        scope_id = source.protection_scope_id
        if scope_id is None:
            raise ProtectedSourceInvariantError("Source is not protected.")
        if source.content_sha256 != blob.integrity_sha256:
            raise ProtectedContentIntegrityError(
                "Protected Source ciphertext hash disagrees with its BlobRecord."
            )
        metadata = self.load_protected_metadata(source_id)
        envelope = self.repository.get_protected_blob_envelope(blob.blob_id)
        if envelope.protection_scope_id != scope_id:
            raise ProtectedContentIntegrityError(
                "Protected Source and Blob envelope belong to different scopes."
            )
        plaintext = self.protected_blobs.read_bytes(blob, envelope)
        if len(plaintext) != metadata.plaintext_byte_length:
            raise ProtectedContentIntegrityError(
                "Protected Source plaintext length does not match authenticated metadata."
            )
        return plaintext

    def verify(self, source_id: uuid.UUID) -> Path:
        source, blob = self.repository.get(source_id)
        if source.protection_scope_id is not None:
            if not self.protected_content.is_unlocked(source.protection_scope_id):
                raise ProtectionScopeLockedError("ProtectionScope is locked.")
            raise ProtectedSourcePersistentPathUnavailableError(
                "Protected Source plaintext has no persistent path; "
                "use read_protected_bytes()."
            )
        return self.blob_store.verify_blob(
            storage_area=blob.storage_area,
            storage_locator=blob.storage_locator,
            expected_sha256=blob.integrity_sha256,
            expected_length=blob.byte_length,
        )
