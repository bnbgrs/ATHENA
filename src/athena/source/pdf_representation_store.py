"""Deterministic native-text extraction for paginated PDF Sources."""

from __future__ import annotations

import hashlib
import os
import secrets
from dataclasses import dataclass
from pathlib import Path

from athena.source.pdf_parser import (
    DEFAULT_PDF_PARSER_POLICY,
    EncryptedPdfUnsupportedError,
    IsolatedPdfTextParser,
    PdfNativeTextUnavailableError,
    PdfParserIsolationError,
    PdfParserPolicy,
    PdfParserTimeoutError,
    PdfRepresentationError,
    PdfResourceLimitError,
)
from athena.source.representation_store import (
    PreparedTextRepresentation,
    StoredRepresentationBlob,
    TextRepresentationStore,
)
from athena.storage.paths import RuntimePaths

_PAGE_SEPARATOR = "\n\n"


class UnsupportedPdfSourceError(
    PdfRepresentationError
):
    """Raised when the Source is not a PDF suitable for this parser."""


@dataclass(
    frozen=True,
    slots=True,
)
class PdfPageSpan:
    page_number: int
    start_offset: int
    end_offset: int
    content_sha256: bytes


@dataclass(
    frozen=True,
    slots=True,
)
class PreparedPdfTextRepresentation:
    staging_path: Path
    byte_length: int
    content_sha256: bytes
    pages: tuple[
        PdfPageSpan,
        ...,
    ]


class PdfNativeTextRepresentationStore:
    """Extract page-ordered native PDF text to immutable UTF-8 representation bytes."""

    def __init__(
        self,
        paths: RuntimePaths,
        *,
        parser: IsolatedPdfTextParser | None = None,
    ) -> None:
        self.paths = paths
        self.parser = (
            parser
            or IsolatedPdfTextParser()
        )
        self._text_store = (
            TextRepresentationStore(
                paths
            )
        )

    def extract(
        self,
        source_path: Path,
    ) -> PreparedPdfTextRepresentation:
        parsed = (
            self.parser.parse_path(
                source_path
            )
        )

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
            / (
                "pdf-text-"
                f"{secrets.token_hex(16)}"
                ".partial"
            )
        )

        digest = hashlib.sha256()
        byte_length = 0
        char_offset = 0

        page_spans: list[
            PdfPageSpan
        ] = []

        try:
            with staging_path.open(
                "xb"
            ) as target:
                for page in parsed.pages:
                    normalized = (
                        page.text
                    )

                    start_offset = (
                        char_offset
                    )

                    encoded = (
                        normalized.encode(
                            "utf-8"
                        )
                    )

                    if encoded:
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

                    end_offset = (
                        char_offset
                    )

                    page_spans.append(
                        PdfPageSpan(
                            page_number=(
                                page.page_number
                            ),
                            start_offset=(
                                start_offset
                            ),
                            end_offset=(
                                end_offset
                            ),
                            content_sha256=(
                                hashlib.sha256(
                                    encoded
                                ).digest()
                            ),
                        )
                    )

                    if (
                        page.page_number
                        < parsed.page_count
                    ):
                        separator = (
                            _PAGE_SEPARATOR
                            .encode(
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

        if (
            byte_length
            != parsed.byte_length
        ):
            staging_path.unlink(
                missing_ok=True
            )

            raise PdfParserIsolationError(
                "PDF parser byte count changed "
                "before representation staging."
            )

        return (
            PreparedPdfTextRepresentation(
                staging_path=staging_path,
                byte_length=byte_length,
                content_sha256=(
                    digest.digest()
                ),
                pages=tuple(
                    page_spans
                ),
            )
        )

    def discard(
        self,
        prepared: PreparedPdfTextRepresentation,
    ) -> None:
        prepared.staging_path.unlink(
            missing_ok=True
        )

    def commit(
        self,
        prepared: PreparedPdfTextRepresentation,
    ) -> StoredRepresentationBlob:
        base = PreparedTextRepresentation(
            staging_path=(
                prepared.staging_path
            ),
            byte_length=(
                prepared.byte_length
            ),
            content_sha256=(
                prepared.content_sha256
            ),
        )

        return self._text_store.commit(
            base
        )


def extract_pdf_text_bytes(
    payload: bytes,
    *,
    parser: IsolatedPdfTextParser | None = None,
) -> str:
    """Extract bounded PDF text from plaintext bytes without disk persistence."""

    active_parser = (
        parser
        or IsolatedPdfTextParser()
    )

    return (
        active_parser
        .parse_bytes(
            payload
        )
        .text()
    )


__all__ = [
    "DEFAULT_PDF_PARSER_POLICY",
    "EncryptedPdfUnsupportedError",
    "IsolatedPdfTextParser",
    "PdfNativeTextRepresentationStore",
    "PdfNativeTextUnavailableError",
    "PdfPageSpan",
    "PdfParserIsolationError",
    "PdfParserPolicy",
    "PdfParserTimeoutError",
    "PdfRepresentationError",
    "PdfResourceLimitError",
    "PreparedPdfTextRepresentation",
    "UnsupportedPdfSourceError",
    "extract_pdf_text_bytes",
]
