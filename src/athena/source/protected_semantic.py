"""Transactional Protected-Content cutover for Source semantic state."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from athena.common.ids import uuid_from_blob, uuid_to_blob
from athena.common.time import utc_now_us
from athena.storage.database import SQLiteDatabase

ProtectedSemanticPayloadWriter = Callable[
    [sqlite3.Connection, bytes],
    uuid.UUID,
]

REPRESENTATION_SEMANTIC_KIND = (
    "source_representation"
)
REPRESENTATION_PAYLOAD_VERSION = 1

_NEUTRAL_OPTIONS_JSON = "{}"
_NEUTRAL_HASH_DOMAIN = (
    b"ATHENA_PROTECTED_SOURCE_"
    b"REPRESENTATION_SEMANTIC_V1:"
)


class SourceProtectedSemanticError(
    RuntimeError
):
    """Base error for Source semantic protection."""


class SourceProtectedSemanticIntegrityError(
    SourceProtectedSemanticError
):
    """Raised when protected semantic state is inconsistent."""


class SourceProtectedSemanticNotFoundError(
    LookupError
):
    """Raised when the semantic entity does not exist."""


@dataclass(
    frozen=True,
    slots=True,
)
class SourceProtectedSemanticMapping:
    source_id: uuid.UUID
    semantic_kind: str
    entity_id: uuid.UUID
    protection_scope_id: uuid.UUID
    protected_payload_id: uuid.UUID
    payload_version: int
    created_at_us: int


@dataclass(
    frozen=True,
    slots=True,
)
class ProtectedRepresentationSemantics:
    representation_id: uuid.UUID
    content_hash: bytes
    options_json: str


def representation_neutral_content_hash(
    representation_id: uuid.UUID,
) -> bytes:
    """Return a deterministic non-content placeholder hash."""
    return hashlib.sha256(
        _NEUTRAL_HASH_DOMAIN
        + representation_id.bytes
    ).digest()


def decode_representation_semantics(
    plaintext: bytes,
) -> ProtectedRepresentationSemantics:
    """Validate and decode one representation semantic payload."""
    try:
        raw_text = plaintext.decode(
            "utf-8"
        )
        payload = json.loads(
            raw_text
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        raise (
            SourceProtectedSemanticIntegrityError(
                "Protected representation semantic "
                "payload is not valid canonical JSON."
            )
        ) from exc

    if (
        not isinstance(
            payload,
            dict,
        )
        or set(
            payload
        )
        != {
            "entity_id",
            "fields",
            "payload_version",
            "semantic_kind",
        }
    ):
        raise (
            SourceProtectedSemanticIntegrityError(
                "Protected representation semantic "
                "payload has an invalid envelope."
            )
        )

    if (
        payload[
            "semantic_kind"
        ]
        != REPRESENTATION_SEMANTIC_KIND
        or payload[
            "payload_version"
        ]
        != REPRESENTATION_PAYLOAD_VERSION
    ):
        raise (
            SourceProtectedSemanticIntegrityError(
                "Protected representation semantic "
                "payload version is unsupported."
            )
        )

    try:
        representation_id = uuid.UUID(
            str(
                payload[
                    "entity_id"
                ]
            )
        )
    except ValueError as exc:
        raise (
            SourceProtectedSemanticIntegrityError(
                "Protected representation semantic "
                "payload has an invalid entity ID."
            )
        ) from exc

    fields = payload[
        "fields"
    ]

    if (
        not isinstance(
            fields,
            dict,
        )
        or set(
            fields
        )
        != {
            "content_hash_hex",
            "options_json",
        }
    ):
        raise (
            SourceProtectedSemanticIntegrityError(
                "Protected representation semantic "
                "payload fields are invalid."
            )
        )

    content_hash_hex = fields[
        "content_hash_hex"
    ]
    options_json = fields[
        "options_json"
    ]

    if not isinstance(
        content_hash_hex,
        str,
    ):
        raise (
            SourceProtectedSemanticIntegrityError(
                "Protected representation content "
                "hash is invalid."
            )
        )

    try:
        content_hash = bytes.fromhex(
            content_hash_hex
        )
    except ValueError as exc:
        raise (
            SourceProtectedSemanticIntegrityError(
                "Protected representation content "
                "hash is invalid."
            )
        ) from exc

    if len(
        content_hash
    ) != 32:
        raise (
            SourceProtectedSemanticIntegrityError(
                "Protected representation content "
                "hash is not SHA-256."
            )
        )

    if not isinstance(
        options_json,
        str,
    ):
        raise (
            SourceProtectedSemanticIntegrityError(
                "Protected representation options "
                "are invalid."
            )
        )

    try:
        options = json.loads(
            options_json
        )
    except json.JSONDecodeError as exc:
        raise (
            SourceProtectedSemanticIntegrityError(
                "Protected representation options "
                "are not valid JSON."
            )
        ) from exc

    if not isinstance(
        options,
        dict,
    ):
        raise (
            SourceProtectedSemanticIntegrityError(
                "Protected representation options "
                "must be a JSON object."
            )
        )

    return ProtectedRepresentationSemantics(
        representation_id=representation_id,
        content_hash=content_hash,
        options_json=options_json,
    )


class SourceProtectedSemanticRepository:
    """Atomically protect persisted Source-derived semantics."""

    def __init__(
        self,
        database: SQLiteDatabase,
    ) -> None:
        self.database = database

    def get_representation_mapping(
        self,
        *,
        source_id: uuid.UUID,
        representation_id: uuid.UUID,
    ) -> SourceProtectedSemanticMapping | None:
        row = (
            self.database
            .connection
            .execute(
                """
                SELECT
                    source_id,
                    semantic_kind,
                    entity_id,
                    protection_scope_id,
                    protected_payload_id,
                    payload_version,
                    created_at_us
                FROM source_protected_semantic_payloads
                WHERE source_id = ?
                  AND semantic_kind = ?
                  AND entity_id = ?
                """,
                (
                    uuid_to_blob(
                        source_id
                    ),
                    REPRESENTATION_SEMANTIC_KIND,
                    uuid_to_blob(
                        representation_id
                    ),
                ),
            )
            .fetchone()
        )

        if row is None:
            return None

        return self._mapping_from_row(
            row
        )

    def protect_representation_semantics(
        self,
        connection: sqlite3.Connection,
        *,
        source_id: uuid.UUID,
        representation_id: uuid.UUID,
        protection_scope_id: uuid.UUID,
        payload_writer: (
            ProtectedSemanticPayloadWriter
        ),
        now_us: int | None = None,
    ) -> SourceProtectedSemanticMapping:
        """Protect representation metadata in the caller transaction."""
        if not connection.in_transaction:
            raise RuntimeError(
                "Protected Source semantic cutover "
                "requires an active transaction."
            )

        row = connection.execute(
            """
            SELECT
                source_id,
                content_hash,
                options_json
            FROM source_representations
            WHERE representation_id = ?
            """,
            (
                uuid_to_blob(
                    representation_id
                ),
            ),
        ).fetchone()

        if row is None:
            raise (
                SourceProtectedSemanticNotFoundError(
                    str(
                        representation_id
                    )
                )
            )

        actual_source_id = uuid_from_blob(
            bytes(
                row[
                    "source_id"
                ]
            )
        )

        if actual_source_id != source_id:
            raise (
                SourceProtectedSemanticIntegrityError(
                    "SourceRepresentation does not "
                    "belong to the requested Source."
                )
            )

        content_hash = bytes(
            row[
                "content_hash"
            ]
        )
        options_json = str(
            row[
                "options_json"
            ]
        )

        if len(
            content_hash
        ) != 32:
            raise (
                SourceProtectedSemanticIntegrityError(
                    "SourceRepresentation content "
                    "hash is invalid."
                )
            )

        self._require_options_object(
            options_json
        )

        scope = connection.execute(
            """
            SELECT lifecycle_state
            FROM protection_scopes
            WHERE protection_scope_id = ?
            """,
            (
                uuid_to_blob(
                    protection_scope_id
                ),
            ),
        ).fetchone()

        if (
            scope is None
            or str(
                scope[
                    "lifecycle_state"
                ]
            )
            != "active"
        ):
            raise (
                SourceProtectedSemanticIntegrityError(
                    "Representation semantic cutover "
                    "requires an active ProtectionScope."
                )
            )

        existing = connection.execute(
            """
            SELECT
                source_id,
                semantic_kind,
                entity_id,
                protection_scope_id,
                protected_payload_id,
                payload_version,
                created_at_us
            FROM source_protected_semantic_payloads
            WHERE source_id = ?
              AND semantic_kind = ?
              AND entity_id = ?
            """,
            (
                uuid_to_blob(
                    source_id
                ),
                REPRESENTATION_SEMANTIC_KIND,
                uuid_to_blob(
                    representation_id
                ),
            ),
        ).fetchone()

        neutral_hash = (
            representation_neutral_content_hash(
                representation_id
            )
        )

        if existing is not None:
            mapping = (
                self._mapping_from_row(
                    existing
                )
            )

            if (
                mapping.protection_scope_id
                != protection_scope_id
                or mapping.payload_version
                != REPRESENTATION_PAYLOAD_VERSION
            ):
                raise (
                    SourceProtectedSemanticIntegrityError(
                        "Existing representation "
                        "semantic mapping disagrees "
                        "with the requested scope."
                    )
                )

            self._require_mapping_payload(
                connection,
                mapping,
            )

            if (
                content_hash
                != neutral_hash
                or options_json
                != _NEUTRAL_OPTIONS_JSON
            ):
                raise (
                    SourceProtectedSemanticIntegrityError(
                        "Representation semantic "
                        "mapping exists but the public "
                        "row is not neutralized."
                    )
                )

            return mapping

        plaintext = (
            self._encode_representation_semantics(
                representation_id=(
                    representation_id
                ),
                content_hash=content_hash,
                options_json=options_json,
            )
        )

        protected_payload_id = (
            payload_writer(
                connection,
                plaintext,
            )
        )

        payload = connection.execute(
            """
            SELECT protection_scope_id
            FROM protected_payloads
            WHERE protected_payload_id = ?
            """,
            (
                uuid_to_blob(
                    protected_payload_id
                ),
            ),
        ).fetchone()

        if (
            payload is None
            or uuid_from_blob(
                bytes(
                    payload[
                        "protection_scope_id"
                    ]
                )
            )
            != protection_scope_id
        ):
            raise (
                SourceProtectedSemanticIntegrityError(
                    "Protected semantic payload "
                    "writer returned an invalid "
                    "payload reference."
                )
            )

        created_at_us = (
            utc_now_us()
            if now_us is None
            else now_us
        )

        try:
            connection.execute(
                """
                INSERT INTO
                source_protected_semantic_payloads (
                    source_id,
                    semantic_kind,
                    entity_id,
                    protection_scope_id,
                    protected_payload_id,
                    payload_version,
                    created_at_us
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid_to_blob(
                        source_id
                    ),
                    REPRESENTATION_SEMANTIC_KIND,
                    uuid_to_blob(
                        representation_id
                    ),
                    uuid_to_blob(
                        protection_scope_id
                    ),
                    uuid_to_blob(
                        protected_payload_id
                    ),
                    REPRESENTATION_PAYLOAD_VERSION,
                    created_at_us,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise (
                SourceProtectedSemanticIntegrityError(
                    "Representation semantic mapping "
                    "violates the v39 schema."
                )
            ) from exc

        updated = connection.execute(
            """
            UPDATE source_representations
            SET content_hash = ?,
                options_json = ?
            WHERE representation_id = ?
              AND source_id = ?
              AND content_hash = ?
              AND options_json = ?
            """,
            (
                neutral_hash,
                _NEUTRAL_OPTIONS_JSON,
                uuid_to_blob(
                    representation_id
                ),
                uuid_to_blob(
                    source_id
                ),
                content_hash,
                options_json,
            ),
        )

        if updated.rowcount != 1:
            raise (
                SourceProtectedSemanticIntegrityError(
                    "SourceRepresentation changed "
                    "during semantic cutover."
                )
            )

        return SourceProtectedSemanticMapping(
            source_id=source_id,
            semantic_kind=(
                REPRESENTATION_SEMANTIC_KIND
            ),
            entity_id=representation_id,
            protection_scope_id=(
                protection_scope_id
            ),
            protected_payload_id=(
                protected_payload_id
            ),
            payload_version=(
                REPRESENTATION_PAYLOAD_VERSION
            ),
            created_at_us=created_at_us,
        )

    @staticmethod
    def _encode_representation_semantics(
        *,
        representation_id: uuid.UUID,
        content_hash: bytes,
        options_json: str,
    ) -> bytes:
        if len(
            content_hash
        ) != 32:
            raise (
                SourceProtectedSemanticIntegrityError(
                    "Representation semantic content "
                    "hash is invalid."
                )
            )

        SourceProtectedSemanticRepository._require_options_object(
            options_json
        )

        payload = {
            "entity_id": str(
                representation_id
            ),
            "fields": {
                "content_hash_hex": (
                    content_hash.hex()
                ),
                "options_json": (
                    options_json
                ),
            },
            "payload_version": (
                REPRESENTATION_PAYLOAD_VERSION
            ),
            "semantic_kind": (
                REPRESENTATION_SEMANTIC_KIND
            ),
        }

        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(
                ",",
                ":",
            ),
            allow_nan=False,
        ).encode(
            "utf-8"
        )

    @staticmethod
    def _require_options_object(
        options_json: str,
    ) -> None:
        try:
            parsed = json.loads(
                options_json
            )
        except json.JSONDecodeError as exc:
            raise (
                SourceProtectedSemanticIntegrityError(
                    "SourceRepresentation options "
                    "are not valid JSON."
                )
            ) from exc

        if not isinstance(
            parsed,
            dict,
        ):
            raise (
                SourceProtectedSemanticIntegrityError(
                    "SourceRepresentation options "
                    "must be a JSON object."
                )
            )

    @staticmethod
    def _require_mapping_payload(
        connection: sqlite3.Connection,
        mapping: SourceProtectedSemanticMapping,
    ) -> None:
        row = connection.execute(
            """
            SELECT protection_scope_id
            FROM protected_payloads
            WHERE protected_payload_id = ?
            """,
            (
                uuid_to_blob(
                    mapping
                    .protected_payload_id
                ),
            ),
        ).fetchone()

        if (
            row is None
            or uuid_from_blob(
                bytes(
                    row[
                        "protection_scope_id"
                    ]
                )
            )
            != mapping.protection_scope_id
        ):
            raise (
                SourceProtectedSemanticIntegrityError(
                    "Representation semantic mapping "
                    "references an invalid protected "
                    "payload."
                )
            )

    @staticmethod
    def _mapping_from_row(
        row: sqlite3.Row,
    ) -> SourceProtectedSemanticMapping:
        return SourceProtectedSemanticMapping(
            source_id=uuid_from_blob(
                bytes(
                    row[
                        "source_id"
                    ]
                )
            ),
            semantic_kind=str(
                row[
                    "semantic_kind"
                ]
            ),
            entity_id=uuid_from_blob(
                bytes(
                    row[
                        "entity_id"
                    ]
                )
            ),
            protection_scope_id=(
                uuid_from_blob(
                    bytes(
                        row[
                            "protection_scope_id"
                        ]
                    )
                )
            ),
            protected_payload_id=(
                uuid_from_blob(
                    bytes(
                        row[
                            "protected_payload_id"
                        ]
                    )
                )
            ),
            payload_version=int(
                row[
                    "payload_version"
                ]
            ),
            created_at_us=int(
                row[
                    "created_at_us"
                ]
            ),
        )
