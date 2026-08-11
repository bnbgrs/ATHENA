"""Command-line launcher for ATHENA."""

from __future__ import annotations

import argparse

from athena.core.application import AthenaApplication
from athena.version import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="athena",
        description="ATHENA local-first personal knowledge system",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"ATHENA {__version__}",
    )
    return parser


def main() -> int:
    build_parser().parse_args()

    app = AthenaApplication()
    app.start()

    health = app.health.snapshot()
    print(f"ATHENA {__version__}")
    print(f"Core state: {app.state.value}")
    print(f"Health: {health.status.value}")

    app.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
