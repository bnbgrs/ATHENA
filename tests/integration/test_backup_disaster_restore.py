from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

_CREATE = r"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.security.models import Argon2idParameters

runtime = Path(sys.argv[1])
backup_root = Path(sys.argv[2])
inputs = Path(sys.argv[3])
metadata_path = Path(sys.argv[4])

public_payload = (
    b"SLICE14F_PUBLIC_DISASTER_CANARY_"
    b"46C21AA9"
)

protected_payload = (
    b"SLICE14F_PROTECTED_DISASTER_CANARY_"
    b"8513DF72"
)

later_payload = (
    b"SLICE14F_LATER_SOURCE_"
    b"1A93B775"
)

password = (
    b"slice14f-disaster-password-8513DF72"
)

inputs.mkdir(
    parents=True,
    exist_ok=True,
)

public_path = (
    inputs
    / "public-disaster.bin"
)

protected_path = (
    inputs
    / "protected-disaster-secret.bin"
)

later_path = (
    inputs
    / "later-after-good-snapshot.bin"
)

public_path.write_bytes(
    public_payload
)

protected_path.write_bytes(
    protected_payload
)

later_path.write_bytes(
    later_payload
)

app = AthenaApplication(
    settings=AthenaSettings(
        local_root=runtime,
    )
)

app.start()

