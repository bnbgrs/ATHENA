from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from athena.backup.service import BackupRestoreError
from athena.common.ids import uuid_to_blob
from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.lifecycle.deletion import (
    current_deletion_watermark,
)


def _app(
    root: Path,
) -> AthenaApplication:
    app = AthenaApplication(
        settings=AthenaSettings(
            local_root=root,
        )
    )

    app.start()

    return app


def _record_files(
    target: Path,
) -> tuple[
    Path,
    ...,
]:
    root = (
        target
        / "deletion-ledger"
        / "records"
    )

    if not root.is_dir():
        return ()

    return tuple(
        sorted(
            root.glob(
                "*.json"
            )
        )
    )


def test_deletion_is_immediately_propagated_to_all_reachable_targets(
    tmp_path: Path,
) -> None:
    app = _app(
        tmp_path
        / "runtime"
    )

    first_target = (
        tmp_path
        / "backup-a"
    )

    second_target = (
        tmp_path
        / "backup-b"
    )

    try:
        first = (
            app.backup.register_target(
                first_target
            )
        )

        second = (
            app.backup.register_target(
                second_target
            )
        )

        secret = (
            "SLICE15B_DO_NOT_COPY_PAYLOAD_"
            "A13FD87C"
        )

        memory = (
            app.personal_memory.remember(
                content=secret
            )
        )

        app.personal_memory.delete(
            memory.memory_id
        )

        for target_id, root in (
            (
                first.target_id,
                first_target,
            ),
            (
                second.target_id,
                second_target,
            ),
        ):
            state = (
                app.backup.get_target(
                    target_id
                )
            )

            assert state.status == "active"
            assert (
                state.deletion_ledger_watermark
                == 1
            )
            assert (
                state.deletion_sync_pending
                is False
            )

            files = (
                _record_files(
                    root
                )
            )

            assert len(files) == 1

            raw = files[0].read_bytes()

            assert (
                secret.encode(
                    "utf-8"
                )
                not in raw
            )

            payload = json.loads(
                raw.decode(
                    "utf-8"
                )
            )

            assert (
                payload[
                    "entity_id"
                ]
                == str(
                    memory.memory_id
                )
            )

            assert (
                set(payload)
                == {
                    "deleted_at_us",
                    "deleted_by_actor_id",
                    "deletion_commit_seq",
                    "deletion_id",
                    "entity_id",
                    "entity_type",
                    "format_version",
                    "ledger_seq",
                }
            )

    finally:
        app.stop()


def test_offline_target_remains_pending_and_startup_catches_up(
    tmp_path: Path,
) -> None:
    runtime = (
        tmp_path
        / "runtime"
    )

    target = (
        tmp_path
        / "backup"
    )

    disconnected = (
        tmp_path
        / "backup-disconnected"
    )

    app = _app(
        runtime
    )

    registered = (
        app.backup.register_target(
            target
        )
    )

    memory = (
        app.personal_memory.remember(
            content="offline deletion"
        )
    )

    target.rename(
        disconnected
    )

    app.personal_memory.delete(
        memory.memory_id
    )

    pending = (
        app.backup.get_target(
            registered.target_id
        )
    )

    assert pending.status == "offline"
    assert (
        pending.deletion_ledger_watermark
        == 0
    )
    assert (
        pending.deletion_sync_pending
        is True
    )

    app.stop()

    disconnected.rename(
        target
    )

    restarted = _app(
        runtime
    )

    try:
        caught_up = (
            restarted.backup.get_target(
                registered.target_id
            )
        )

        assert caught_up.status == "active"
        assert (
            caught_up.deletion_ledger_watermark
            == 1
        )
        assert (
            caught_up.deletion_sync_pending
            is False
        )

        files = (
            _record_files(
                target
            )
        )

        assert len(files) == 1

    finally:
        restarted.stop()


