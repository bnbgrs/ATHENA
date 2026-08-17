from __future__ import annotations

from pathlib import Path

import pytest

from athena.source.pdf_parser import (
    IsolatedPdfTextParser,
    PdfNativeTextUnavailableError,
    PdfParserPolicy,
    PdfParserTimeoutError,
    PdfRepresentationError,
    PdfResourceLimitError,
)
from athena.source.pdf_representation_store import (
    extract_pdf_text_bytes,
)


def _native_text_pdf(
    pages: tuple[str, ...],
) -> bytes:
    font_id = (
        3
        + (2 * len(pages))
    )

    objects: dict[
        int,
        bytes,
    ] = {
        1: (
            b"<< /Type /Catalog "
            b"/Pages 2 0 R >>"
        ),
        2: (
            (
                "<< /Type /Pages /Kids "
                "["
                + " ".join(
                    (
                        f"{3 + 2 * index} 0 R"
                    )
                    for index
                    in range(
                        len(pages)
                    )
                )
                + "] "
                f"/Count {len(pages)} >>"
            ).encode(
                "ascii"
            )
        ),
        font_id: (
            b"<< /Type /Font "
            b"/Subtype /Type1 "
            b"/BaseFont /Helvetica >>"
        ),
    }

    for (
        index,
        text,
    ) in enumerate(
        pages
    ):
        page_id = (
            3
            + (2 * index)
        )

        content_id = (
            page_id
            + 1
        )

        escaped = (
            text
            .replace(
                "\\",
                "\\\\",
            )
            .replace(
                "(",
                "\\(",
            )
            .replace(
                ")",
                "\\)",
            )
        )

        stream = (
            (
                "BT /F1 12 Tf "
                "72 720 Td "
                f"({escaped}) Tj ET"
            )
            .encode(
                "latin-1"
            )
        )

        objects[page_id] = (
            (
                "<< /Type /Page "
                "/Parent 2 0 R "
                "/MediaBox [0 0 612 792] "
                "/Resources << /Font << "
                f"/F1 {font_id} 0 R "
                ">> >> "
                f"/Contents {content_id} 0 R >>"
            )
            .encode(
                "ascii"
            )
        )

        objects[content_id] = (
            (
                f"<< /Length {len(stream)} >>"
                "\nstream\n"
            ).encode(
                "ascii"
            )
            + stream
            + b"\nendstream"
        )

    highest = max(
        objects
    )

    output = bytearray(
        b"%PDF-1.4\n%ATHENA\n"
    )

    offsets = [
        0
    ] * (
        highest
        + 1
    )

    for object_id in range(
        1,
        highest + 1,
    ):
        offsets[
            object_id
        ] = len(
            output
        )

        output.extend(
            (
                f"{object_id} 0 obj\n"
            ).encode(
                "ascii"
            )
        )

        output.extend(
            objects[
                object_id
            ]
        )

        output.extend(
            b"\nendobj\n"
        )

    xref = len(
        output
    )

    output.extend(
        (
            f"xref\n0 {highest + 1}\n"
        ).encode(
            "ascii"
        )
    )

    output.extend(
        b"0000000000 65535 f \n"
    )

    for object_id in range(
        1,
        highest + 1,
    ):
        output.extend(
            (
                f"{offsets[object_id]:010d} "
                "00000 n \n"
            ).encode(
                "ascii"
            )
        )

    output.extend(
        (
            "trailer\n"
            f"<< /Size {highest + 1} "
            "/Root 1 0 R >>\n"
            "startxref\n"
            f"{xref}\n"
            "%%EOF\n"
        ).encode(
            "ascii"
        )
    )

    return bytes(
        output
    )


def test_isolated_parser_preserves_page_order_and_text(
    tmp_path: Path,
) -> None:
    payload = _native_text_pdf(
        (
            "Alpha page",
            "Beta page",
        )
    )

    path = (
        tmp_path
        / "safe.pdf"
    )

    path.write_bytes(
        payload
    )

    parsed = (
        IsolatedPdfTextParser()
        .parse_path(
            path
        )
    )

    assert (
        parsed.page_count
        == 2
    )

    assert tuple(
        page.page_number
        for page
        in parsed.pages
    ) == (
        1,
        2,
    )

    assert (
        parsed.text()
        == (
            "Alpha page"
            "\n\n"
            "Beta page"
        )
    )

    assert (
        parsed.byte_length
        == len(
            parsed.text()
            .encode(
                "utf-8"
            )
        )
    )