try:
    app.protected_content.initialize_password(
        password,
        parameters=Argon2idParameters(
            iterations=1,
            lanes=1,
            memory_cost_kib=8 * 1024,
            length=32,
        ),
    )

    scope = (
        app.protected_content.create_scope(
            password,
            neutral_label=(
                "Slice 14f disaster scope"
            ),
        )
    )

    app.protected_content.unlock_scope(
        scope.protection_scope_id,
        password,
    )

    public = (
        app.sources.capture_file(
            public_path
        )
    )

    protected = (
        app.sources.capture_protected_file(
            protected_path,
            protection_scope_id=(
                scope.protection_scope_id
            ),
        )
    )

    app.protected_content.lock_scope(
        scope.protection_scope_id
    )

    good = (
        app.backup.create_snapshot(
            target_root=backup_root,
        )
    )

    app.backup.verify_deep(
        good.snapshot_id
    )

    app.sources.capture_file(
        later_path
    )

    newest = (
        app.backup.create_snapshot(
            target_root=backup_root,
        )
    )

    app.backup.verify_deep(
        newest.snapshot_id
    )

    metadata_path.write_text(
        json.dumps(
            {
                "public_source_id": str(
                    public.source.source_id
                ),
                "protected_source_id": str(
                    protected.source.source_id
                ),
                "scope_id": str(
                    scope.protection_scope_id
                ),
                "password": (
                    password.decode("ascii")
                ),
                "public_payload_hex": (
                    public_payload.hex()
                ),
                "protected_payload_hex": (
                    protected_payload.hex()
                ),
                "good_snapshot": str(
                    good.snapshot_id
                ),
                "good_relative_path": (
                    good.relative_path
                ),
                "newest_snapshot": str(
                    newest.snapshot_id
                ),
                "newest_relative_path": (
                    newest.relative_path
                ),
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

finally:
    app.stop()
"""


_RESTORE = r"""
from __future__ import annotations

import sys
from pathlib import Path

from athena.backup.service import BackupRestoreError
from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication

controller_root = Path(sys.argv[1])
good_snapshot = Path(sys.argv[2])
bad_snapshot = Path(sys.argv[3])
restored_root = Path(sys.argv[4])
bad_destination = Path(sys.argv[5])
nonempty_destination = Path(sys.argv[6])

app = AthenaApplication(
    settings=AthenaSettings(
        local_root=controller_root,
    )
)

app.start()

try:
    try:
        app.backup.restore_path(
            bad_snapshot,
            destination_root=(
                bad_destination
            ),
        )
    except BackupRestoreError:
        pass
    else:
        raise AssertionError(
            "Corrupt snapshot was accepted "
            "as a restore candidate."
        )

    if bad_destination.exists():
        raise AssertionError(
            "Failed corrupt restore published "
            "a destination."
        )

    if tuple(
        bad_destination.parent.glob(
            f".{bad_destination.name}."
            "*.restore-partial"
        )
    ):
        raise AssertionError(
            "Failed corrupt restore left "
            "partial staging behind."
        )

    nonempty_destination.mkdir(
        parents=True,
        exist_ok=False,
    )

    sentinel = (
        nonempty_destination
        / "DO_NOT_TOUCH.txt"
    )

    sentinel.write_text(
        "existing destination",
        encoding="ascii",
    )

    try:
        app.backup.restore_path(
            good_snapshot,
            destination_root=(
                nonempty_destination
            ),
        )
    except BackupRestoreError:
        pass
    else:
        raise AssertionError(
            "Restore accepted an existing "
            "destination."
        )

    if (
        sentinel.read_text(
            encoding="ascii"
        )
        != "existing destination"
    ):
        raise AssertionError(
            "Existing destination was modified."
        )

    restored = (
        app.backup.restore_path(
            good_snapshot,
            destination_root=(
                restored_root
            ),
        )
    )

    if restored != restored_root.resolve():
        raise AssertionError(
            "Restore returned unexpected path."
        )

    if not (
        restored_root
        / "state"
        / "restore.complete"
    ).is_file():
        raise AssertionError(
            "Restore completion marker missing."
        )

    if tuple(
        restored_root.parent.glob(
            f".{restored_root.name}."
            "*.restore-partial"
        )
    ):
        raise AssertionError(
            "Successful restore left "
            "partial staging behind."
        )

finally:
    app.stop()
"""


_BOOT = r"""
from __future__ import annotations

import json
import sqlite3
import sys
import uuid
from pathlib import Path

from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.security.service import ProtectionScopeLockedError

restored_root = Path(sys.argv[1])
metadata_path = Path(sys.argv[2])

metadata = json.loads(
    metadata_path.read_text(
        encoding="utf-8"
    )
)

public_source_id = uuid.UUID(
    metadata["public_source_id"]
)

protected_source_id = uuid.UUID(
    metadata["protected_source_id"]
)

scope_id = uuid.UUID(
    metadata["scope_id"]
)

password = (
    metadata["password"].encode(
        "ascii"
    )
)

public_payload = bytes.fromhex(
    metadata["public_payload_hex"]
)

protected_payload = bytes.fromhex(
    metadata[
        "protected_payload_hex"
    ]
)

app = AthenaApplication(
    settings=AthenaSettings(
        local_root=restored_root,
    )
)

app.start()

try:
    public_path = (
        app.sources.verify(
            public_source_id
        )
    )

    if (
        public_path.read_bytes()
        != public_payload
    ):
        raise AssertionError(
            "Public source bytes were not "
            "recovered exactly."
        )

    if (
        app.protected_content
        .is_unlocked(scope_id)
    ):
        raise AssertionError(
            "Protected scope survived restore "
            "in unlocked state."
        )

    try:
        app.sources.read_protected_bytes(
            protected_source_id
        )
    except ProtectionScopeLockedError:
        pass
    else:
        raise AssertionError(
            "Protected restore did not fail "
            "closed while locked."
        )

    app.protected_content.unlock_scope(
        scope_id,
        password,
    )

    if (
        app.sources.read_protected_bytes(
            protected_source_id
        )
        != protected_payload
    ):
        raise AssertionError(
            "Protected source did not recover "
            "after explicit unlock."
        )

    statuses = (
        app.database.connection.execute(
            "SELECT DISTINCT status "
            "FROM backup_targets"
        ).fetchall()
    )

    if statuses and any(
        str(row["status"]) != "offline"
        for row in statuses
    ):
        raise AssertionError(
            "Restored backup target metadata "
            "was automatically trusted online."
        )

    pins = (
        app.database.connection.execute(
            "SELECT COUNT(*) "
            "FROM backup_snapshot_pins"
        ).fetchone()
    )

    if (
        pins is None
        or int(pins[0]) != 0
    ):
        raise AssertionError(
            "Backup pins survived "
            "disaster restore."
        )

    if not (
        restored_root
        / "state"
        / "restore.complete"
    ).is_file():
        raise AssertionError(
            "Restore marker disappeared "
            "after normal ATHENA startup."
        )

    forbidden = (
        protected_payload,
        password,
        b"protected-disaster-secret.bin",
    )

    for candidate in (
        restored_root.rglob("*")
    ):
        if not candidate.is_file():
            continue

        data = candidate.read_bytes()

        for needle in forbidden:
            if needle in data:
                raise AssertionError(
                    "Protected plaintext leaked "
                    "into persistent restore file: "
                    f"{candidate}"
                )

finally:
    app.stop()

database = sqlite3.connect(
    restored_root
    / "state"
    / "athena.db"
)

try:
    if (
        database.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0]
        != "ok"
    ):
        raise AssertionError(
            "Restored DB failed final "
            "integrity_check."
        )

    if database.execute(
        "PRAGMA foreign_key_check"
    ).fetchall():
        raise AssertionError(
            "Restored DB failed final "
            "foreign_key_check."
        )

finally:
    database.close()
"""


def _run(
    code: str,
    *args: Path,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            code,
            *(
                str(arg)
                for arg in args
            ),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, (
        f"Child process failed: "
        f"{result.returncode}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )

    return result


def test_process_separated_real_disaster_restore(
    tmp_path: Path,
) -> None:
    source_runtime = (
        tmp_path
        / "destroyed-runtime"
    )

    backup_root = (
        tmp_path
        / "backup-medium"
    )

    inputs = (
        tmp_path
        / "inputs"
    )

    metadata_path = (
        tmp_path
        / "metadata.json"
    )

    controller_root = (
        tmp_path
        / "fresh-controller"
    )

    restored_root = (
        tmp_path
        / "restored-runtime"
    )

    bad_destination = (
        tmp_path
        / "must-not-publish"
    )

    nonempty_destination = (
        tmp_path
        / "existing-root"
    )

    _run(
        _CREATE,
        source_runtime,
        backup_root,
        inputs,
        metadata_path,
    )

    metadata = json.loads(
        metadata_path.read_text(
            encoding="utf-8"
        )
    )

    good_snapshot = (
        backup_root
        / metadata[
            "good_relative_path"
        ]
    )

    bad_snapshot = (
        backup_root
        / metadata[
            "newest_relative_path"
        ]
    )

    assert (
        good_snapshot
        / "complete.marker"
    ).is_file()

    assert (
        bad_snapshot
        / "complete.marker"
    ).is_file()

    # Simulate total loss of the original runtime.
    shutil.rmtree(
        source_runtime
    )

    assert not source_runtime.exists()

    # Corrupt the newest restore point while keeping
    # the previous verified restore point intact.
    manifest_path = (
        bad_snapshot
        / "manifest.json"
    )

    manifest_path.write_bytes(
        manifest_path.read_bytes()
        + b"\nCORRUPTED-SLICE14F"
    )

    _run(
        _RESTORE,
        controller_root,
        good_snapshot,
        bad_snapshot,
        restored_root,
        bad_destination,
        nonempty_destination,
    )

    assert restored_root.is_dir()
    assert not bad_destination.exists()

    assert (
        nonempty_destination
        / "DO_NOT_TOUCH.txt"
    ).read_text(
        encoding="ascii"
    ) == "existing destination"

    # Backup medium disappears after restore.
    # The restored ATHENA instance must still boot
    # and operate solely from its restored local root.
    offline_backup = (
        tmp_path
        / "backup-medium-offline"
    )

    backup_root.rename(
        offline_backup
    )

    assert not backup_root.exists()
    assert offline_backup.exists()

    _run(
        _BOOT,
        restored_root,
        metadata_path,
    )
