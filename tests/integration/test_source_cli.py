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