def test_isolated_parser_rejects_input_before_child_start() -> None:
    parser = IsolatedPdfTextParser(
        PdfParserPolicy(
            max_input_bytes=16
        )
    )

    with pytest.raises(
        PdfResourceLimitError,
        match="input exceeds",
    ):
        parser.parse_bytes(
            b"%PDF-"
            + (b"x" * 32)
        )


def test_isolated_parser_rejects_excessive_page_count() -> None:
    parser = IsolatedPdfTextParser(
        PdfParserPolicy(
            max_pages=1
        )
    )

    with pytest.raises(
        PdfResourceLimitError,
        match="page count",
    ):
        parser.parse_bytes(
            _native_text_pdf(
                (
                    "One",
                    "Two",
                )
            )
        )


def test_isolated_parser_rejects_excessive_output() -> None:
    parser = IsolatedPdfTextParser(
        PdfParserPolicy(
            max_output_bytes=32
        )
    )

    with pytest.raises(
        PdfResourceLimitError,
        match="output byte limit",
    ):
        parser.parse_bytes(
            _native_text_pdf(
                (
                    "X" * 128,
                )
            )
        )


def test_isolated_parser_timeout_kills_child_and_recovers() -> None:
    payload = _native_text_pdf(
        (
            "Timeout marker",
        )
    )

    parser = IsolatedPdfTextParser(
        PdfParserPolicy(
            timeout_seconds=0.001
        )
    )

    with pytest.raises(
        PdfParserTimeoutError,
        match="wall-clock timeout",
    ):
        parser.parse_bytes(
            payload
        )

    recovered = (
        IsolatedPdfTextParser(
            PdfParserPolicy(
                timeout_seconds=30.0
            )
        )
        .parse_bytes(
            payload
        )
    )

    assert (
        recovered.text()
        == "Timeout marker"
    )


def test_isolated_parser_preserves_existing_failure_contracts() -> None:
    parser = (
        IsolatedPdfTextParser()
    )

    with pytest.raises(
        PdfRepresentationError
    ):
        parser.parse_bytes(
            b"%PDF-1.7\nbroken"
        )

    with pytest.raises(
        PdfNativeTextUnavailableError,
        match="OCR fallback",
    ):
        parser.parse_bytes(
            _native_text_pdf(
                (
                    "",
                )
            )
        )


def test_protected_bytes_api_remains_memory_only_and_bounded() -> None:
    payload = _native_text_pdf(
        (
            "Protected PDF evidence",
        )
    )

    parser = IsolatedPdfTextParser(
        PdfParserPolicy(
            max_output_bytes=1024
        )
    )

    assert (
        extract_pdf_text_bytes(
            payload,
            parser=parser,
        )
        == "Protected PDF evidence"
    )

def test_isolated_parser_ignores_pythonpath_sitecustomize(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    poison = (
        tmp_path
        / "poison"
    )

    poison.mkdir()

    marker = (
        tmp_path
        / "sitecustomize-executed.txt"
    )

    (
        poison
        / "sitecustomize.py"
    ).write_text(
        (
            "import os\n"
            "from pathlib import Path\n"
            "Path("
            "os.environ['ATHENA_PDF_POISON_MARKER']"
            ").write_text('executed', encoding='utf-8')\n"
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv(
        "PYTHONPATH",
        str(
            poison
        ),
    )

    monkeypatch.setenv(
        "ATHENA_PDF_POISON_MARKER",
        str(
            marker
        ),
    )

    parsed = (
        IsolatedPdfTextParser()
        .parse_bytes(
            _native_text_pdf(
                (
                    "Isolated child",
                )
            )
        )
    )

    assert (
        parsed.text()
        == "Isolated child"
    )

    assert not marker.exists()


def test_default_pdf_timeout_leaves_scheduler_lease_headroom() -> None:
    from athena.jobs.scheduler import (
        SchedulerPolicy,
    )
    from athena.source.pdf_parser import (
        DEFAULT_PDF_PARSER_POLICY,
    )

    assert (
        DEFAULT_PDF_PARSER_POLICY.timeout_seconds
        <= SchedulerPolicy().lease_seconds - 30
    )
