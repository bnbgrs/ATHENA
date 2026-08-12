import tomllib
from pathlib import Path


def test_quality_gate_tools_are_pinned() -> None:
    config = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    dev_dependencies = set(config["project"]["optional-dependencies"]["dev"])

    assert "pytest==9.1.1" in dev_dependencies
    assert "ruff==0.15.22" in dev_dependencies
    assert "mypy==2.3.0" in dev_dependencies


def test_project_remains_pinned_to_python_312() -> None:
    config = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert config["project"]["requires-python"] == ">=3.12,<3.13"
    assert config["tool"]["ruff"]["target-version"] == "py312"
    assert config["tool"]["mypy"]["python_version"] == "3.12"



def test_quality_gate_invokes_ruff_via_current_python_interpreter() -> None:
    source = Path("scripts/quality.py").read_text(encoding="utf-8")

    assert 'sys.executable,' in source
    assert '"-m",' in source
    assert '"ruff",' in source
    assert 'shutil.which("ruff")' not in source
