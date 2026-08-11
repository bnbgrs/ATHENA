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


def test_cli_chat_survives_separate_process_restarts(tmp_path) -> None:
    create = _run_cli(tmp_path, "chat", "new")
    assert create.returncode == 0, create.stderr
    match = _UUID_RE.search(create.stdout)
    assert match is not None
    chat_id = match.group(0)

    append = _run_cli(tmp_path, "chat", "add", chat_id, "Persist across processes")
    assert append.returncode == 0, append.stderr
    assert "Sequence: 1" in append.stdout

    show = _run_cli(tmp_path, "chat", "show", chat_id)
    assert show.returncode == 0, show.stderr
    assert f"Chat: {chat_id}" in show.stdout
    assert "Messages: 1" in show.stdout
    assert "[1] user: Persist across processes" in show.stdout

    listing = _run_cli(tmp_path, "chat", "list")
    assert listing.returncode == 0, listing.stderr
    assert chat_id in listing.stdout
    assert "messages=1" in listing.stdout


def test_cli_rejects_blank_message_without_persisting_it(tmp_path) -> None:
    create = _run_cli(tmp_path, "chat", "new")
    match = _UUID_RE.search(create.stdout)
    assert create.returncode == 0 and match is not None
    chat_id = match.group(0)

    append = _run_cli(tmp_path, "chat", "add", chat_id, "   ")
    assert append.returncode == 2
    assert "must contain non-whitespace text" in append.stderr

    show = _run_cli(tmp_path, "chat", "show", chat_id)
    assert show.returncode == 0, show.stderr
    assert "Messages: 0" in show.stdout
