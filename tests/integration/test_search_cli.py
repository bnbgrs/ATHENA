from __future__ import annotations

from athena.__main__ import main


def test_search_cli_empty_database(capsys, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ATHENA_DATA_DIR", str(tmp_path))
    exit_code = main(["search", "nichts"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Retrieval results: 0" in captured.out


def test_search_cli_raw_mode(capsys, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ATHENA_DATA_DIR", str(tmp_path))
    exit_code = main(["search", "nichts", "--raw"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Raw search results: 0" in captured.out
