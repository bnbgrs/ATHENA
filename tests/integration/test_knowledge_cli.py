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


def test_cli_promotes_chat_message_and_preserves_revision_history(tmp_path) -> None:
    create_chat = _run_cli(tmp_path, "chat", "new")
    assert create_chat.returncode == 0, create_chat.stderr
    chat_match = _UUID_RE.search(create_chat.stdout)
    assert chat_match is not None
    chat_id = chat_match.group(0)

    append = _run_cli(tmp_path, "chat", "add", chat_id, "Earth orbits the Sun.")
    assert append.returncode == 0, append.stderr

    promote = _run_cli(
        tmp_path,
        "knowledge",
        "promote",
        chat_id,
        "1",
        "--kind",
        "fact",
        "--title",
        "Heliocentrism",
    )
    assert promote.returncode == 0, promote.stderr
    knowledge_match = re.search(r"Knowledge created: (" + _UUID_RE.pattern + r")", promote.stdout)
    assert knowledge_match is not None
    knowledge_id = knowledge_match.group(1)

    show = _run_cli(tmp_path, "knowledge", "show", knowledge_id)
    assert show.returncode == 0, show.stderr
    assert "Revision: 1" in show.stdout
    assert "Kind: fact" in show.stdout
    assert "Title: Heliocentrism" in show.stdout
    assert "Body: Earth orbits the Sun." in show.stdout
    assert "Provenance inputs: 1" in show.stdout
    assert "role=chat_message_source" in show.stdout

    revise = _run_cli(
        tmp_path,
        "knowledge",
        "revise",
        knowledge_id,
        "Earth orbits the Sun once per year.",
        "--status",
        "supported",
    )
    assert revise.returncode == 0, revise.stderr
    assert "Revision: 2" in revise.stdout

    history = _run_cli(tmp_path, "knowledge", "history", knowledge_id)
    assert history.returncode == 0, history.stderr
    assert "Revisions: 2" in history.stdout
    assert "[1]" in history.stdout
    assert "[2]" in history.stdout
    assert "body=Earth orbits the Sun." in history.stdout
    assert "body=Earth orbits the Sun once per year." in history.stdout


def test_cli_rejects_missing_source_message_without_knowledge_write(tmp_path) -> None:
    create_chat = _run_cli(tmp_path, "chat", "new")
    chat_match = _UUID_RE.search(create_chat.stdout)
    assert create_chat.returncode == 0 and chat_match is not None

    promote = _run_cli(
        tmp_path,
        "knowledge",
        "promote",
        chat_match.group(0),
        "99",
        "--kind",
        "fact",
    )
    assert promote.returncode == 2
    assert "has no message with sequence 99" in promote.stderr

    listing = _run_cli(tmp_path, "knowledge", "list")
    assert listing.returncode == 0, listing.stderr
    assert "No canonical KnowledgeUnits." in listing.stdout
