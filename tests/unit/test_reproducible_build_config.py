from __future__ import annotations

import tomllib
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_PYPROJECT = _ROOT / "pyproject.toml"
_WORKFLOW = _ROOT / ".github" / "workflows" / "quality.yml"
_LOCKFILE = _ROOT / "uv.lock"


def test_build_backend_and_resolver_versions_are_exactly_pinned() -> None:
    config = tomllib.loads(
        _PYPROJECT.read_text(
            encoding="utf-8"
        )
    )

    assert config["build-system"]["requires"] == [
        "setuptools==83.0.0",
        "wheel==0.47.0",
    ]
    assert (
        config["tool"]["uv"]["required-version"]
        == "==0.11.21"
    )


def test_quality_ci_uses_only_the_frozen_dependency_resolution() -> None:
    workflow = _WORKFLOW.read_text(
        encoding="utf-8"
    )

    assert '"pip==26.1.2"' in workflow
    assert '"uv==0.11.21"' in workflow
    assert "sudo apt-get update" in workflow
    assert (
        "sudo apt-get install --no-install-recommends -y libegl1"
        in workflow
    )
    assert "uv lock --check" in workflow
    assert (
        "uv run --locked --extra dev --extra desktop "
        "python scripts/quality.py"
        in workflow
    )

    assert "pip install --upgrade pip" not in workflow
    assert 'pip install -e ".[dev]"' not in workflow


def test_lockfile_covers_runtime_and_development_dependencies() -> None:
    lock_text = _LOCKFILE.read_text(
        encoding="utf-8"
    )

    required_packages = {
        "athena-local",
        "cryptography",
        "pypdf",
        "numpy",
        "usearch",
        "tzdata",
        "mypy",
        "pytest",
        "ruff",
    }

    for package in required_packages:
        assert f'name = "{package}"' in lock_text
