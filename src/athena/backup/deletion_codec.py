"""Pure deletion-ledger serialization helpers for backup targets."""

from __future__ import annotations

import hashlib
import uuid

from athena.backup.errors import BackupRestoreError
from athena.backup.json_codec import _canonical_json
from athena.lifecycle.deletion import DeletionLedgerRecord


class DeletionLedgerCodecMixin:
    """Stateless deletion-ledger codec inherited by BackupService."""

    DELETION_LEDGER_RECORD_FORMAT_VERSION: int
    DELETION_LEDGER_HEAD_FORMAT_VERSION: int

    @classmethod
    def _deletion_records_digest(
        cls,
        records: tuple[
            DeletionLedgerRecord,
            ...,
        ],
    ) -> str:
        hasher = hashlib.sha256()

        for record in records:
            encoded = _canonical_json(
                cls._deletion_record_payload(
                    record
                )
            ).encode(
                "utf-8"
            )

            hasher.update(
                len(encoded).to_bytes(
                    8,
                    byteorder="big",
                    signed=False,
                )
            )

            hasher.update(
                encoded
            )

        return hasher.hexdigest()

    @classmethod
    def _deletion_head_payload(
        cls,
        *,
        target_id: uuid.UUID,
        records: tuple[
            DeletionLedgerRecord,
            ...,
        ],
    ) -> dict[
        str,
        object,
    ]:
        watermark = (
            records[-1].ledger_seq
            if records
            else 0
        )

        return {
            "format_version": (
                cls.DELETION_LEDGER_HEAD_FORMAT_VERSION
            ),
            "record_count": len(
                records
            ),
            "records_sha256": (
                cls._deletion_records_digest(
                    records
                )
            ),
            "target_id": str(
                target_id
            ),
            "watermark": watermark,
        }

    @classmethod
    def _deletion_record_name(
        cls,
        record: DeletionLedgerRecord,
    ) -> str:
        """Return immutable identity bound to every canonical record field."""
        canonical_payload = _canonical_json(
            cls._deletion_record_payload(
                record
            )
        ).encode(
            "utf-8"
        )

        payload_sha256 = hashlib.sha256(
            canonical_payload
        ).hexdigest()

        return (
            f"{record.ledger_seq:020d}-"
            f"{record.deletion_id}-"
            f"{payload_sha256}.json"
        )

    @classmethod
    def _deletion_record_payload(
        cls,
        record: DeletionLedgerRecord,
    ) -> dict[
        str,
        object,
    ]:
        return {
            "deleted_at_us": (
                record.deleted_at_us
            ),
            "deleted_by_actor_id": str(
                record.deleted_by_actor_id
            ),
            "deletion_commit_seq": (
                record.deletion_commit_seq
            ),
            "deletion_id": str(
                record.deletion_id
            ),
            "entity_id": str(
                record.entity_id
            ),
            "entity_type": (
                record.entity_type
            ),
            "format_version": (
                cls.DELETION_LEDGER_RECORD_FORMAT_VERSION
            ),
            "ledger_seq": (
                record.ledger_seq
            ),
        }

    @classmethod
    def _deletion_record_from_payload(
        cls,
        payload: dict[
            str,
            object,
        ],
    ) -> DeletionLedgerRecord:
        required_keys = {
            "deleted_at_us",
            "deleted_by_actor_id",
            "deletion_commit_seq",
            "deletion_id",
            "entity_id",
            "entity_type",
            "format_version",
            "ledger_seq",
        }

        if set(
            payload
        ) != required_keys:
            raise BackupRestoreError(
                "Backup deletion-ledger record "
                "contains unexpected fields."
            )

        format_version = payload[
            "format_version"
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
            != cls.DELETION_LEDGER_RECORD_FORMAT_VERSION
        ):
            raise BackupRestoreError(
                "Backup deletion-ledger record "
                "format version is unsupported."
            )

        def integer(
            key: str,
            *,
            minimum: int,
        ) -> int:
            value = payload[
                key
            ]

            if (
                not isinstance(
                    value,
                    int,
                )
                or isinstance(
                    value,
                    bool,
                )
                or value < minimum
            ):
                raise BackupRestoreError(
                    f"Backup deletion-ledger field "
                    f"{key!r} is invalid."
                )

            return value

        entity_type = payload[
            "entity_type"
        ]

        if (
            not isinstance(
                entity_type,
                str,
            )
            or not entity_type.strip()
        ):
            raise BackupRestoreError(
                "Backup deletion-ledger entity_type is invalid."
            )

        try:
            return DeletionLedgerRecord(
                ledger_seq=integer(
                    "ledger_seq",
                    minimum=1,
                ),
                deletion_id=uuid.UUID(
                    str(
                        payload[
                            "deletion_id"
                        ]
                    )
                ),
                entity_id=uuid.UUID(
                    str(
                        payload[
                            "entity_id"
                        ]
                    )
                ),
                entity_type=entity_type,
                deleted_at_us=integer(
                    "deleted_at_us",
                    minimum=0,
                ),
                deletion_commit_seq=integer(
                    "deletion_commit_seq",
                    minimum=1,
                ),
                deleted_by_actor_id=uuid.UUID(
                    str(
                        payload[
                            "deleted_by_actor_id"
                        ]
                    )
                ),
            )

        except (
            ValueError,
            AttributeError,
        ) as exc:
            raise BackupRestoreError(
                "Backup deletion-ledger UUID is invalid."
            ) from exc
