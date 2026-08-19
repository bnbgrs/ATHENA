"""Streaming immutable blob capture for the Raw Archive."""

from __future__ import annotations

import hashlib
import mimetypes
import os
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from athena.source.models import BlobStorageArea
from athena.storage.durable_fs import durable_mkdir, durable_replace
from athena.storage.paths import RuntimePaths

_COPY_BUFFER_SIZE = 1024 * 1024
ORPHAN_BLOB_SAFETY_HORIZON_US = 24 * 60 * 60 * 1_000_000
_HEX_DIGITS = frozenset("0123456789abcdef")


class BlobStoreError(RuntimeError):
    """Base error for physical Raw Archive blob capture."""


class SourceFileNotReadableError(BlobStoreError):
    """Raised when a requested source path cannot be safely read."""


class SourceChangedDuringCaptureError(BlobStoreError):
    """Raised when the source changes while ATHENA is copying it."""


class BlobIntegrityError(BlobStoreError):
    """Raised when stored bytes do not match the expected integrity hash."""


class ArchiveStorageUnavailableError(BlobStoreError):
    """Raised when the configured long-term Archive Root is unavailable."""


@dataclass(frozen=True, slots=True)
class PreparedBlob:
    byte_length: int
    media_type: str | None
    integrity_sha256: bytes
    storage_area: BlobStorageArea
    storage_locator: str
    source_modified_at_us: int | None


