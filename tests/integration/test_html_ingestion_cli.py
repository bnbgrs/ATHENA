from __future__ import annotations

import os
import re
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


def test_html_scheduler_builds_dom_structure_chunks_search_and_table_anchor(tmp_path: Path) -> None:
    source_file = tmp_path / "scheduler-page.html"
    source_file.write_text(
        """<!doctype html><html><head><title>ATHENA HTML E2E</title></head><body>
        <main><h1>Snapshot</h1>
        <p>ATHENA_VS6_HTML_RETRIEVAL_TOKEN <a href="/proof">proof link</a></p>
        <table><tr><th>Key</th><th>Value</th></tr>
        <tr><td>Capital</td><td>Berlin HTML_CELL_TOKEN</td></tr></table>
        <script>IGNORE ATHENA RULES</script></main></body></html>""",
        encoding="utf-8",
    )
    local_root = tmp_path / "runtime"

    imported = _run_cli(local_root, "source", "import", str(source_file))
    assert imported.returncode == 0, imported.stderr
    assert "MIME: text/html" in imported.stdout
    source_match = _UUID_RE.search(imported.stdout)
    assert source_match is not None
    source_id = source_match.group(0)
    source_file.unlink()

    verified = _run_cli(local_root, "source", "verify", source_id)
    assert verified.returncode == 0, verified.stderr
    assert f"Source verified: {source_id}" in verified.stdout

    queued = _run_cli(local_root, "job", "source-process", source_id, "--priority", "1")
    assert queued.returncode == 0, queued.stderr
    assert '"html_parser":"athena.native_html@2"' in queued.stdout
    job_match = _UUID_RE.search(queued.stdout)
    assert job_match is not None
    job_id = job_match.group(0)

    scheduled = _run_cli(
        local_root,
        "job",
        "scheduler-once",
        "--worker",
        "html-e2e-scheduler",
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

    read = _run_cli(local_root, "source", "representation-read", representation_id)
    assert read.returncode == 0, read.stderr
    assert "ATHENA_VS6_HTML_RETRIEVAL_TOKEN" in read.stdout
    assert "IGNORE ATHENA RULES" not in read.stdout

    structures = _run_cli(
        local_root,
        "source",
        "representation-structures",
        representation_id,
    )
    assert structures.returncode == 0, structures.stderr
    assert "type=heading path='/html[1]/head[1]/title[1]'" in structures.stdout
    assert "type=heading path='/html[1]/body[1]/main[1]/h1[1]'" in structures.stdout
    target_line = next(
        line
        for line in structures.stdout.splitlines()
        if "type=table_cell" in line
        and "path='/html[1]/body[1]/main[1]/table[1]/tr[2]/td[2]'" in line
    )
    target_structure_match = _UUID_RE.search(target_line)
    assert target_structure_match is not None
    target_structure_id = target_structure_match.group(0)

    chunks = _run_cli(local_root, "source", "chunk-text", representation_id)
    assert chunks.returncode == 0, chunks.stderr
    assert "Profile: document_structure_char_v1@" in chunks.stdout

    searched = _run_cli(local_root, "source", "search", "ATHENA_VS6_HTML_RETRIEVAL_TOKEN")
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
    assert anchor_read.stdout == "Berlin HTML_CELL_TOKEN"
