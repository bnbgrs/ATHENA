"""Run ATHENA's local quality gate.

This script intentionally mirrors the checks used by GitHub Actions so a
developer can reproduce CI failures locally before pushing a commit.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    command: tuple[str, ...]


def main() -> int:
    checks = (
        Check(
            name="Specification validator",
            command=(sys.executable, "scripts/validate_spec.py"),
        ),
        Check(
            name="Ruff",
            command=(
                sys.executable,
                "-m",
                "ruff",
                "check",
                "src",
                "tests",
                "scripts",
            ),
        ),
        Check(
            name="mypy",
            command=(sys.executable, "-m", "mypy", "src/athena"),
        ),
        Check(
            name="pytest",
            command=(sys.executable, "-m", "pytest"),
        ),
    )

    print("ATHENA QUALITY GATE")
    print("=" * 60)

    for check in checks:
        print(f"\n[RUN] {check.name}")
        print(" ".join(check.command))

        completed = subprocess.run(
            check.command,
            check=False,
        )

        if completed.returncode != 0:
            print(
                f"\n[FAIL] {check.name} returned {completed.returncode}.",
                file=sys.stderr,
            )
            return completed.returncode

        print(f"[PASS] {check.name}")

    print("\n" + "=" * 60)
    print("ATHENA QUALITY GATE: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
