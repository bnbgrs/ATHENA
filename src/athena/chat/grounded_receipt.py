"""Durable exact replay receipts for structured Grounded chat responses."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import dataclass

from athena.common.ids import uuid_from_blob, uuid_to_blob
from athena.common.time import utc_now_us
from athena.storage.database import SQLiteDatabase

GROUNDED_RESPONSE_RECEIPT_FORMAT_VERSION = 1


class GroundedResponseReceiptConflictError(RuntimeError):
    """Raised when an operation ID is reused for different Grounded output."""


class GroundedResponseReceiptCorruptionError(RuntimeError):
    """Raised when persisted receipt bytes fail their immutable checksum."""


@dataclass(frozen=True, slots=True)
class GroundedResponseReceipt:
    """One immutable exact-replay projection for a completed Grounded send."""

    operation_id: uuid.UUID
    chat_id: uuid.UUID
    processing_run_id: uuid.UUID
    payload_json: str
    payload_sha256: str
    format_version: int
    created_at_us: int


def _canonical_payload(
    payload_json: str,
) -> tuple[str, str]:
    try:
        payload = json.loads(
            payload_json
        )
    except json.JSONDecodeError as exc:
        raise ValueError(
            "Grounded response receipt payload must be valid JSON."
        ) from exc

    if not isinstance(
        payload,
        dict,
    ):
        raise ValueError(
            "Grounded response receipt payload must be a JSON object."
        )

    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(
            ",",
            ":",
        ),
    )

    digest = hashlib.sha256(
        canonical.encode(
            "utf-8"
        )
    ).hexdigest()

    return (
        canonical,
        digest,
    )


def _receipt_from_row(
    row: sqlite3.Row,
) -> GroundedResponseReceipt:
    receipt = GroundedResponseReceipt(
        operation_id=uuid_from_blob(
            bytes(row[0])
        ),
        chat_id=uuid_from_blob(
            bytes(row[1])
        ),
        processing_run_id=uuid_from_blob(
            bytes(row[2])
        ),
        payload_json=str(
            row[3]
        ),
        payload_sha256=str(
            row[4]
        ),
        format_version=int(
            row[5]
        ),
        created_at_us=int(
            row[6]
        ),
    )

    if (
        receipt.format_version
        != GROUNDED_RESPONSE_RECEIPT_FORMAT_VERSION
    ):
        raise GroundedResponseReceiptCorruptionError(
            "Grounded response receipt format version is unsupported."
        )

    try:
        canonical, digest = _canonical_payload(
            receipt.payload_json
        )
    except ValueError as exc:
        raise GroundedResponseReceiptCorruptionError(
            "Grounded response receipt contains invalid JSON."
        ) from exc

    if (
        canonical != receipt.payload_json
        or digest != receipt.payload_sha256
    ):
        raise GroundedResponseReceiptCorruptionError(
            "Grounded response receipt checksum verification failed."
        )

    return receipt


class GroundedResponseReceiptRepository:
    """Persist one immutable Grounded replay receipt per send operation."""

    def __init__(
        self,
        database: SQLiteDatabase,
    ) -> None:
        self.database = database

    def load(
        self,
        operation_id: uuid.UUID,
    ) -> GroundedResponseReceipt | None:
        row = self.database.connection.execute(
            """
            SELECT
                operation_id,
                chat_id,
                processing_run_id,
                payload_json,
                payload_sha256,
                format_version,
                created_at_us
            FROM grounded_response_receipts
            WHERE operation_id = ?
            """,
            (
                uuid_to_blob(
                    operation_id
                ),
            ),
        ).fetchone()

        if row is None:
            return None

        return _receipt_from_row(
            row
        )

    def store(
        self,
        *,
        operation_id: uuid.UUID,
        chat_id: uuid.UUID,
        processing_run_id: uuid.UUID,
        payload_json: str,
    ) -> GroundedResponseReceipt:
        canonical, digest = _canonical_payload(
            payload_json
        )

        with self.database.write_transaction() as connection:
            row = connection.execute(
                """
                SELECT
                    operation_id,
                    chat_id,
                    processing_run_id,
                    payload_json,
                    payload_sha256,
                    format_version,
                    created_at_us
                FROM grounded_response_receipts
                WHERE operation_id = ?
                """,
                (
                    uuid_to_blob(
                        operation_id
                    ),
                ),
            ).fetchone()

            if row is not None:
                existing = _receipt_from_row(
                    row
                )

                if (
                    existing.chat_id == chat_id
                    and existing.processing_run_id
                    == processing_run_id
                    and existing.payload_json
                    == canonical
                    and existing.payload_sha256
                    == digest
                ):
                    return existing

                raise GroundedResponseReceiptConflictError(
                    "Grounded response operation ID already has "
                    "a different durable receipt."
                )

            created_at_us = utc_now_us()

            connection.execute(
                """
                INSERT INTO grounded_response_receipts (
                    operation_id,
                    chat_id,
                    processing_run_id,
                    payload_json,
                    payload_sha256,
                    format_version,
                    created_at_us
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid_to_blob(
                        operation_id
                    ),
                    uuid_to_blob(
                        chat_id
                    ),
                    uuid_to_blob(
                        processing_run_id
                    ),
                    canonical,
                    digest,
                    GROUNDED_RESPONSE_RECEIPT_FORMAT_VERSION,
                    created_at_us,
                ),
            )

            return GroundedResponseReceipt(
                operation_id=operation_id,
                chat_id=chat_id,
                processing_run_id=processing_run_id,
                payload_json=canonical,
                payload_sha256=digest,
                format_version=(
                    GROUNDED_RESPONSE_RECEIPT_FORMAT_VERSION
                ),
                created_at_us=created_at_us,
            )
