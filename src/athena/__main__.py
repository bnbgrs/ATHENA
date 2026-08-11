"""Command-line launcher for ATHENA."""

from __future__ import annotations

import argparse
import sys

from athena.config.settings import ConfigurationError
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
    parser.add_argument(
        "--show-paths",
        action="store_true",
        help="Print resolved ATHENA runtime paths.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()

    try:
        app = AthenaApplication()
    except ConfigurationError as exc:
        print(f"ATHENA configuration error: {exc}", file=sys.stderr)
        return 2

    try:
        app.start()
        health = app.health.snapshot()

        print(f"ATHENA {__version__}")
        print(f"Core state: {app.state.value}")
        print(f"Health: {health.status.value}")

        if args.show_paths:
            print(f"Local root: {app.paths.local_root}")
            print(f"State root: {app.paths.state_root}")
            print(f"Database: {app.paths.database_path}")
            print(f"Spool root: {app.paths.spool_root}")
            print(f"Derived root: {app.paths.derived_root}")
            print(f"Log root: {app.paths.log_root}")
            print(f"Temp root: {app.paths.temp_root}")
            print(
                "Archive root: "
                + (str(app.paths.archive_root) if app.paths.archive_root else "<unset>")
            )
            print(
                "Backup root: "
                + (str(app.paths.backup_root) if app.paths.backup_root else "<unset>")
            )
            print(
                "Projection root: "
                + (
                    str(app.paths.projection_root)
                    if app.paths.projection_root
                    else "<unset>"
                )
            )

        return 0
    finally:
        if app.state.value != "stopped":
            app.stop()


if __name__ == "__main__":
    raise SystemExit(main())
