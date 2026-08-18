from __future__ import annotations

import json

from athena.__main__ import main


def test_context_cli_empty_database_returns_valid_json(capsys, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ATHENA_LOCAL_ROOT", str(tmp_path))
    exit_code = main(
        [
            "context",
            "build",
            "nichts",
            "--max-tokens",
            "300",
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Context bundle: mode=lexical items=0" in captured.out

    json_start = captured.out.index("{")
    payload = json.loads(captured.out[json_start:])
    assert payload["athena_context_version"] == 2
    assert payload["query"] == "nichts"
    assert payload["items"] == []


def test_context_cli_rejects_too_small_budget(capsys, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ATHENA_LOCAL_ROOT", str(tmp_path))
    exit_code = main(
        [
            "context",
            "build",
            "nichts",
            "--max-tokens",
            "50",
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 2
    assert "Context token budget must be between" in captured.err