@dataclass(frozen=True, slots=True)
class BlobOrphanReconciliationResult:
    scanned_blob_count: int
    referenced_blob_count: int
    recent_unreferenced_count: int
    deleted_orphan_count: int
    unsafe_candidate_count: int
    archive_root_unavailable: bool


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

    def detect_media_type(
        self,
        path: Path,
    ) -> str | None:
        return _detect_media_type(path)

    def commit_encrypted_staging(
        self,
        staging_path: Path,
        *,
        integrity_sha256: bytes,
        byte_length: int,
    ) -> tuple[BlobStorageArea, str]:
        if not staging_path.is_file():
            raise BlobStoreError(
                "Protected Blob ciphertext staging file is missing."
            )
        return self._commit_staged_blob(
            staging_path,
            integrity_sha256=integrity_sha256,
            byte_length=byte_length,
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
        progress_callback: Callable[[], None] | None = None,
    ) -> Path:
        path = self.resolve_blob_path(
            storage_area=storage_area,
            storage_locator=storage_locator,
        )

        digest, byte_length = _hash_file(
            path,
            progress_callback=progress_callback,
        )

        if (
            byte_length != expected_length
            or digest != expected_sha256
        ):
            raise BlobIntegrityError(
                "Raw Archive blob integrity verification "
                f"failed for {str(path)!r}."
            )

        return path


    def replicate_spool_blob_to_archive(
        self,
        *,
        storage_locator: str,
        expected_sha256: bytes,
        expected_length: int,
        progress_callback: Callable[[], None] | None = None,
    ) -> Path:
        """Copy one verified spool blob to the configured Archive Root."""
        archive_root = self.paths.archive_root

        if archive_root is None:
            raise ArchiveStorageUnavailableError(
                "No archive_root is configured."
            )

        if not archive_root.is_dir():
            raise ArchiveStorageUnavailableError(
                "Configured archive_root is unavailable."
            )

        source_path = self.verify_blob(
            storage_area=BlobStorageArea.SPOOL,
            storage_locator=storage_locator,
            expected_sha256=expected_sha256,
            expected_length=expected_length,
            progress_callback=progress_callback,
        )

        try:
            self._copy_into_root(
                source_path,
                root=archive_root,
                locator=storage_locator,
                expected_sha256=expected_sha256,
                expected_length=expected_length,
                progress_callback=progress_callback,
            )
        except BlobIntegrityError:
            raise
        except (BlobStoreError, OSError) as exc:
            raise ArchiveStorageUnavailableError(
                "Archive Root became unavailable "
                "during replication."
            ) from exc

        target_path = (
            archive_root
            / Path(storage_locator)
        )

        try:
            digest, length = _hash_file(
                target_path,
                progress_callback=progress_callback,
            )
        except BlobStoreError as exc:
            raise ArchiveStorageUnavailableError(
                "Replicated Archive blob cannot "
                "be read back."
            ) from exc

        if (
            digest != expected_sha256
            or length != expected_length
        ):
            raise BlobIntegrityError(
                "Replicated Archive blob failed "
                "target verification."
            )

        return target_path

    def cleanup_verified_spool_replica(
        self,
        *,
        storage_locator: str,
        expected_sha256: bytes,
        expected_length: int,
        progress_callback: Callable[[], None] | None = None,
    ) -> bool:
        """Delete transfer-only spool bytes only after Archive verification."""
        spool_path = self.resolve_blob_path(
            storage_area=BlobStorageArea.SPOOL,
            storage_locator=storage_locator,
        )

        # Normal verified rows have already been cleaned. Do not re-hash
        # long-term storage when there is no transfer-only local duplicate.
        if not spool_path.exists():
            return False

        archive_path = self.verify_blob(
            storage_area=BlobStorageArea.ARCHIVE,
            storage_locator=storage_locator,
            expected_sha256=expected_sha256,
            expected_length=expected_length,
            progress_callback=progress_callback,
        )

        if (
            archive_path.resolve()
            == spool_path.resolve()
        ):
            raise BlobStoreError(
                "Archive Root and Durable Spool resolve to "
                "the same physical blob path."
            )

        digest, length = _hash_file(
            spool_path,
            progress_callback=progress_callback,
        )

        if (
            digest != expected_sha256
            or length != expected_length
        ):
            raise BlobIntegrityError(
                "Transfer-only spool replica failed integrity "
                "verification before cleanup."
            )

        try:
            spool_path.unlink()
        except OSError as exc:
            raise BlobStoreError(
                "Verified transfer-only spool replica "
                "could not be removed."
            ) from exc

        if progress_callback is not None:
            progress_callback()

        return True

    def verified_replica_paths(
        self,
        *,
        storage_locator: str,
        expected_sha256: bytes,
        expected_length: int,
    ) -> tuple[Path, ...]:
        """Return every verified Raw Archive replica of one content object."""

        relative = Path(
            storage_locator
        )

        if (
            relative.is_absolute()
            or ".." in relative.parts
        ):
            raise BlobStoreError(
                "Stored blob locator is not a safe relative path."
            )

        roots: list[
            Path
        ] = [
            self.paths.spool_root,
        ]

        archive_root = (
            self.paths.archive_root
        )

        if archive_root is not None:
            if (
                archive_root.is_symlink()
                or not archive_root.is_dir()
            ):
                raise ArchiveStorageUnavailableError(
                    "Configured Archive Root is unavailable; "
                    "physical deletion cannot prove that all "
                    "Raw Archive replicas are gone."
                )

            roots.append(
                archive_root
            )

        verified: list[
            Path
        ] = []

        seen: set[
            Path
        ] = set()

        for root in roots:
            if (
                root.is_symlink()
                or not root.is_dir()
            ):
                raise BlobStoreError(
                    "Blob storage root is unavailable "
                    "or is a symbolic link."
                )

            resolved_root = (
                root.resolve()
            )

            candidate = (
                root
                / relative
            )

            if candidate.is_symlink():
                raise BlobStoreError(
                    "Refusing to inspect a symbolic-link "
                    "Raw Archive blob."
                )

            resolved_candidate = (
                candidate.resolve(
                    strict=False
                )
            )

            if (
                resolved_candidate
                != resolved_root
                and resolved_root
                not in resolved_candidate.parents
            ):
                raise BlobStoreError(
                    "Raw Archive blob resolves outside "
                    "its configured storage root."
                )

            if (
                resolved_candidate
                in seen
            ):
                continue

            seen.add(
                resolved_candidate
            )

            if not candidate.exists():
                continue

            if not candidate.is_file():
                raise BlobStoreError(
                    "Raw Archive blob path is not "
                    "a regular file."
                )

            digest, length = (
                _hash_file(
                    candidate
                )
            )

            if (
                digest
                != expected_sha256
                or length
                != expected_length
            ):
                raise BlobIntegrityError(
                    "Raw Archive replica failed "
                    "integrity verification before purge."
                )

            verified.append(
                candidate
            )

        return tuple(
            verified
        )


    def reconcile_orphaned_blobs(
        self,
        *,
        referenced_locators: frozenset[str],
        now_us: int,
        safety_horizon_us: int = ORPHAN_BLOB_SAFETY_HORIZON_US,
    ) -> BlobOrphanReconciliationResult:
        """Remove old unreferenced content-addressed blobs conservatively."""
        if safety_horizon_us < 0:
            raise ValueError(
                "Blob orphan safety horizon must not be negative."
            )

        spool_root = self.paths.spool_root
        if (
            spool_root.is_symlink()
            or not spool_root.is_dir()
        ):
            raise BlobStoreError(
                "Durable Spool is unavailable for blob reconciliation."
            )

        roots: list[Path] = [spool_root]
        archive_root_unavailable = False

        archive_root = self.paths.archive_root
        if archive_root is not None:
            if (
                archive_root.is_symlink()
                or not archive_root.is_dir()
            ):
                archive_root_unavailable = True
            else:
                roots.append(archive_root)

        cutoff_ns = max(
            0,
            now_us - safety_horizon_us,
        ) * 1_000

        scanned = 0
        referenced = 0
        recent = 0
        deleted = 0
        unsafe = 0
        seen_roots: set[Path] = set()

        for root in roots:
            resolved_root = root.resolve()
            if resolved_root in seen_roots:
                continue
            seen_roots.add(resolved_root)

            candidates, unsafe_directories = (
                _content_addressed_blob_candidates(root)
            )
            unsafe += unsafe_directories

            for candidate in candidates:
                scanned += 1

                if (
                    candidate.is_symlink()
                    or not candidate.is_file()
                ):
                    unsafe += 1
                    continue

                try:
                    relative = (
                        candidate
                        .relative_to(root)
                        .as_posix()
                    )
                except ValueError:
                    unsafe += 1
                    continue

                digest_hex = candidate.name.removesuffix(
                    ".blob"
                )

                if (
                    len(digest_hex) != 64
                    or any(
                        character not in _HEX_DIGITS
                        for character in digest_hex
                    )
                ):
                    unsafe += 1
                    continue

                expected_digest = bytes.fromhex(
                    digest_hex
                )
                expected_locator = _blob_locator(
                    expected_digest
                )

                if relative != expected_locator:
                    unsafe += 1
                    continue

                if relative in referenced_locators:
                    referenced += 1
                    continue

                try:
                    stat = candidate.stat()
                except OSError:
                    unsafe += 1
                    continue

                if stat.st_mtime_ns > cutoff_ns:
                    recent += 1
                    continue

                try:
                    actual_digest, _length = (
                        _hash_file(candidate)
                    )
                except BlobStoreError:
                    unsafe += 1
                    continue

                if actual_digest != expected_digest:
                    unsafe += 1
                    continue

                if (
                    candidate.is_symlink()
                    or not candidate.is_file()
                ):
                    unsafe += 1
                    continue

                try:
                    candidate.unlink()
                except OSError:
                    unsafe += 1
                    continue

                if (
                    candidate.exists()
                    or candidate.is_symlink()
                ):
                    unsafe += 1
                    continue

                deleted += 1

        return BlobOrphanReconciliationResult(
            scanned_blob_count=scanned,
            referenced_blob_count=referenced,
            recent_unreferenced_count=recent,
            deleted_orphan_count=deleted,
            unsafe_candidate_count=unsafe,
            archive_root_unavailable=archive_root_unavailable,
        )

    def purge_verified_replicas(
        self,
        *,
        storage_locator: str,
        expected_sha256: bytes,
        expected_length: int,
    ) -> tuple[Path, ...]:
        """Delete all verified spool/archive replicas of one Raw Archive blob."""

        paths = (
            self.verified_replica_paths(
                storage_locator=storage_locator,
                expected_sha256=expected_sha256,
                expected_length=expected_length,
            )
        )

        deleted: list[
            Path
        ] = []

        for path in paths:
            # Re-verify immediately before unlink. The shared
            # runtime mutation lock prevents ATHENA writers,
            # while this catches out-of-band filesystem changes.
            digest, length = (
                _hash_file(
                    path
                )
            )

            if (
                digest
                != expected_sha256
                or length
                != expected_length
            ):
                raise BlobIntegrityError(
                    "Raw Archive replica changed "
                    "between purge verification and unlink."
                )

            try:
                path.unlink()

            except OSError as exc:
                raise BlobStoreError(
                    "Verified Raw Archive replica "
                    "could not be removed."
                ) from exc

            if (
                path.exists()
                or path.is_symlink()
            ):
                raise BlobStoreError(
                    "Raw Archive replica still exists "
                    "after physical deletion."
                )

            deleted.append(
                path
            )

        return tuple(
            deleted
        )

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
        progress_callback: Callable[[], None] | None = None,
    ) -> None:
        final_path = (
            root
            / Path(locator)
        )

        durable_mkdir(
            final_path.parent,
            parents=True,
            exist_ok=True,
        )

        if final_path.exists():
            digest, length = _hash_file(
                final_path,
                progress_callback=progress_callback,
            )

            if (
                digest != expected_sha256
                or length != expected_length
            ):
                raise BlobIntegrityError(
                    "Existing content-addressed blob "
                    f"is corrupt: {str(final_path)!r}."
                )

            return

        temp_path = final_path.with_name(
            f".{final_path.name}."
            f"{secrets.token_hex(8)}.partial"
        )

        try:
            with (
                staging_path.open("rb") as source,
                temp_path.open("xb") as target,
            ):
                while True:
                    chunk = source.read(
                        _COPY_BUFFER_SIZE
                    )

                    if not chunk:
                        break

                    target.write(
                        chunk
                    )

                    if progress_callback is not None:
                        progress_callback()

                target.flush()
                os.fsync(
                    target.fileno()
                )

            digest, length = _hash_file(
                temp_path,
                progress_callback=progress_callback,
            )

            if (
                digest != expected_sha256
                or length != expected_length
            ):
                raise BlobIntegrityError(
                    "Blob changed before finalization: "
                    f"{str(temp_path)!r}."
                )

            durable_replace(
                temp_path,
                final_path,
            )

            if progress_callback is not None:
                progress_callback()

        finally:
            temp_path.unlink(
                missing_ok=True
            )