def test_disaster_restore_path_applies_deletion_written_after_snapshot(
    tmp_path: Path,
) -> None:
    runtime = (
        tmp_path
        / "runtime"
    )

    target = (
        tmp_path
        / "backup"
    )

    restored_root = (
        tmp_path
        / "restored"
    )

    controller_root = (
        tmp_path
        / "fresh-controller"
    )

    app = _app(
        runtime
    )

    try:
        memory = (
            app.personal_memory.remember(
                content=(
                    "must not resurrect "
                    "after total runtime loss"
                )
            )
        )

        snapshot = (
            app.backup.create_snapshot(
                target_root=target
            )
        )

        assert (
            snapshot.deletion_ledger_watermark
            == 0
        )

        snapshot_root = (
            target
            / snapshot.relative_path
        )

        app.personal_memory.delete(
            memory.memory_id
        )

        assert (
            len(
                _record_files(
                    target
                )
            )
            == 1
        )

    finally:
        app.stop()

    shutil.rmtree(
        runtime
    )

    controller = _app(
        controller_root
    )

    try:
        controller.backup.restore_path(
            snapshot_root,
            destination_root=restored_root,
        )

    finally:
        controller.stop()

    restored = sqlite3.connect(
        restored_root
        / "state"
        / "athena.db"
    )

    restored.row_factory = (
        sqlite3.Row
    )

    try:
        entity = restored.execute(
            """
            SELECT lifecycle_state
            FROM entity_registry
            WHERE entity_id = ?
            """,
            (
                uuid_to_blob(
                    memory.memory_id
                ),
            ),
        ).fetchone()

        assert entity is not None

        assert (
            entity[
                "lifecycle_state"
            ]
            == "deleted"
        )

        assert (
            current_deletion_watermark(
                restored
            )
            == 1
        )

        assert (
            restored.execute(
                "PRAGMA foreign_key_check"
            ).fetchall()
            == []
        )

    finally:
        restored.close()

    status = json.loads(
        (
            restored_root
            / "state"
            / "restore.deletion-ledger.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    assert status == {
        "available_watermark": 1,
        "currentness_guaranteed": False,
        "format_version": 1,
        "snapshot_watermark": 0,
        "source": "target_sidecar",
    }


def test_corrupt_target_deletion_record_blocks_disaster_restore(
    tmp_path: Path,
) -> None:
    runtime = (
        tmp_path
        / "runtime"
    )

    target = (
        tmp_path
        / "backup"
    )

    destination = (
        tmp_path
        / "restore-must-not-exist"
    )

    controller_root = (
        tmp_path
        / "controller"
    )

    app = _app(
        runtime
    )

    try:
        memory = (
            app.personal_memory.remember(
                content="tamper test"
            )
        )

        snapshot = (
            app.backup.create_snapshot(
                target_root=target
            )
        )

        snapshot_root = (
            target
            / snapshot.relative_path
        )

        app.personal_memory.delete(
            memory.memory_id
        )

        files = (
            _record_files(
                target
            )
        )

        assert len(files) == 1

        payload = json.loads(
            files[0].read_text(
                encoding="utf-8"
            )
        )

        payload[
            "entity_id"
        ] = str(
            snapshot.snapshot_id
        )

        files[0].write_text(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(
                    ",",
                    ":",
                ),
            ),
            encoding="utf-8",
        )

    finally:
        app.stop()

    controller = _app(
        controller_root
    )

    try:
        with pytest.raises(
            BackupRestoreError
        ):
            controller.backup.restore_path(
                snapshot_root,
                destination_root=destination,
            )

        assert (
            not destination.exists()
        )

    finally:
        controller.stop()



def test_target_ledger_head_binds_complete_record_sequence(
    tmp_path: Path,
) -> None:
    app = _app(
        tmp_path
        / "runtime-head"
    )

    target = (
        tmp_path
        / "backup-head"
    )

    try:
        registered = (
            app.backup.register_target(
                target
            )
        )

        first = (
            app.personal_memory.remember(
                content="head first"
            )
        )

        second = (
            app.personal_memory.remember(
                content="head second"
            )
        )

        app.personal_memory.delete(
            first.memory_id
        )

        app.personal_memory.delete(
            second.memory_id
        )

        files = (
            _record_files(
                target
            )
        )

        assert len(files) == 2

        head_path = (
            target
            / "deletion-ledger"
            / "head.json"
        )

        assert head_path.is_file()

        raw = head_path.read_bytes()

        payload = json.loads(
            raw.decode(
                "utf-8"
            )
        )

        assert (
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(
                    ",",
                    ":",
                ),
            ).encode(
                "utf-8"
            )
            == raw
        )

        assert payload[
            "format_version"
        ] == 1

        assert payload[
            "record_count"
        ] == 2

        assert payload[
            "watermark"
        ] == 2

        assert payload[
            "target_id"
        ] == str(
            registered.target_id
        )

        assert (
            isinstance(
                payload[
                    "records_sha256"
                ],
                str,
            )
            and len(
                payload[
                    "records_sha256"
                ]
            )
            == 64
        )

        state = (
            app.backup.get_target(
                registered.target_id
            )
        )

        assert (
            state.deletion_ledger_watermark
            == 2
        )

        assert (
            state.deletion_sync_pending
            is False
        )

    finally:
        app.stop()


def test_truncated_target_ledger_is_rejected_by_head(
    tmp_path: Path,
) -> None:
    runtime = (
        tmp_path
        / "runtime-truncated"
    )

    target = (
        tmp_path
        / "backup-truncated"
    )

    destination = (
        tmp_path
        / "restore-truncated"
    )

    controller_root = (
        tmp_path
        / "controller-truncated"
    )

    app = _app(
        runtime
    )

    try:
        first = (
            app.personal_memory.remember(
                content="truncate first"
            )
        )

        second = (
            app.personal_memory.remember(
                content="truncate second"
            )
        )

        snapshot = (
            app.backup.create_snapshot(
                target_root=target
            )
        )

        snapshot_root = (
            target
            / snapshot.relative_path
        )

        app.personal_memory.delete(
            first.memory_id
        )

        app.personal_memory.delete(
            second.memory_id
        )

        files = (
            _record_files(
                target
            )
        )

        assert len(files) == 2

        files[-1].unlink()

    finally:
        app.stop()

    controller = _app(
        controller_root
    )

    try:
        with pytest.raises(
            BackupRestoreError
        ):
            controller.backup.restore_path(
                snapshot_root,
                destination_root=destination,
            )

        assert (
            not destination.exists()
        )

    finally:
        controller.stop()


