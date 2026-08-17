from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.knowledge.models import KnowledgeKind

_CANARY = (
    "SLICE16F_PRIVATE_DIAGNOSTIC_CANARY_"
    "MUST_NEVER_APPEAR_IN_OUTPUT"
)


def _prepare_runtime(
    tmp_path: Path,
) -> Path:
    runtime = (
        tmp_path
        / "runtime"
    )

    app = AthenaApplication(
        settings=AthenaSettings(
            local_root=runtime,
        )
    )

    app.start()

    try:
        chat_id = app.chat.create_chat()

        message = app.chat.add_user_message(
            chat_id=chat_id,
            content=(
                "Berlin ist die Hauptstadt Deutschlands. "
                + _CANARY
            ),
        )

        app.knowledge.promote_chat_message(
            chat_id=chat_id,
            sequence_no=message.sequence_no,
            knowledge_kind=KnowledgeKind.FACT,
        )

        source_path = (
            tmp_path
            / "recovery-diagnostics-source.txt"
        )

        source_path.write_text(
            "Berlin ist die Hauptstadt Deutschlands.",
            encoding="utf-8",
        )

        captured = app.sources.capture_file(
            source_path
        )

        represented = app.source_text.build(
            captured.source.source_id
        )

        app.source_chunks.build_default(
            represented.result
            .representation
            .representation_id
        )

        app.search.rebuild()

    finally:
        app.stop()

    return runtime


