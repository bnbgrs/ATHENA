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


def _create_claim(root: Path, text: str) -> str:
    create_chat = _run_cli(root, "chat", "new")
    assert create_chat.returncode == 0, create_chat.stderr
    chat_match = _UUID_RE.search(create_chat.stdout)
    assert chat_match is not None
    chat_id = chat_match.group(0)

    append = _run_cli(root, "chat", "add", chat_id, text)
    assert append.returncode == 0, append.stderr

    promote = _run_cli(
        root,
        "claim",
        "promote",
        chat_id,
        "1",
        "--kind",
        "factual_assertion",
    )
    assert promote.returncode == 0, promote.stderr
    claim_match = re.search(r"Claim created: (" + _UUID_RE.pattern + r")", promote.stdout)
    assert claim_match is not None
    return claim_match.group(1)


def test_cli_creates_and_shows_claim_with_chat_origin(tmp_path) -> None:
    claim_id = _create_claim(tmp_path, "Mars has two moons.")

    show = _run_cli(tmp_path, "claim", "show", claim_id)
    assert show.returncode == 0, show.stderr
    assert "Revision: 1" in show.stdout
    assert "Kind: factual_assertion" in show.stdout
    assert "Statement: Mars has two moons." in show.stdout
    assert "Provenance inputs: 1" in show.stdout
    assert "role=chat_message_source" in show.stdout
    assert "role=originates" in show.stdout


def test_cli_links_two_claims_without_overwriting_either(tmp_path) -> None:
    left = _create_claim(tmp_path, "The door is open.")
    right = _create_claim(tmp_path, "The door is closed.")

    link = _run_cli(tmp_path, "claim", "contradict", left, right)
    assert link.returncode == 0, link.stderr
    assert f"Contradiction linked: {left} <-> {right}" in link.stdout

    left_show = _run_cli(tmp_path, "claim", "show", left)
    right_show = _run_cli(tmp_path, "claim", "show", right)
    assert left_show.returncode == 0, left_show.stderr
    assert right_show.returncode == 0, right_show.stderr
    assert "Statement: The door is open." in left_show.stdout
    assert "Statement: The door is closed." in right_show.stdout
    assert "role=contradicts" in left_show.stdout
    assert right in left_show.stdout
    assert "role=contradicts" in right_show.stdout
    assert left in right_show.stdout
