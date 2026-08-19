"""Deletion-ledger target filesystem boundary for backups."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from athena.backup.deletion_codec import DeletionLedgerCodecMixin
from athena.backup.errors import BackupRestoreError
from athena.backup.json_codec import _canonical_json
from athena.common.ids import new_uuid7
from athena.lifecycle.deletion import DeletionLedgerRecord
from athena.storage.durable_fs import durable_mkdir, durable_replace


class DeletionLedgerStorageMixin(DeletionLedgerCodecMixin):
    """Filesystem I/O for deletion-ledger sidecars on backup targets."""

    DELETION_LEDGER_DIR: str
    DELETION_LEDGER_RECORDS_DIR: str
    DELETION_LEDGER_HEAD_NAME: str

    def _read_target_descriptor(
        self,
        target: Path,
    ) -> uuid.UUID | None:
        raise NotImplementedError

    def _read_target_deletion_records(
        self,
        target: Path,
    ) -> tuple[
        DeletionLedgerRecord,
        ...,
    ]:
        ledger_root = (
            target
            / self.DELETION_LEDGER_DIR
        )

        if not ledger_root.exists():
            return ()

        if (
            ledger_root.is_symlink()
            or not ledger_root.is_dir()
        ):
            raise BackupRestoreError(
                "Backup target deletion-ledger root is unsafe."
            )

        allowed_names = {
            self.DELETION_LEDGER_RECORDS_DIR,
            self.DELETION_LEDGER_HEAD_NAME,
        }

        unexpected = tuple(
            item
            for item in ledger_root.iterdir()
            if item.name not in allowed_names
        )

        if unexpected:
            raise BackupRestoreError(
                "Backup target deletion-ledger root "
                "contains unexpected entries."
            )

        head_path = (
            ledger_root
            / self.DELETION_LEDGER_HEAD_NAME
        )

        if (
            head_path.is_symlink()
            or not head_path.is_file()
        ):
            raise BackupRestoreError(
                "Existing backup deletion ledger "
                "has no valid integrity head."
            )

        records_root = (
            ledger_root
            / self.DELETION_LEDGER_RECORDS_DIR
        )

        records: list[
            DeletionLedgerRecord
        ] = []

        if records_root.exists():
            if (
                records_root.is_symlink()
                or not records_root.is_dir()
            ):
                raise BackupRestoreError(
                    "Backup target deletion records "
                    "directory is unsafe."
                )

            for path in sorted(
                records_root.iterdir(),
                key=lambda item: item.name,
            ):
                if (
                    path.is_symlink()
                    or not path.is_file()
                ):
                    raise BackupRestoreError(
                        "Backup deletion ledger contains "
                        "a non-regular record."
                    )

                try:
                    raw = path.read_bytes()
                    payload = json.loads(
                        raw.decode(
                            "utf-8"
                        )
                    )
                except (
                    OSError,
                    UnicodeDecodeError,
                    json.JSONDecodeError,
                ) as exc:
                    raise BackupRestoreError(
                        "Backup deletion-ledger record "
                        "cannot be decoded."
                    ) from exc

                if not isinstance(
                    payload,
                    dict,
                ):
                    raise BackupRestoreError(
                        "Backup deletion-ledger record "
                        "must be a JSON object."
                    )

                canonical = (
                    _canonical_json(
                        payload
                    ).encode(
                        "utf-8"
                    )
                )

                if canonical != raw:
                    raise BackupRestoreError(
                        "Backup deletion-ledger record "
                        "is not canonical."
                    )

                record = (
                    self._deletion_record_from_payload(
                        payload
                    )
                )

                expected_name = (
                    self._deletion_record_name(
                        record
                    )
                )

                if path.name != expected_name:
                    raise BackupRestoreError(
                        "Backup deletion-ledger filename "
                        "does not match its full record identity."
                    )

                records.append(
                    record
                )

        for index, record in enumerate(
            records,
            start=1,
        ):
            if record.ledger_seq != index:
                raise BackupRestoreError(
                    "Backup deletion ledger is not "
                    "a contiguous sequence from 1."
                )

        result = tuple(
            records
        )

        self._validate_target_deletion_head(
            target=target,
            records=result,
        )

        return result

    def _write_target_deletion_head(
        self,
        *,
        target: Path,
        target_id: uuid.UUID,
        records: tuple[
            DeletionLedgerRecord,
            ...,
        ],
    ) -> None:
        descriptor_id = (
            self._read_target_descriptor(
                target
            )
        )

        if descriptor_id != target_id:
            raise BackupRestoreError(
                "Cannot publish deletion-ledger head: "
                "backup target identity mismatch."
            )

        ledger_root = (
            target
            / self.DELETION_LEDGER_DIR
        )

        durable_mkdir(
            ledger_root,
            parents=True,
            exist_ok=True,
        )

        if (
            ledger_root.is_symlink()
            or not ledger_root.is_dir()
        ):
            raise BackupRestoreError(
                "Backup deletion-ledger root is unsafe."
            )

        payload = (
            self._deletion_head_payload(
                target_id=target_id,
                records=records,
            )
        )

        encoded = _canonical_json(
            payload
        ).encode(
            "utf-8"
        )

        destination = (
            ledger_root
            / self.DELETION_LEDGER_HEAD_NAME
        )

        temporary = (
            destination.with_name(
                f".{destination.name}."
                f"{new_uuid7()}.partial"
            )
        )

        try:
            with temporary.open(
                "xb"
            ) as handle:
                handle.write(
                    encoded
                )
                handle.flush()
                os.fsync(
                    handle.fileno()
                )

            durable_replace(
                temporary,
                destination,
            )

        finally:
            temporary.unlink(
                missing_ok=True
            )

        if (
            destination.is_symlink()
            or not destination.is_file()
            or destination.read_bytes()
            != encoded
        ):
            raise BackupRestoreError(
                "Deletion-ledger integrity head failed "
                "post-publication verification."
            )

    def _validate_target_deletion_head(
        self,
        *,
        target: Path,
        records: tuple[
            DeletionLedgerRecord,
            ...,
        ],
    ) -> None:
        ledger_root = (
            target
            / self.DELETION_LEDGER_DIR
        )

        head_path = (
            ledger_root
            / self.DELETION_LEDGER_HEAD_NAME
        )

        try:
            raw = head_path.read_bytes()
            payload = json.loads(
                raw.decode(
                    "utf-8"
                )
            )
        except (
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as exc:
            raise BackupRestoreError(
                "Backup deletion-ledger integrity head "
                "cannot be decoded."
            ) from exc

        if not isinstance(
            payload,
            dict,
        ):
            raise BackupRestoreError(
                "Backup deletion-ledger integrity head "
                "must be a JSON object."
            )

        canonical = _canonical_json(
            payload
        ).encode(
            "utf-8"
        )

        if canonical != raw:
            raise BackupRestoreError(
                "Backup deletion-ledger integrity head "
                "is not canonical."
            )

        required_keys = {
            "format_version",
            "record_count",
            "records_sha256",
            "target_id",
            "watermark",
        }

        if set(
            payload
        ) != required_keys:
            raise BackupRestoreError(
                "Backup deletion-ledger integrity head "
                "contains unexpected fields."
            )

        format_version = payload[
            "format_version"
        ]

        record_count = payload[
            "record_count"
        ]

        watermark = payload[
            "watermark"
        ]

        digest = payload[
            "records_sha256"
        ]

        if (
            not isinstance(
                format_version,
                int,
            )
            or isinstance(
                format_version,
                bool,
            )
            or format_version
            != self.DELETION_LEDGER_HEAD_FORMAT_VERSION
        ):
            raise BackupRestoreError(
                "Backup deletion-ledger integrity head "
                "format is unsupported."
            )

        if (
            not isinstance(
                record_count,
                int,
            )
            or isinstance(
                record_count,
                bool,
            )
            or record_count < 0
        ):
            raise BackupRestoreError(
                "Backup deletion-ledger head "
                "record_count is invalid."
            )

        if (
            not isinstance(
                watermark,
                int,
            )
            or isinstance(
                watermark,
                bool,
            )
            or watermark < 0
        ):
            raise BackupRestoreError(
                "Backup deletion-ledger head "
                "watermark is invalid."
            )

        if (
            not isinstance(
                digest,
                str,
            )
            or len(digest) != 64
        ):
            raise BackupRestoreError(
                "Backup deletion-ledger head "
                "digest is invalid."
            )

        try:
            bytes.fromhex(
                digest
            )
        except ValueError as exc:
            raise BackupRestoreError(
                "Backup deletion-ledger head "
                "digest is not hexadecimal."
            ) from exc

        try:
            head_target_id = uuid.UUID(
                str(
                    payload[
                        "target_id"
                    ]
                )
            )
        except (
            ValueError,
            AttributeError,
        ) as exc:
            raise BackupRestoreError(
                "Backup deletion-ledger head "
                "target ID is invalid."
            ) from exc

        descriptor_id = (
            self._read_target_descriptor(
                target
            )
        )

        if descriptor_id is None:
            raise BackupRestoreError(
                "Backup deletion-ledger exists on a "
                "target without an identity descriptor."
            )

        if head_target_id != descriptor_id:
            raise BackupRestoreError(
                "Backup deletion-ledger head belongs "
                "to a different backup target."
            )

        expected = (
            self._deletion_head_payload(
                target_id=descriptor_id,
                records=records,
            )
        )

        if payload != expected:
            raise BackupRestoreError(
                "Backup deletion ledger does not match "
                "its integrity head."
            )

    def _write_target_deletion_record(
        self,
        target: Path,
        record: DeletionLedgerRecord,
    ) -> None:
        records_root = (
            target
            / self.DELETION_LEDGER_DIR
            / self.DELETION_LEDGER_RECORDS_DIR
        )

        durable_mkdir(
            records_root,
            parents=True,
            exist_ok=True,
        )

        if (
            records_root.is_symlink()
            or not records_root.is_dir()
        ):
            raise BackupRestoreError(
                "Backup deletion records directory is unsafe."
            )

        payload = (
            self._deletion_record_payload(
                record
            )
        )

        encoded = (
            _canonical_json(
                payload
            ).encode(
                "utf-8"
            )
        )

        destination = (
            records_root
            / self._deletion_record_name(
                record
            )
        )

        if destination.exists():
            if (
                destination.is_symlink()
                or not destination.is_file()
            ):
                raise BackupRestoreError(
                    "Existing deletion-ledger record is unsafe."
                )

            if destination.read_bytes() != encoded:
                raise BackupRestoreError(
                    "Existing deletion-ledger record "
                    "disagrees with the durable ledger."
                )

            return

        temporary = (
            destination.with_name(
                f".{destination.name}."
                f"{new_uuid7()}.partial"
            )
        )

        try:
            with temporary.open(
                "xb"
            ) as handle:
                handle.write(
                    encoded
                )
                handle.flush()
                os.fsync(
                    handle.fileno()
                )

            durable_replace(
                temporary,
                destination,
            )

        finally:
            temporary.unlink(
                missing_ok=True
            )

        if destination.read_bytes() != encoded:
            raise BackupRestoreError(
                "Deletion-ledger record failed "
                "post-publication verification."
            )