def _run_diagnose(
    runtime: Path,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["ATHENA_LOCAL_ROOT"] = str(
        runtime.resolve()
    )

    return subprocess.run(
        [
            sys.executable,
            "-m",
            "athena.recovery_cli",
            "diagnose",
        ],
        text=True,
        capture_output=True,
        check=False,
        env=environment,
    )


def _payload(
    completed: subprocess.CompletedProcess[str],
) -> dict[str, object]:
    return json.loads(
        completed.stdout
    )


def _issue_codes(
    payload: dict[str, object],
) -> set[str]:
    raw = payload["issues"]

    assert isinstance(
        raw,
        list,
    )

    result: set[str] = set()

    for item in raw:
        assert isinstance(
            item,
            dict,
        )

        code = item.get(
            "code"
        )

        assert isinstance(
            code,
            str,
        )

        result.add(
            code
        )

    return result


def test_healthy_recovery_diagnostics_are_payload_free(
    tmp_path: Path,
) -> None:
    runtime = _prepare_runtime(
        tmp_path
    )

    completed = _run_diagnose(
        runtime
    )

    assert completed.returncode == 0, (
        completed.stdout
        + completed.stderr
    )

    payload = _payload(
        completed
    )

    assert payload["status"] == "healthy"
    assert payload["canonical_database"] == "healthy"
    assert payload["canonical_integrity_confirmed"] is True
    assert payload["normal_core_start_allowed"] is True
    assert payload["protected_scopes_locked"] is True
    assert payload["optional_components_required"] is False
    assert payload["issues"] == []

    assert _CANARY not in completed.stdout
    assert _CANARY not in completed.stderr


def test_missing_database_requires_recovery_without_creating_layout(
    tmp_path: Path,
) -> None:
    runtime = (
        tmp_path
        / "missing-runtime"
    )

    assert not runtime.exists()

    completed = _run_diagnose(
        runtime
    )

    assert completed.returncode == 4, (
        completed.stdout
        + completed.stderr
    )

    payload = _payload(
        completed
    )

    assert payload["status"] == "recovery-required"
    assert payload["canonical_integrity_confirmed"] is False
    assert payload["normal_core_start_allowed"] is False

    assert (
        "canonical.database_missing"
        in _issue_codes(payload)
    )

    assert not runtime.exists()


def test_corrupt_canonical_database_requires_recovery_and_is_unchanged(
    tmp_path: Path,
) -> None:
    runtime = _prepare_runtime(
        tmp_path
    )

    database_path = (
        runtime
        / "state"
        / "athena.db"
    )

    corrupt = (
        b"SLICE16F_CORRUPT_CANONICAL_DB_"
        b"MUST_NOT_BE_REPAIRED"
    )

    database_path.write_bytes(
        corrupt
    )

    completed = _run_diagnose(
        runtime
    )

    assert completed.returncode == 4, (
        completed.stdout
        + completed.stderr
    )

    payload = _payload(
        completed
    )

    assert payload["status"] == "recovery-required"
    assert payload["canonical_integrity_confirmed"] is False

    assert (
        "canonical.database_invalid_or_incompatible"
        in _issue_codes(payload)
    )

    assert database_path.read_bytes() == corrupt


def test_stale_canonical_fts_is_degraded_and_rebuildable(
    tmp_path: Path,
) -> None:
    runtime = _prepare_runtime(
        tmp_path
    )

    database_path = (
        runtime
        / "state"
        / "athena.db"
    )

    connection = sqlite3.connect(
        database_path
    )

    try:
        connection.execute(
            "DELETE FROM search_fts"
        )

        connection.execute(
            """
            UPDATE search_index_state
            SET indexed_commit_seq = 0
            WHERE singleton_id = 1
            """
        )

        connection.commit()

    finally:
        connection.close()

    completed = _run_diagnose(
        runtime
    )

    assert completed.returncode == 3, (
        completed.stdout
        + completed.stderr
    )

    payload = _payload(
        completed
    )

    assert payload["status"] == "degraded-derived"
    assert payload["canonical_integrity_confirmed"] is True
    assert payload["normal_core_start_allowed"] is True

    assert (
        "derived.canonical_fts_stale"
        in _issue_codes(payload)
    )


def test_missing_canonical_fts_structure_requires_recovery(
    tmp_path: Path,
) -> None:
    runtime = _prepare_runtime(
        tmp_path
    )

    database_path = (
        runtime
        / "state"
        / "athena.db"
    )

    connection = sqlite3.connect(
        database_path
    )

    try:
        connection.execute(
            "DROP TABLE search_fts"
        )
        connection.commit()

    finally:
        connection.close()

    completed = _run_diagnose(
        runtime
    )

    assert completed.returncode == 4, (
        completed.stdout
        + completed.stderr
    )

    payload = _payload(
        completed
    )

    assert payload["status"] == "recovery-required"
    assert payload["canonical_integrity_confirmed"] is True
    assert payload["normal_core_start_allowed"] is False

    assert (
        "derived.canonical_fts_invalid"
        in _issue_codes(payload)
    )


def test_corrupt_archive_store_requires_recovery_without_replacement(
    tmp_path: Path,
) -> None:
    runtime = _prepare_runtime(
        tmp_path
    )

    search_db = (
        runtime
        / "derived"
        / "search.db"
    )

    corrupt = (
        b"SLICE16F_CORRUPT_DERIVED_SEARCH_DB_"
        b"MUST_NOT_BE_RECREATED"
    )

    search_db.write_bytes(
        corrupt
    )

    completed = _run_diagnose(
        runtime
    )

    assert completed.returncode == 4, (
        completed.stdout
        + completed.stderr
    )

    payload = _payload(
        completed
    )

    assert payload["status"] == "recovery-required"
    assert payload["canonical_integrity_confirmed"] is True

    assert (
        "derived.archive_store_invalid"
        in _issue_codes(payload)
    )

    assert search_db.read_bytes() == corrupt


def test_plugin_import_failure_cannot_break_recovery_diagnostics(
    tmp_path: Path,
) -> None:
    runtime = _prepare_runtime(
        tmp_path
    )

    environment = os.environ.copy()
    environment["ATHENA_LOCAL_ROOT"] = str(
        runtime.resolve()
    )

    code = r"""
from __future__ import annotations

import importlib.abc
import json
import sys


class PoisonPluginFinder(importlib.abc.MetaPathFinder):
    def find_spec(
        self,
        fullname,
        path=None,
        target=None,
    ):
        del path
        del target

        if (
            fullname == "athena.plugins"
            or fullname.startswith("athena.plugins.")
            or fullname == "athena.plugin"
            or fullname.startswith("athena.plugin.")
        ):
            raise RuntimeError(
                "synthetic plugin subsystem failure"
            )

        return None


sys.meta_path.insert(
    0,
    PoisonPluginFinder(),
)

from athena.recovery_cli import main

raise SystemExit(
    main(
        [
            "diagnose",
        ]
    )
)
"""

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            code,
        ],
        text=True,
        capture_output=True,
        check=False,
        env=environment,
    )

    assert completed.returncode == 0, (
        completed.stdout
        + completed.stderr
    )

    payload = json.loads(
        completed.stdout
    )

    assert payload["status"] == "healthy"
    assert payload["optional_components_required"] is False
