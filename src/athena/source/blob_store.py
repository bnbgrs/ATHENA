"""Streaming immutable blob capture for the Raw Archive."""

from __future__ import annotations

import hashlib
import mimetypes
import os
import secrets
from dataclasses import dataclass
from pathlib import Path

from athena.source.models import BlobStorageArea
from athena.storage.paths import RuntimePaths

_COPY_BUFFER_SIZE = 1024 * 1024


class BlobStoreError(RuntimeError):
    """Base error for physical Raw Archive blob capture."""


class SourceFileNotReadableError(BlobStoreError):
    """Raised when a requested source path cannot be safely read."""


class SourceChangedDuringCaptureError(BlobStoreError):
    """Raised when the source changes while ATHENA is copying it."""


class BlobIntegrityError(BlobStoreError):
    """Raised when stored bytes do not match the expected integrity hash."""


@dataclass(frozen=True, slots=True)
class PreparedBlob:
    byte_length: int
    media_type: str | None
    integrity_sha256: bytes
    storage_area: BlobStorageArea
    storage_locator: str
    source_modified_at_us: int | None


class BlobStore:
    """Capture unprotected original bytes before any semantic processing.

    Input is streamed through the durable local spool while SHA-256 is computed.
    A configured reachable archive root is preferred for the final immutable
    location; otherwise the verified local spool remains the durable location.
    """

    def __init__(self, paths: RuntimePaths) -> None:
        self.paths = paths

    def capture_file(self, path: Path) -> PreparedBlob:
        requested_path = path.expanduser()
        if requested_path.is_symlink():
            raise SourceFileNotReadableError(
                "VS4 Step 1 does not follow symbolic-link source paths; import the target path directly."
            )
        source_path = requested_path.resolve()
        try:
            before = source_path.stat()
        except OSError as exc:
            raise SourceFileNotReadableError(
                f"Cannot stat source file {str(source_path)!r}."
            ) from exc
        if not source_path.is_file():
            raise SourceFileNotReadableError(
                f"Source path is not a regular file: {str(source_path)!r}."
            )

        staging_dir = self.paths.spool_root / "imports"
        staging_dir.mkdir(parents=True, exist_ok=True)
        staging_path = staging_dir / f"capture-{secrets.token_hex(16)}.partial"

        digest = hashlib.sha256()
        byte_length = 0
        try:
            with source_path.open("rb") as source, staging_path.open("xb") as target:
                while True:
                    chunk = source.read(_COPY_BUFFER_SIZE)
                    if not chunk:
                        break
                    target.write(chunk)
                    digest.update(chunk)
                    byte_length += len(chunk)
                target.flush()
                os.fsync(target.fileno())

            try:
                after = source_path.stat()
            except OSError as exc:
                raise SourceChangedDuringCaptureError(
                    "Source became unavailable while it was being captured."
                ) from exc

            if (
                before.st_size != after.st_size
                or before.st_mtime_ns != after.st_mtime_ns
                or before.st_size != byte_length
            ):
                raise SourceChangedDuringCaptureError(
                    "Source changed while ATHENA was capturing it; no Source was committed."
                )

            integrity_sha256 = digest.digest()
            storage_area, storage_locator = self._commit_staged_blob(
                staging_path,
                integrity_sha256=integrity_sha256,
                byte_length=byte_length,
            )
        finally:
            staging_path.unlink(missing_ok=True)

        media_type = _detect_media_type(source_path)
        modified_at_us = before.st_mtime_ns // 1_000
        return PreparedBlob(
            byte_length=byte_length,
            media_type=media_type,
            integrity_sha256=integrity_sha256,
            storage_area=storage_area,
            storage_locator=storage_locator,
            source_modified_at_us=modified_at_us,
        )

    def resolve_blob_path(self, *, storage_area: BlobStorageArea, storage_locator: str) -> Path:
        relative = Path(storage_locator)
        if relative.is_absolute() or ".." in relative.parts:
            raise BlobStoreError("Stored blob locator is not a safe relative path.")
        if storage_area is BlobStorageArea.ARCHIVE:
            if self.paths.archive_root is None:
                raise BlobStoreError("Blob references archive storage but no archive_root is configured.")
            return self.paths.archive_root / relative
        return self.paths.spool_root / relative

    def verify_blob(
        self,
        *,
        storage_area: BlobStorageArea,
        storage_locator: str,
        expected_sha256: bytes,
        expected_length: int,
    ) -> Path:
        path = self.resolve_blob_path(
            storage_area=storage_area,
            storage_locator=storage_locator,
        )
        digest, byte_length = _hash_file(path)
        if byte_length != expected_length or digest != expected_sha256:
            raise BlobIntegrityError(
                f"Raw Archive blob integrity verification failed for {str(path)!r}."
            )
        return path

    def _commit_staged_blob(
        self,
        staging_path: Path,
        *,
        integrity_sha256: bytes,
        byte_length: int,
    ) -> tuple[BlobStorageArea, str]:
        locator = _blob_locator(integrity_sha256)

        archive_root = self.paths.archive_root
        if archive_root is not None and archive_root.is_dir():
            try:
                self._copy_into_root(
                    staging_path,
                    root=archive_root,
                    locator=locator,
                    expected_sha256=integrity_sha256,
                    expected_length=byte_length,
                )
                return BlobStorageArea.ARCHIVE, locator
            except OSError:
                # Archive/NAS availability is not allowed to lose an intake. The
                # already-fsynced local staging copy falls back to Durable Spool.
                pass

        self._copy_into_root(
            staging_path,
            root=self.paths.spool_root,
            locator=locator,
            expected_sha256=integrity_sha256,
            expected_length=byte_length,
        )
        return BlobStorageArea.SPOOL, locator

    @staticmethod
    def _copy_into_root(
        staging_path: Path,
        *,
        root: Path,
        locator: str,
        expected_sha256: bytes,
        expected_length: int,
    ) -> None:
        final_path = root / Path(locator)
        final_path.parent.mkdir(parents=True, exist_ok=True)

        if final_path.exists():
            digest, length = _hash_file(final_path)
            if digest != expected_sha256 or length != expected_length:
                raise BlobIntegrityError(
                    f"Existing content-addressed blob is corrupt: {str(final_path)!r}."
                )
            return

        temp_path = final_path.with_name(
            f".{final_path.name}.{secrets.token_hex(8)}.partial"
        )
        try:
            with staging_path.open("rb") as source, temp_path.open("xb") as target:
                while True:
                    chunk = source.read(_COPY_BUFFER_SIZE)
                    if not chunk:
                        break
                    target.write(chunk)
                target.flush()
                os.fsync(target.fileno())

            digest, length = _hash_file(temp_path)
            if digest != expected_sha256 or length != expected_length:
                raise BlobIntegrityError(
                    f"Blob changed before finalization: {str(temp_path)!r}."
                )
            os.replace(temp_path, final_path)
        finally:
            temp_path.unlink(missing_ok=True)


