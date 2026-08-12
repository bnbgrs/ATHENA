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


def test_source_import_show_verify_and_list_survive_process_restarts(tmp_path) -> None:
    original = tmp_path / "source.txt"
    original.write_text("Persistent Raw Archive bytes", encoding="utf-8")
    local_root = tmp_path / "runtime"

    imported = _run_cli(local_root, "source", "import", str(original))
    assert imported.returncode == 0, imported.stderr
    match = _UUID_RE.search(imported.stdout)
    assert match is not None
    source_id = match.group(0)
    assert "State: captured" in imported.stdout
    assert "reused=no" in imported.stdout

    shown = _run_cli(local_root, "source", "show", source_id)
    assert shown.returncode == 0, shown.stderr
    assert f"Source: {source_id}" in shown.stdout
    assert "Original name: source.txt" in shown.stdout
    assert "State: captured" in shown.stdout

    verified = _run_cli(local_root, "source", "verify", source_id)
    assert verified.returncode == 0, verified.stderr
    assert f"Source verified: {source_id}" in verified.stdout

    listing = _run_cli(local_root, "source", "list")
    assert listing.returncode == 0, listing.stderr
    assert source_id in listing.stdout


def test_text_representation_cli_survives_process_restarts(tmp_path) -> None:
    original = tmp_path / "source.md"
    original.write_bytes(b"\xef\xbb\xbf# Title\r\n\rBody\r\n")
    local_root = tmp_path / "runtime"

    imported = _run_cli(local_root, "source", "import", str(original))
    assert imported.returncode == 0, imported.stderr
    source_match = _UUID_RE.search(imported.stdout)
    assert source_match is not None
    source_id = source_match.group(0)
    original.unlink()

    represented = _run_cli(local_root, "source", "represent-text", source_id)
    assert represented.returncode == 0, represented.stderr
    representation_match = _UUID_RE.search(represented.stdout)
    assert representation_match is not None
    representation_id = representation_match.group(0)
    assert "Run status: succeeded" in represented.stdout
    assert "Retention: retained" in represented.stdout

    shown = _run_cli(local_root, "source", "representation-show", representation_id)
    assert shown.returncode == 0, shown.stderr
    assert f"Representation: {representation_id}" in shown.stdout
    assert f"Source: {source_id}" in shown.stdout
    assert "Parser: athena.native_text@1" in shown.stdout

    verified = _run_cli(local_root, "source", "representation-verify", representation_id)
    assert verified.returncode == 0, verified.stderr
    assert f"Representation verified: {representation_id}" in verified.stdout

    read = _run_cli(local_root, "source", "representation-read", representation_id)
    assert read.returncode == 0, read.stderr
    assert read.stdout == "# Title\n\nBody\n"

    listing = _run_cli(local_root, "source", "representation-list", source_id)
    assert listing.returncode == 0, listing.stderr
    assert representation_id in listing.stdout
