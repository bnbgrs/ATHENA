"""Deterministic streaming text extraction and immutable representation storage."""

from __future__ import annotations

import codecs
import hashlib
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol

from athena.source.blob_store import BlobIntegrityError, BlobStoreError
from athena.source.models import BlobStorageArea
from athena.storage.durable_fs import durable_mkdir, durable_replace
from athena.storage.paths import RuntimePaths

_COPY_BUFFER_SIZE = 1024 * 1024


class _Digest(Protocol):
    def update(self, data: bytes, /) -> object: ...


class TextRepresentationError(RuntimeError):
    """Base error for deterministic text representation work."""


class UnsupportedTextSourceError(TextRepresentationError):
    """Raised when VS4 Step 2 has no deterministic text profile for a Source."""


class TextDecodingError(TextRepresentationError):
    """Raised when a nominal text Source is not strict UTF-8."""


@dataclass(frozen=True, slots=True)
class PreparedTextRepresentation:
    """Fsynced normalized UTF-8 bytes awaiting immutable final placement."""

    staging_path: Path
    byte_length: int
    content_sha256: bytes


@dataclass(frozen=True, slots=True)
class StoredRepresentationBlob:
    """Physical location of one verified immutable representation payload."""

    byte_length: int
    content_sha256: bytes
    storage_area: BlobStorageArea
    storage_locator: str


class TextRepresentationStore:
    """Build normalized UTF-8 text without loading the whole Source into RAM."""

    def __init__(self, paths: RuntimePaths) -> None:
        self.paths = paths

    def extract(self, source_path: Path) -> PreparedTextRepresentation:
        staging_dir = self.paths.spool_root / "representations" / "staging"
        staging_dir.mkdir(parents=True, exist_ok=True)
        staging_path = staging_dir / f"text-{secrets.token_hex(16)}.partial"

        digest = hashlib.sha256()
        byte_length = 0
        decoder = codecs.getincrementaldecoder("utf-8-sig")(errors="strict")
        pending_cr = False

        try:
            with source_path.open("rb") as source, staging_path.open("xb") as target:
                while True:
                    chunk = source.read(_COPY_BUFFER_SIZE)
                    if not chunk:
                        break
                    try:
                        decoded = decoder.decode(chunk, final=False)
                    except UnicodeDecodeError as exc:
                        raise TextDecodingError(
                            "Text representation requires strict UTF-8 input in VS4 Step 2."
                        ) from exc
                    normalized, pending_cr = _normalize_newlines(decoded, pending_cr)
                    byte_length += _write_text(target, normalized, digest)

                try:
                    decoded = decoder.decode(b"", final=True)
                except UnicodeDecodeError as exc:
                    raise TextDecodingError(
                        "Text representation requires strict UTF-8 input in VS4 Step 2."
                    ) from exc
                normalized, pending_cr = _normalize_newlines(decoded, pending_cr)
                byte_length += _write_text(target, normalized, digest)
                if pending_cr:
                    byte_length += _write_text(target, "\n", digest)

                target.flush()
                os.fsync(target.fileno())
        except OSError as exc:
            staging_path.unlink(missing_ok=True)
            raise TextRepresentationError(
                f"Cannot read or stage Source text from {str(source_path)!r}."
            ) from exc
        except Exception:
            staging_path.unlink(missing_ok=True)
            raise

        return PreparedTextRepresentation(
            staging_path=staging_path,
            byte_length=byte_length,
            content_sha256=digest.digest(),
        )

    def discard(self, prepared: PreparedTextRepresentation) -> None:
        prepared.staging_path.unlink(missing_ok=True)

    def commit(self, prepared: PreparedTextRepresentation) -> StoredRepresentationBlob:
        locator = _representation_locator(prepared.content_sha256)
        archive_root = self.paths.archive_root

        try:
            if archive_root is not None and archive_root.is_dir():
                try:
                    self._copy_into_root(
                        prepared.staging_path,
                        root=archive_root,
                        locator=locator,
                        expected_sha256=prepared.content_sha256,
                        expected_length=prepared.byte_length,
                    )
                    return StoredRepresentationBlob(
                        byte_length=prepared.byte_length,
                        content_sha256=prepared.content_sha256,
                        storage_area=BlobStorageArea.ARCHIVE,
                        storage_locator=locator,
                    )
                except OSError:
                    pass

            try:
                self._copy_into_root(
                    prepared.staging_path,
                    root=self.paths.spool_root,
                    locator=locator,
                    expected_sha256=prepared.content_sha256,
                    expected_length=prepared.byte_length,
                )
            except OSError as exc:
                raise BlobStoreError(
                    "Cannot durably store the generated SourceRepresentation."
                ) from exc
            return StoredRepresentationBlob(
                byte_length=prepared.byte_length,
                content_sha256=prepared.content_sha256,
                storage_area=BlobStorageArea.SPOOL,
                storage_locator=locator,
            )
        finally:
            prepared.staging_path.unlink(missing_ok=True)

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
        durable_mkdir(
            final_path.parent,
            parents=True,
            exist_ok=True,
        )
        if final_path.exists():
            digest, length = _hash_file(final_path)
            if digest != expected_sha256 or length != expected_length:
                raise BlobIntegrityError(
                    f"Existing representation blob is corrupt: {str(final_path)!r}."
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
                    f"Representation changed before finalization: {str(temp_path)!r}."
                )
            durable_replace(
                temp_path,
                final_path,
            )
        finally:
            temp_path.unlink(missing_ok=True)


def _normalize_newlines(text: str, pending_cr: bool) -> tuple[str, bool]:
    if pending_cr:
        text = "\r" + text
        pending_cr = False
    if text.endswith("\r"):
        text = text[:-1]
        pending_cr = True
    return text.replace("\r\n", "\n").replace("\r", "\n"), pending_cr


def _write_text(handle: BinaryIO, text: str, digest: _Digest) -> int:
    if not text:
        return 0
    encoded = text.encode("utf-8")
    handle.write(encoded)
    digest.update(encoded)
    return len(encoded)


def _representation_locator(content_sha256: bytes) -> str:
    value = content_sha256.hex()
    return f"representations/sha256/{value[:2]}/{value[2:4]}/{value}.repr"


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
        raise BlobStoreError(
            f"Cannot read stored representation blob {str(path)!r}."
        ) from exc
    return digest.digest(), byte_length
