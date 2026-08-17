"""Ciphertext-only file storage for Protected Raw Archive Sources."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from athena.common.ids import new_uuid7
from athena.security.crypto import CryptoAuthenticationError
from athena.security.models import ProtectedBlobEnvelopeRecord
from athena.security.service import (
    ProtectedContentIntegrityError,
    ProtectedContentService,
)
from athena.source.blob_store import (
    BlobStore,
    PreparedBlob,
    SourceChangedDuringCaptureError,
    SourceFileNotReadableError,
)
from athena.source.models import BlobRecord, SourceType

PROTECTED_BLOB_ENCRYPTION_STATE = "protected_v1"
PROTECTED_BLOB_FORMAT_VERSION = 1
PROTECTED_BLOB_CHUNK_SIZE = 4 * 1024 * 1024
_MAGIC = b"ATHPB01\n"
_FRAME_HEADER_BYTES = 4
_GCM_TAG_BYTES = 16


@dataclass(frozen=True, slots=True)
class ProtectedSourceMetadata:
    source_type: SourceType
    original_name: str
    source_uri: str
    original_modified_at_us: int | None
    mime_type: str | None
    plaintext_byte_length: int

    def to_payload(self) -> bytes:
        return json.dumps(
            {
                "format_version": 1,
                "mime_type": self.mime_type,
                "original_modified_at_us": self.original_modified_at_us,
                "original_name": self.original_name,
                "plaintext_byte_length": self.plaintext_byte_length,
                "source_type": self.source_type.value,
                "source_uri": self.source_uri,
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")

    @classmethod
    def from_payload(cls, payload: bytes) -> "ProtectedSourceMetadata":
        try:
            raw: object = json.loads(payload.decode("ascii"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProtectedContentIntegrityError(
                "Protected Source metadata payload is invalid."
            ) from exc

        if not isinstance(raw, dict):
            raise ProtectedContentIntegrityError(
                "Protected Source metadata payload is invalid."
            )
        data = cast(dict[str, object], raw)
        expected_keys = {
            "format_version",
            "mime_type",
            "original_modified_at_us",
            "original_name",
            "plaintext_byte_length",
            "source_type",
            "source_uri",
        }
        if set(data) != expected_keys or data["format_version"] != 1:
            raise ProtectedContentIntegrityError(
                "Protected Source metadata schema is invalid."
            )

        original_name = data["original_name"]
        source_uri = data["source_uri"]
        mime_type = data["mime_type"]
        modified = data["original_modified_at_us"]
        plaintext_length = data["plaintext_byte_length"]
        source_type_raw = data["source_type"]

        if (
            not isinstance(original_name, str)
            or not original_name
            or not isinstance(source_uri, str)
            or not source_uri
            or (mime_type is not None and not isinstance(mime_type, str))
            or (
                modified is not None
                and (isinstance(modified, bool) or not isinstance(modified, int))
            )
            or isinstance(plaintext_length, bool)
            or not isinstance(plaintext_length, int)
            or plaintext_length < 0
            or not isinstance(source_type_raw, str)
        ):
            raise ProtectedContentIntegrityError(
                "Protected Source metadata values are invalid."
            )

        try:
            source_type = SourceType(source_type_raw)
        except ValueError as exc:
            raise ProtectedContentIntegrityError(
                "Protected Source type is invalid."
            ) from exc

        return cls(
            source_type=source_type,
            original_name=original_name,
            source_uri=source_uri,
            original_modified_at_us=modified,
            mime_type=mime_type,
            plaintext_byte_length=plaintext_length,
        )


@dataclass(frozen=True, slots=True)
class PreparedProtectedBlob:
    blob_id: uuid.UUID
    prepared_blob: PreparedBlob
    envelope: ProtectedBlobEnvelopeRecord
    metadata: ProtectedSourceMetadata


class ProtectedBlobStore:
    """Encrypt/decrypt Protected Source files without plaintext staging."""

    def __init__(
        self,
        *,
        blob_store: BlobStore,
        protected_content: ProtectedContentService,
    ) -> None:
        self.blob_store = blob_store
        self.protected_content = protected_content

    def capture_file(
        self,
        path: Path,
        *,
        protection_scope_id: uuid.UUID,
        source_type: SourceType = SourceType.FILE,
    ) -> PreparedProtectedBlob:
        requested_path = path.expanduser()
        if requested_path.is_symlink():
            raise SourceFileNotReadableError(
                "Protected Source capture does not follow symbolic links."
            )
        source_path = requested_path.resolve()
        try:
            before = source_path.stat()
        except OSError as exc:
            raise SourceFileNotReadableError(
                "Cannot stat Protected Source file."
            ) from exc
        if not source_path.is_file():
            raise SourceFileNotReadableError(
                "Protected Source path is not a regular file."
            )

        blob_id = new_uuid7()
        nonce_prefix = secrets.token_bytes(8)
        dek = bytearray(self.protected_content.crypto.random_key())
        envelope = self.protected_content.wrap_blob_dek(
            protection_scope_id,
            blob_id=blob_id,
            dek=bytes(dek),
            nonce_prefix=nonce_prefix,
            chunk_size=PROTECTED_BLOB_CHUNK_SIZE,
            format_version=PROTECTED_BLOB_FORMAT_VERSION,
        )

        staging_dir = self.blob_store.paths.spool_root / "imports"
        staging_dir.mkdir(parents=True, exist_ok=True)
        staging_path = staging_dir / (
            "protected-" + secrets.token_hex(16) + ".partial"
        )
        digest = hashlib.sha256()
        ciphertext_length = 0
        plaintext_length = 0
        chunk_index = 0

        try:
            try:
                with source_path.open("rb") as source, staging_path.open("xb") as target:
                    target.write(_MAGIC)
                    digest.update(_MAGIC)
                    ciphertext_length += len(_MAGIC)

                    while True:
                        chunk = source.read(PROTECTED_BLOB_CHUNK_SIZE)
                        if not chunk:
                            break
                        if chunk_index > 0xFFFFFFFF:
                            raise ValueError(
                                "Protected Blob exceeds the v1 chunk-index range."
                            )
                        nonce = nonce_prefix + chunk_index.to_bytes(4, "big")
                        encrypted = self.protected_content.crypto.encrypt_with_nonce(
                            bytes(dek),
                            chunk,
                            nonce=nonce,
                            aad=_chunk_aad(
                                blob_id=blob_id,
                                protection_scope_id=protection_scope_id,
                                chunk_index=chunk_index,
                                plaintext_length=len(chunk),
                            ),
                        )
                        frame_header = len(chunk).to_bytes(_FRAME_HEADER_BYTES, "big")
                        target.write(frame_header)
                        target.write(encrypted.ciphertext)
                        digest.update(frame_header)
                        digest.update(encrypted.ciphertext)
                        plaintext_length += len(chunk)
                        ciphertext_length += len(frame_header) + len(encrypted.ciphertext)
                        chunk_index += 1

                    target.flush()
                    os.fsync(target.fileno())
            except OSError as exc:
                raise SourceFileNotReadableError(
                    "Protected Source could not be encrypted into durable staging."
                ) from exc

            try:
                after = source_path.stat()
            except OSError as exc:
                raise SourceChangedDuringCaptureError(
                    "Protected Source became unavailable during capture."
                ) from exc
            if (
                before.st_size != after.st_size
                or before.st_mtime_ns != after.st_mtime_ns
                or before.st_size != plaintext_length
            ):
                raise SourceChangedDuringCaptureError(
                    "Protected Source changed during capture; no Source was committed."
                )

            integrity_sha256 = digest.digest()
            storage_area, storage_locator = self.blob_store.commit_encrypted_staging(
                staging_path,
                integrity_sha256=integrity_sha256,
                byte_length=ciphertext_length,
            )
            exact_media_type = self.blob_store.detect_media_type(source_path)
            metadata = ProtectedSourceMetadata(
                source_type=source_type,
                original_name=source_path.name,
                source_uri=source_path.as_uri(),
                original_modified_at_us=before.st_mtime_ns // 1_000,
                mime_type=exact_media_type,
                plaintext_byte_length=plaintext_length,
            )
            prepared_blob = PreparedBlob(
                byte_length=ciphertext_length,
                media_type="application/octet-stream",
                integrity_sha256=integrity_sha256,
                storage_area=storage_area,
                storage_locator=storage_locator,
                source_modified_at_us=None,
            )
            return PreparedProtectedBlob(
                blob_id=blob_id,
                prepared_blob=prepared_blob,
                envelope=envelope,
                metadata=metadata,
            )
        finally:
            _wipe(dek)
            staging_path.unlink(missing_ok=True)

    def read_bytes(
        self,
        blob: BlobRecord,
        envelope: ProtectedBlobEnvelopeRecord,
    ) -> bytes:
        if (
            blob.encryption_state != PROTECTED_BLOB_ENCRYPTION_STATE
            or envelope.blob_id != blob.blob_id
            or envelope.cipher_suite != "AES-256-GCM"
            or envelope.format_version != PROTECTED_BLOB_FORMAT_VERSION
            or envelope.chunk_size != PROTECTED_BLOB_CHUNK_SIZE
            or len(envelope.nonce_prefix) != 8
        ):
            raise ProtectedContentIntegrityError(
                "Protected Blob storage metadata is inconsistent."
            )

        path = self.blob_store.verify_blob(
            storage_area=blob.storage_area,
            storage_locator=blob.storage_locator,
            expected_sha256=blob.integrity_sha256,
            expected_length=blob.byte_length,
        )
        dek = self.protected_content.unwrap_blob_dek(envelope)
        output = bytearray()
        try:
            try:
                with path.open("rb") as handle:
                    if handle.read(len(_MAGIC)) != _MAGIC:
                        raise ProtectedContentIntegrityError(
                            "Protected Blob format header is invalid."
                        )
                    chunk_index = 0
                    while True:
                        header = handle.read(_FRAME_HEADER_BYTES)
                        if not header:
                            break
                        if len(header) != _FRAME_HEADER_BYTES:
                            raise ProtectedContentIntegrityError(
                                "Protected Blob frame header is truncated."
                            )
                        plaintext_length = int.from_bytes(header, "big")
                        if not 1 <= plaintext_length <= envelope.chunk_size:
                            raise ProtectedContentIntegrityError(
                                "Protected Blob frame length is invalid."
                            )
                        if chunk_index > 0xFFFFFFFF:
                            raise ProtectedContentIntegrityError(
                                "Protected Blob chunk index is invalid."
                            )
                        ciphertext = handle.read(plaintext_length + _GCM_TAG_BYTES)
                        if len(ciphertext) != plaintext_length + _GCM_TAG_BYTES:
                            raise ProtectedContentIntegrityError(
                                "Protected Blob ciphertext frame is truncated."
                            )
                        nonce = envelope.nonce_prefix + chunk_index.to_bytes(4, "big")
                        try:
                            plaintext = self.protected_content.crypto.decrypt(
                                bytes(dek),
                                nonce=nonce,
                                ciphertext=ciphertext,
                                aad=_chunk_aad(
                                    blob_id=blob.blob_id,
                                    protection_scope_id=envelope.protection_scope_id,
                                    chunk_index=chunk_index,
                                    plaintext_length=plaintext_length,
                                ),
                            )
                        except CryptoAuthenticationError as exc:
                            raise ProtectedContentIntegrityError(
                                "Protected Blob authentication failed."
                            ) from exc
                        output.extend(plaintext)
                        chunk_index += 1
            except OSError as exc:
                raise ProtectedContentIntegrityError(
                    "Protected Blob ciphertext could not be read."
                ) from exc
            return bytes(output)
        finally:
            _wipe(dek)
            _wipe(output)


def _chunk_aad(
    *,
    blob_id: uuid.UUID,
    protection_scope_id: uuid.UUID,
    chunk_index: int,
    plaintext_length: int,
) -> bytes:
    return (
        b"ATHENA\x00PROTECTED_BLOB_CHUNK\x00"
        + PROTECTED_BLOB_FORMAT_VERSION.to_bytes(4, "big")
        + blob_id.bytes
        + chunk_index.to_bytes(4, "big")
        + plaintext_length.to_bytes(8, "big")
        + protection_scope_id.bytes
    )


def _wipe(value: bytearray) -> None:
    for index in range(len(value)):
        value[index] = 0