def test_rewritten_and_renamed_record_is_rejected_by_head(
    tmp_path: Path,
) -> None:
    runtime = (
        tmp_path
        / "runtime-rewrite"
    )

    target = (
        tmp_path
        / "backup-rewrite"
    )

    destination = (
        tmp_path
        / "restore-rewrite"
    )

    controller_root = (
        tmp_path
        / "controller-rewrite"
    )

    app = _app(
        runtime
    )

    try:
        memory = (
            app.personal_memory.remember(
                content="rewrite detection"
            )
        )

        snapshot = (
            app.backup.create_snapshot(
                target_root=target
            )
        )

        snapshot_root = (
            target
            / snapshot.relative_path
        )

        app.personal_memory.delete(
            memory.memory_id
        )

        files = (
            _record_files(
                target
            )
        )

        assert len(files) == 1

        original = files[0]

        payload = json.loads(
            original.read_text(
                encoding="utf-8"
            )
        )

        payload[
            "entity_id"
        ] = str(
            snapshot.snapshot_id
        )

        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(
                ",",
                ":",
            ),
        ).encode(
            "utf-8"
        )

        forged_hash = hashlib.sha256(
            encoded
        ).hexdigest()

        forged_name = (
            f"{int(payload['ledger_seq']):020d}-"
            f"{payload['deletion_id']}-"
            f"{forged_hash}.json"
        )

        forged = (
            original.with_name(
                forged_name
            )
        )

        forged.write_bytes(
            encoded
        )

        original.unlink()

    finally:
        app.stop()

    controller = _app(
        controller_root
    )

    try:
        with pytest.raises(
            BackupRestoreError
        ):
            controller.backup.restore_path(
                snapshot_root,
                destination_root=destination,
            )

        assert (
            not destination.exists()
        )

    finally:
        controller.stop()


def test_target_identity_mismatch_in_ledger_head_blocks_restore(
    tmp_path: Path,
) -> None:
    runtime = (
        tmp_path
        / "runtime-head-id"
    )

    target = (
        tmp_path
        / "backup-head-id"
    )

    destination = (
        tmp_path
        / "restore-head-id"
    )

    controller_root = (
        tmp_path
        / "controller-head-id"
    )

    app = _app(
        runtime
    )

    try:
        memory = (
            app.personal_memory.remember(
                content="target identity binding"
            )
        )

        snapshot = (
            app.backup.create_snapshot(
                target_root=target
            )
        )

        snapshot_root = (
            target
            / snapshot.relative_path
        )

        app.personal_memory.delete(
            memory.memory_id
        )

        head_path = (
            target
            / "deletion-ledger"
            / "head.json"
        )

        payload = json.loads(
            head_path.read_text(
                encoding="utf-8"
            )
        )

        payload[
            "target_id"
        ] = str(
            snapshot.snapshot_id
        )

        head_path.write_text(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(
                    ",",
                    ":",
                ),
            ),
            encoding="utf-8",
        )

    finally:
        app.stop()

    controller = _app(
        controller_root
    )

    try:
        with pytest.raises(
            BackupRestoreError
        ):
            controller.backup.restore_path(
                snapshot_root,
                destination_root=destination,
            )

        assert (
            not destination.exists()
        )

    finally:
        controller.stop()


def test_legacy_medium_without_sidecar_restores_with_clear_limitation(
    tmp_path: Path,
) -> None:
    runtime = (
        tmp_path
        / "runtime-legacy-medium"
    )

    target = (
        tmp_path
        / "backup-legacy-medium"
    )

    destination = (
        tmp_path
        / "restore-legacy-medium"
    )

    controller_root = (
        tmp_path
        / "controller-legacy-medium"
    )

    app = _app(
        runtime
    )

    try:
        app.personal_memory.remember(
            content="legacy medium retained content"
        )

        snapshot = (
            app.backup.create_snapshot(
                target_root=target
            )
        )

        snapshot_root = (
            target
            / snapshot.relative_path
        )

    finally:
        app.stop()

    shutil.rmtree(
        target
        / "deletion-ledger"
    )

    controller = _app(
        controller_root
    )

    try:
        controller.backup.restore_path(
            snapshot_root,
            destination_root=destination,
        )

    finally:
        controller.stop()

    status = json.loads(
        (
            destination
            / "state"
            / "restore.deletion-ledger.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    assert status[
        "source"
    ] == "snapshot_only"

    assert (
        status[
            "currentness_guaranteed"
        ]
        is False
    )

    assert status[
        "available_watermark"
    ] == 0

    assert status[
        "snapshot_watermark"
    ] == 0