def _content_addressed_blob_candidates(
    root: Path,
) -> tuple[tuple[Path, ...], int]:
    """Return exact blob-layout candidates without following symlink dirs."""
    sha_root = root / "blobs" / "sha256"

    if not sha_root.exists():
        return (), 0

    if (
        sha_root.is_symlink()
        or not sha_root.is_dir()
    ):
        return (), 1

    candidates: list[Path] = []
    unsafe = 0

    try:
        first_level = tuple(sha_root.iterdir())
    except OSError:
        return (), 1

    for first in first_level:
        if (
            len(first.name) != 2
            or any(
                character not in _HEX_DIGITS
                for character in first.name
            )
        ):
            continue

        if (
            first.is_symlink()
            or not first.is_dir()
        ):
            unsafe += 1
            continue

        try:
            second_level = tuple(first.iterdir())
        except OSError:
            unsafe += 1
            continue

        for second in second_level:
            if (
                len(second.name) != 2
                or any(
                    character not in _HEX_DIGITS
                    for character in second.name
                )
            ):
                continue

            if (
                second.is_symlink()
                or not second.is_dir()
            ):
                unsafe += 1
                continue

            try:
                leaves = tuple(second.iterdir())
            except OSError:
                unsafe += 1
                continue

            for leaf in leaves:
                if leaf.name.endswith(".blob"):
                    candidates.append(leaf)

    return tuple(candidates), unsafe


def _blob_locator(integrity_sha256: bytes) -> str:
    value = integrity_sha256.hex()
    return f"blobs/sha256/{value[:2]}/{value[2:4]}/{value}.blob"


def _hash_file(
    path: Path,
    *,
    progress_callback: Callable[[], None] | None = None,
) -> tuple[bytes, int]:
    digest = hashlib.sha256()
    byte_length = 0

    try:
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(
                    _COPY_BUFFER_SIZE
                )

                if not chunk:
                    break

                digest.update(
                    chunk
                )
                byte_length += len(
                    chunk
                )

                if progress_callback is not None:
                    progress_callback()

    except OSError as exc:
        raise BlobStoreError(
            "Cannot read stored Raw Archive blob "
            f"{str(path)!r}."
        ) from exc

    return (
        digest.digest(),
        byte_length,
    )


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
            if signature == b"PK\x03\x04" and path.suffix.lower() == ".docx":
                return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
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