def _blob_locator(integrity_sha256: bytes) -> str:
    value = integrity_sha256.hex()
    return f"blobs/sha256/{value[:2]}/{value[2:4]}/{value}.blob"


def _hash_file(path: Path) -> tuple[bytes, int]:
    digest = hashlib.sha256()
    byte_length = 0
    try:
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(_COPY_BUFFER_SIZE)
                if not chunk:
                    break
                digest.update(chunk)
                byte_length += len(chunk)
    except OSError as exc:
        raise BlobStoreError(f"Cannot read stored Raw Archive blob {str(path)!r}.") from exc
    return digest.digest(), byte_length


def _detect_media_type(path: Path) -> str | None:
    try:
        with path.open("rb") as handle:
            prefix = handle.read(16)
    except OSError:
        return None

    signatures: tuple[tuple[bytes, str], ...] = (
        (b"%PDF-", "application/pdf"),
        (b"\x89PNG\r\n\x1a\n", "image/png"),
        (b"\xff\xd8\xff", "image/jpeg"),
        (b"GIF87a", "image/gif"),
        (b"GIF89a", "image/gif"),
        (b"PK\x03\x04", "application/zip"),
    )
    for signature, media_type in signatures:
        if prefix.startswith(signature):
            return media_type

    guessed, _ = mimetypes.guess_type(path.name, strict=False)
    if guessed is not None:
        return guessed

    if b"\x00" not in prefix:
        try:
            prefix.decode("utf-8")
        except UnicodeDecodeError:
            pass
        else:
            return "text/plain"
    return "application/octet-stream"
