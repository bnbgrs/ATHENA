"""Deterministic native-text extraction for paginated PDF Sources."""

from __future__ import annotations

import hashlib
import os
import secrets
from collections.abc import Iterator
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from athena.source.representation_store import (
    PreparedTextRepresentation,
    StoredRepresentationBlob,
    TextRepresentationStore,
)
from athena.storage.paths import RuntimePaths

_PAGE_SEPARATOR = "\n\n"


class PdfRepresentationError(RuntimeError):
    """Base error for native PDF text representation work."""


class UnsupportedPdfSourceError(PdfRepresentationError):
    """Raised when the Source is not a PDF suitable for this parser."""


class EncryptedPdfUnsupportedError(PdfRepresentationError):
    """Raised because VS6 Step 1 does not accept encrypted PDFs."""


class PdfNativeTextUnavailableError(PdfRepresentationError):
    """Raised when a PDF contains no extractable native text."""


@dataclass(frozen=True, slots=True)
class PdfPageSpan:
    page_number: int
    start_offset: int
    end_offset: int
    content_sha256: bytes


@dataclass(frozen=True, slots=True)
class PreparedPdfTextRepresentation:
    staging_path: Path
    byte_length: int
    content_sha256: bytes
    pages: tuple[PdfPageSpan, ...]


class PdfNativeTextRepresentationStore:
    """Extract page-ordered native PDF text to immutable UTF-8 representation bytes.

    Text is written incrementally page by page. ATHENA stores code-point offsets for
    each page alongside the retained representation so durable anchors can later be
    resolved back to PDF page numbers without depending on transient SourceChunks.
    """

    def __init__(self, paths: RuntimePaths) -> None:
        self.paths = paths
        self._text_store = TextRepresentationStore(paths)

    def extract(
        self,
        source_path: Path,
    ) -> PreparedPdfTextRepresentation:
        staging_dir = (
            self.paths.spool_root
            / "representations"
            / "staging"
        )
        staging_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        staging_path = (
            staging_dir
            / f"pdf-text-{secrets.token_hex(16)}.partial"
        )

        digest = hashlib.sha256()
        byte_length = 0
        char_offset = 0
        page_spans: list[
            PdfPageSpan
        ] = []
        saw_native_text = False

        try:
            reader = _pdf_reader_from_path(
                source_path
            )

            page_count = len(
                reader.pages
            )

            with staging_path.open(
                "xb"
            ) as target:

                for (
                    page_number,
                    normalized,
                ) in _iter_pdf_text_pages(
                    reader
                ):
                    start_offset = char_offset

                    if normalized:
                        saw_native_text = (
                            saw_native_text
                            or bool(
                                normalized.strip()
                            )
                        )

                        encoded = normalized.encode(
                            "utf-8"
                        )

                        target.write(
                            encoded
                        )
                        digest.update(
                            encoded
                        )

                        byte_length += len(
                            encoded
                        )
                        char_offset += len(
                            normalized
                        )

                    end_offset = char_offset

                    page_spans.append(
                        PdfPageSpan(
                            page_number=page_number,
                            start_offset=start_offset,
                            end_offset=end_offset,
                            content_sha256=(
                                hashlib.sha256(
                                    normalized.encode(
                                        "utf-8"
                                    )
                                ).digest()
                            ),
                        )
                    )

                    if page_number < page_count:
                        separator = (
                            _PAGE_SEPARATOR.encode(
                                "utf-8"
                            )
                        )

                        target.write(
                            separator
                        )
                        digest.update(
                            separator
                        )

                        byte_length += len(
                            separator
                        )
                        char_offset += len(
                            _PAGE_SEPARATOR
                        )

                target.flush()
                os.fsync(
                    target.fileno()
                )

        except Exception:
            staging_path.unlink(
                missing_ok=True
            )
            raise

        if not saw_native_text:
            staging_path.unlink(
                missing_ok=True
            )

            raise PdfNativeTextUnavailableError(
                "PDF has no usable native text. "
                "OCR fallback is intentionally "
                "deferred beyond VS6 Step 1."
            )

        return PreparedPdfTextRepresentation(
            staging_path=staging_path,
            byte_length=byte_length,
            content_sha256=digest.digest(),
            pages=tuple(
                page_spans
            ),
        )


    def discard(self, prepared: PreparedPdfTextRepresentation) -> None:
        prepared.staging_path.unlink(missing_ok=True)

    def commit(self, prepared: PreparedPdfTextRepresentation) -> StoredRepresentationBlob:
        base = PreparedTextRepresentation(
            staging_path=prepared.staging_path,
            byte_length=prepared.byte_length,
            content_sha256=prepared.content_sha256,
        )
        return self._text_store.commit(base)


def extract_pdf_text_bytes(
    payload: bytes,
) -> str:
    """Extract native PDF text directly from plaintext bytes in memory."""

    with BytesIO(
        payload
    ) as stream:

        try:
            reader = PdfReader(
                stream,
                strict=True,
            )

        except (
            PdfReadError,
            OSError,
            ValueError,
        ) as exc:
            raise PdfRepresentationError(
                "Cannot parse PDF source bytes."
            ) from exc

        parts: list[str] = []
        saw_native_text = False
        page_count = len(
            reader.pages
        )

        for (
            page_number,
            normalized,
        ) in _iter_pdf_text_pages(
            reader
        ):
            if normalized:
                saw_native_text = (
                    saw_native_text
                    or bool(
                        normalized.strip()
                    )
                )

                parts.append(
                    normalized
                )

            if page_number < page_count:
                parts.append(
                    _PAGE_SEPARATOR
                )

    if not saw_native_text:
        raise PdfNativeTextUnavailableError(
            "PDF has no usable native text. "
            "OCR fallback is intentionally "
            "deferred beyond VS6 Step 1."
        )

    return "".join(
        parts
    )


def _pdf_reader_from_path(
    source_path: Path,
) -> PdfReader:
    try:
        return PdfReader(
            str(
                source_path
            ),
            strict=True,
        )

    except (
        PdfReadError,
        OSError,
        ValueError,
    ) as exc:
        raise PdfRepresentationError(
            "Cannot parse PDF source bytes."
        ) from exc


def _iter_pdf_text_pages(
    reader: PdfReader,
) -> Iterator[tuple[int, str]]:
    if reader.is_encrypted:
        raise EncryptedPdfUnsupportedError(
            "VS6 Step 1 does not process "
            "encrypted PDFs; retain the original "
            "and retry after an explicit "
            "decryption workflow is available."
        )

    for index, page in enumerate(
        reader.pages
    ):
        try:
            extracted = (
                page.extract_text()
                or ""
            )

        except Exception as exc:
            raise PdfRepresentationError(
                "Native PDF text extraction "
                f"failed on page {index + 1}."
            ) from exc

        yield (
            index + 1,
            _normalize_text(
                extracted
            ),
        )


def _normalize_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")
