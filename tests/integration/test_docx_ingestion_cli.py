from __future__ import annotations

import io
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)
_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


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


def _docx_bytes() -> bytes:
    content_types = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""
    styles = f"""<?xml version="1.0" encoding="UTF-8"?>
<w:styles xmlns:w="{_W}">
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/></w:style>
</w:styles>"""
    document = f"""<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="{_W}"><w:body>
<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>ATHENA DOCX E2E</w:t></w:r></w:p>
<w:p><w:r><w:t>ATHENA_VS6_DOCX_RETRIEVAL_TOKEN</w:t></w:r></w:p>
<w:tbl>
<w:tr><w:tc><w:p><w:r><w:t>Key</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Value</w:t></w:r></w:p></w:tc></w:tr>
<w:tr><w:tc><w:p><w:r><w:t>Capital</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Berlin</w:t></w:r></w:p></w:tc></w:tr>
</w:tbl>
<w:sectPr/>
</w:body></w:document>"""
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in (
            ("[Content_Types].xml", content_types),
            ("word/document.xml", document),
            ("word/styles.xml", styles),
        ):
            info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, payload.encode("utf-8"))
    return output.getvalue()


def test_docx_scheduler_builds_structure_chunks_search_and_table_anchor(tmp_path: Path) -> None:
    source_file = tmp_path / "scheduler-report.docx"
    source_file.write_bytes(_docx_bytes())
    local_root = tmp_path / "runtime"

    imported = _run_cli(local_root, "source", "import", str(source_file))
    assert imported.returncode == 0, imported.stderr
    assert "MIME: application/vnd.openxmlformats-officedocument.wordprocessingml.document" in (
        imported.stdout
    )
    source_match = _UUID_RE.search(imported.stdout)
    assert source_match is not None
    source_id = source_match.group(0)
    source_file.unlink()

    verified = _run_cli(local_root, "source", "verify", source_id)
    assert verified.returncode == 0, verified.stderr
    assert f"Source verified: {source_id}" in verified.stdout

    queued = _run_cli(local_root, "job", "source-process", source_id, "--priority", "1")
    assert queued.returncode == 0, queued.stderr
    assert '"docx_parser":"athena.native_docx@1"' in queued.stdout
    job_match = _UUID_RE.search(queued.stdout)
    assert job_match is not None
    job_id = job_match.group(0)

    scheduled = _run_cli(
        local_root,
        "job",
        "scheduler-once",
        "--worker",
        "docx-e2e-scheduler",
    )
    assert scheduled.returncode == 0, scheduled.stderr
    assert f"Job: {job_id}" in scheduled.stdout
    assert "State: completed" in scheduled.stdout

    representations = _run_cli(local_root, "source", "representation-list", source_id)
    assert representations.returncode == 0, representations.stderr
    assert "type=normalized_text" in representations.stdout
    representation_match = _UUID_RE.search(representations.stdout)
    assert representation_match is not None
    representation_id = representation_match.group(0)

    structures = _run_cli(
        local_root,
        "source",
        "representation-structures",
        representation_id,
    )
    assert structures.returncode == 0, structures.stderr
    assert "type=heading path='/body/p[1]'" in structures.stdout
    assert "type=table path='/body/table[1]'" in structures.stdout
    target_line = next(
        line
        for line in structures.stdout.splitlines()
        if "type=table_cell" in line and "path='/body/table[1]/row[2]/cell[2]'" in line
    )
    target_structure_match = _UUID_RE.search(target_line)
    assert target_structure_match is not None
    target_structure_id = target_structure_match.group(0)

    chunks = _run_cli(local_root, "source", "chunk-list", representation_id)
    assert chunks.returncode == 0, chunks.stderr
    assert _UUID_RE.search(chunks.stdout) is not None

    searched = _run_cli(local_root, "source", "search", "ATHENA_VS6_DOCX_RETRIEVAL_TOKEN")
    assert searched.returncode == 0, searched.stderr
    assert f"source={source_id}" in searched.stdout
    assert f"representation={representation_id}" in searched.stdout

    anchor = _run_cli(
        local_root,
        "source",
        "anchor-from-structure",
        target_structure_id,
    )
    assert anchor.returncode == 0, anchor.stderr
    assert "Type: table_cell" in anchor.stdout
    anchor_match = _UUID_RE.search(anchor.stdout)
    assert anchor_match is not None
    anchor_id = anchor_match.group(0)

    anchor_verify = _run_cli(local_root, "source", "anchor-verify", anchor_id)
    assert anchor_verify.returncode == 0, anchor_verify.stderr
    anchor_read = _run_cli(local_root, "source", "anchor-read", anchor_id)
    assert anchor_read.returncode == 0, anchor_read.stderr
    assert anchor_read.stdout == "Berlin"
