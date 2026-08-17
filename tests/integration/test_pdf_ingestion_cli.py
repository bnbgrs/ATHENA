from __future__ import annotations

import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)


def _run_cli(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["ATHENA_LOCAL_ROOT"] = str(root.resolve())
    return subprocess.run(
        [sys.executable, "-m", "athena", *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def _neutralize_environmental_resource_headroom(
    root: Path,
) -> None:
    """Keep pipeline integration tests independent of host RAM/disk fluctuations."""
    database = (
        root
        / "state"
        / "athena.db"
    )

    with sqlite3.connect(
        database
    ) as connection:
        cursor = connection.execute(
            """
            UPDATE resource_policy
            SET ram_headroom_bytes = 0,
                disk_headroom_bytes = 0
            WHERE singleton_id = 1
            """
        )

        if cursor.rowcount != 1:
            raise RuntimeError(
                "ATHENA resource_policy row "
                "is missing from test runtime."
            )

        connection.commit()



def _native_text_pdf(pages: tuple[str, ...]) -> bytes:
    font_id = 3 + (2 * len(pages))
    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: (
            f"<< /Type /Pages /Kids [{' '.join(f'{3 + 2*i} 0 R' for i in range(len(pages)))}] "
            f"/Count {len(pages)} >>"
        ).encode("ascii"),
        font_id: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    for index, text in enumerate(pages):
        page_id = 3 + 2 * index
        content_id = page_id + 1
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("latin-1")
        objects[page_id] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {content_id} 0 R >>"
        ).encode("ascii")
        objects[content_id] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode("ascii")
            + stream
            + b"\nendstream"
        )
    highest = max(objects)
    output = bytearray(b"%PDF-1.4\n%ATHENA\n")
    offsets = [0] * (highest + 1)
    for object_id in range(1, highest + 1):
        offsets[object_id] = len(output)
        output.extend(f"{object_id} 0 obj\n".encode("ascii"))
        output.extend(objects[object_id])
        output.extend(b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {highest + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for object_id in range(1, highest + 1):
        output.extend(f"{offsets[object_id]:010d} 00000 n \n".encode("ascii"))
    output.extend(
        f"trailer\n<< /Size {highest + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode(
            "ascii"
        )
    )
    return bytes(output)


def test_pdf_source_process_scheduler_builds_page_map_chunks_and_search(tmp_path: Path) -> None:
    source_file = tmp_path / "scheduler-paper.pdf"
    source_file.write_bytes(
        _native_text_pdf(
            (
                "ATHENA PDF scheduler marker first page",
                "Native PDF second page provenance marker",
                "Third page retrieval marker",
            )
        )
    )
    local_root = tmp_path / "runtime"

    imported = _run_cli(local_root, "source", "import", str(source_file))
    assert imported.returncode == 0, imported.stderr
    source_match = _UUID_RE.search(imported.stdout)
    assert source_match is not None
    source_id = source_match.group(0)
    source_file.unlink()

    queued = _run_cli(local_root, "job", "source-process", source_id, "--priority", "1")
    assert queued.returncode == 0, queued.stderr
    job_match = _UUID_RE.search(queued.stdout)
    assert job_match is not None
    job_id = job_match.group(0)
    assert '"pdf_parser":"athena.native_pdf@1+pypdf-' in queued.stdout

    # Resource admission itself has deterministic unit coverage.
    # This integration test isolates PDF/source processing semantics.
    _neutralize_environmental_resource_headroom(
        local_root
    )

    scheduled = _run_cli(
        local_root,
        "job",
        "scheduler-once",
        "--worker",
        "pdf-e2e-scheduler",
    )
    assert scheduled.returncode == 0, scheduled.stderr
    assert f"Job: {job_id}" in scheduled.stdout
    assert "Type: source.process" in scheduled.stdout
    assert "State: completed" in scheduled.stdout

    representations = _run_cli(local_root, "source", "representation-list", source_id)
    assert representations.returncode == 0, representations.stderr
    assert "type=extracted_text" in representations.stdout
    representation_match = _UUID_RE.search(representations.stdout)
    assert representation_match is not None
    representation_id = representation_match.group(0)

    pages = _run_cli(local_root, "source", "representation-pages", representation_id)
    assert pages.returncode == 0, pages.stderr
    assert "Representation pages: 3" in pages.stdout
    assert "page=1" in pages.stdout
    assert "page=2" in pages.stdout
    assert "page=3" in pages.stdout

    chunks = _run_cli(local_root, "source", "chunk-list", representation_id)
    assert chunks.returncode == 0, chunks.stderr
    chunk_match = _UUID_RE.search(chunks.stdout)
    assert chunk_match is not None
    chunk_id = chunk_match.group(0)

    searched = _run_cli(local_root, "source", "search", "PDF scheduler marker")
    assert searched.returncode == 0, searched.stderr
    assert f"source={source_id}" in searched.stdout
    assert f"representation={representation_id}" in searched.stdout

    anchor = _run_cli(local_root, "source", "anchor-from-chunk", chunk_id)
    assert anchor.returncode == 0, anchor.stderr
    assert "SourceAnchor:" in anchor.stdout
    assert "Page:" in anchor.stdout
