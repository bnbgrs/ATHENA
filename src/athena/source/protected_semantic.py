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

PAGE_MAP_SEMANTIC_KIND = "source_representation_pages"
PAGE_MAP_PAYLOAD_VERSION = 1
STRUCTURE_MAP_SEMANTIC_KIND = "source_representation_structures"
STRUCTURE_MAP_PAYLOAD_VERSION = 1

_NEUTRAL_PAGE_HASH_DOMAIN = (
    b"ATHENA_PROTECTED_SOURCE_"
    b"REPRESENTATION_PAGE_MAP_V1:"
)
_NEUTRAL_STRUCTURE_HASH_DOMAIN = (
    b"ATHENA_PROTECTED_SOURCE_"
    b"REPRESENTATION_STRUCTURE_MAP_V1:"
)
_NEUTRAL_STRUCTURE_METADATA_JSON = "{}"


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


@dataclass(frozen=True, slots=True)
class ProtectedRepresentationPageEntry:
    page_number: int
    content_hash: bytes


@dataclass(frozen=True, slots=True)
class ProtectedRepresentationPageMapSemantics:
    representation_id: uuid.UUID
    pages: tuple[ProtectedRepresentationPageEntry, ...]


@dataclass(frozen=True, slots=True)
class ProtectedRepresentationStructureEntry:
    structure_id: uuid.UUID
    structure_index: int
    path: str
    content_hash: bytes
    metadata_json: str


@dataclass(frozen=True, slots=True)
class ProtectedRepresentationStructureMapSemantics:
    representation_id: uuid.UUID
    structures: tuple[ProtectedRepresentationStructureEntry, ...]


def page_neutral_content_hash(
    representation_id: uuid.UUID,
    page_number: int,
) -> bytes:
    """Return a deterministic non-content page hash."""
    if page_number < 1:
        raise ValueError("Page number must be positive.")

    return hashlib.sha256(
        _NEUTRAL_PAGE_HASH_DOMAIN
        + representation_id.bytes
        + page_number.to_bytes(
            8,
            "big",
            signed=False,
        )
    ).digest()


def structure_neutral_content_hash(
    structure_id: uuid.UUID,
) -> bytes:
    """Return a deterministic non-content structure hash."""
    return hashlib.sha256(
        _NEUTRAL_STRUCTURE_HASH_DOMAIN
        + structure_id.bytes
    ).digest()


def structure_neutral_path(
    structure_id: uuid.UUID,
    structure_index: int,
) -> str:
    """Return a unique path containing only neutral public identity."""
    if structure_index < 0:
        raise ValueError(
            "Structure index must be non-negative."
        )

    return (
        "/_protected/structure["
        f"{structure_index}"
        "]/id["
        f"{structure_id.hex}"
        "]"
    )


def _decode_map_envelope(
    plaintext: bytes,
    *,
    semantic_kind: str,
    payload_version: int,
    field_name: str,
) -> tuple[uuid.UUID, object]:
    try:
        payload = json.loads(
            plaintext.decode("utf-8")
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        raise SourceProtectedSemanticIntegrityError(
            "Protected representation-map payload "
            "is not valid canonical JSON."
        ) from exc

    if (
        not isinstance(payload, dict)
        or set(payload)
        != {
            "entity_id",
            "fields",
            "payload_version",
            "semantic_kind",
        }
    ):
        raise SourceProtectedSemanticIntegrityError(
            "Protected representation-map payload "
            "has an invalid envelope."
        )

    if (
        payload["semantic_kind"] != semantic_kind
        or payload["payload_version"] != payload_version
    ):
        raise SourceProtectedSemanticIntegrityError(
            "Protected representation-map payload "
            "version is unsupported."
        )

    try:
        representation_id = uuid.UUID(
            str(payload["entity_id"])
        )
    except ValueError as exc:
        raise SourceProtectedSemanticIntegrityError(
            "Protected representation-map payload "
            "has an invalid entity ID."
        ) from exc

    fields = payload["fields"]

    if (
        not isinstance(fields, dict)
        or set(fields) != {field_name}
    ):
        raise SourceProtectedSemanticIntegrityError(
            "Protected representation-map payload "
            "fields are invalid."
        )

    return representation_id, fields[field_name]


def decode_representation_page_map_semantics(
    plaintext: bytes,
) -> ProtectedRepresentationPageMapSemantics:
    representation_id, raw_pages = _decode_map_envelope(
        plaintext,
        semantic_kind=PAGE_MAP_SEMANTIC_KIND,
        payload_version=PAGE_MAP_PAYLOAD_VERSION,
        field_name="pages",
    )

    if not isinstance(raw_pages, list):
        raise SourceProtectedSemanticIntegrityError(
            "Protected page-map entries are invalid."
        )

    pages: list[ProtectedRepresentationPageEntry] = []

    for expected_number, raw in enumerate(
        raw_pages,
        start=1,
    ):
        if (
            not isinstance(raw, dict)
            or set(raw)
            != {
                "content_hash_hex",
                "page_number",
            }
        ):
            raise SourceProtectedSemanticIntegrityError(
                "Protected page-map entry is invalid."
            )

        page_number = raw["page_number"]

        if (
            not isinstance(page_number, int)
            or isinstance(page_number, bool)
            or page_number != expected_number
        ):
            raise SourceProtectedSemanticIntegrityError(
                "Protected page-map ordering is invalid."
            )

        raw_hash = raw["content_hash_hex"]

        if not isinstance(raw_hash, str):
            raise SourceProtectedSemanticIntegrityError(
                "Protected page hash is invalid."
            )

        try:
            content_hash = bytes.fromhex(raw_hash)
        except ValueError as exc:
            raise SourceProtectedSemanticIntegrityError(
                "Protected page hash is invalid."
            ) from exc

        if len(content_hash) != 32:
            raise SourceProtectedSemanticIntegrityError(
                "Protected page hash is not SHA-256."
            )

        pages.append(
            ProtectedRepresentationPageEntry(
                page_number=page_number,
                content_hash=content_hash,
            )
        )

    return ProtectedRepresentationPageMapSemantics(
        representation_id=representation_id,
        pages=tuple(pages),
    )


def decode_representation_structure_map_semantics(
    plaintext: bytes,
) -> ProtectedRepresentationStructureMapSemantics:
    representation_id, raw_structures = _decode_map_envelope(
        plaintext,
        semantic_kind=STRUCTURE_MAP_SEMANTIC_KIND,
        payload_version=STRUCTURE_MAP_PAYLOAD_VERSION,
        field_name="structures",
    )

    if not isinstance(raw_structures, list):
        raise SourceProtectedSemanticIntegrityError(
            "Protected structure-map entries are invalid."
        )

    structures: list[
        ProtectedRepresentationStructureEntry
    ] = []

    for expected_index, raw in enumerate(
        raw_structures
    ):
        if (
            not isinstance(raw, dict)
            or set(raw)
            != {
                "content_hash_hex",
                "metadata_json",
                "path",
                "structure_id",
                "structure_index",
            }
        ):
            raise SourceProtectedSemanticIntegrityError(
                "Protected structure-map entry is invalid."
            )

        structure_index = raw["structure_index"]

        if (
            not isinstance(structure_index, int)
            or isinstance(structure_index, bool)
            or structure_index != expected_index
        ):
            raise SourceProtectedSemanticIntegrityError(
                "Protected structure-map ordering is invalid."
            )

        try:
            structure_id = uuid.UUID(
                str(raw["structure_id"])
            )
        except ValueError as exc:
            raise SourceProtectedSemanticIntegrityError(
                "Protected structure ID is invalid."
            ) from exc

        path = raw["path"]
        metadata_json = raw["metadata_json"]
        raw_hash = raw["content_hash_hex"]

        if (
            not isinstance(path, str)
            or not path
            or not isinstance(metadata_json, str)
            or not isinstance(raw_hash, str)
        ):
            raise SourceProtectedSemanticIntegrityError(
                "Protected structure fields are invalid."
            )

        try:
            metadata = json.loads(metadata_json)
        except json.JSONDecodeError as exc:
            raise SourceProtectedSemanticIntegrityError(
                "Protected structure metadata "
                "is not valid JSON."
            ) from exc

        if not isinstance(metadata, dict):
            raise SourceProtectedSemanticIntegrityError(
                "Protected structure metadata "
                "must be a JSON object."
            )

        try:
            content_hash = bytes.fromhex(raw_hash)
        except ValueError as exc:
            raise SourceProtectedSemanticIntegrityError(
                "Protected structure hash is invalid."
            ) from exc

        if len(content_hash) != 32:
            raise SourceProtectedSemanticIntegrityError(
                "Protected structure hash is not SHA-256."
            )

        structures.append(
            ProtectedRepresentationStructureEntry(
                structure_id=structure_id,
                structure_index=structure_index,
                path=path,
                content_hash=content_hash,
                metadata_json=metadata_json,
            )
        )

    return ProtectedRepresentationStructureMapSemantics(
        representation_id=representation_id,
        structures=tuple(structures),
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

    def protect_representation_map_semantics(
        self,
        connection: sqlite3.Connection,
        *,
        source_id: uuid.UUID,
        representation_id: uuid.UUID,
        protection_scope_id: uuid.UUID,
        payload_writer: ProtectedSemanticPayloadWriter,
        now_us: int | None = None,
    ) -> tuple[SourceProtectedSemanticMapping, ...]:
        """Protect retained page/structure-map semantics atomically."""
        if not connection.in_transaction:
            raise RuntimeError(
                "Protected Source semantic cutover "
                "requires an active transaction."
            )

        self._require_representation_source(
            connection,
            source_id=source_id,
            representation_id=representation_id,
        )

        self._require_active_scope(
            connection,
            protection_scope_id,
        )

        created_at_us = (
            utc_now_us()
            if now_us is None
            else now_us
        )

        page_mapping = self._protect_page_map_semantics(
            connection,
            source_id=source_id,
            representation_id=representation_id,
            protection_scope_id=protection_scope_id,
            payload_writer=payload_writer,
            created_at_us=created_at_us,
        )

        structure_mapping = (
            self._protect_structure_map_semantics(
                connection,
                source_id=source_id,
                representation_id=representation_id,
                protection_scope_id=protection_scope_id,
                payload_writer=payload_writer,
                created_at_us=created_at_us,
            )
        )

        return tuple(
            mapping
            for mapping in (
                page_mapping,
                structure_mapping,
            )
            if mapping is not None
        )

    def _protect_page_map_semantics(
        self,
        connection: sqlite3.Connection,
        *,
        source_id: uuid.UUID,
        representation_id: uuid.UUID,
        protection_scope_id: uuid.UUID,
        payload_writer: ProtectedSemanticPayloadWriter,
        created_at_us: int,
    ) -> SourceProtectedSemanticMapping | None:
        rows = connection.execute(
            """
            SELECT
                page_number,
                content_hash
            FROM source_representation_pages
            WHERE representation_id = ?
            ORDER BY page_number
            """,
            (
                uuid_to_blob(representation_id),
            ),
        ).fetchall()

        existing = self._mapping_for(
            connection,
            source_id=source_id,
            semantic_kind=PAGE_MAP_SEMANTIC_KIND,
            entity_id=representation_id,
        )

        if not rows:
            if existing is not None:
                raise SourceProtectedSemanticIntegrityError(
                    "Protected page-map mapping exists "
                    "but the public page map is missing."
                )
            return None

        pages = tuple(
            (
                int(row["page_number"]),
                bytes(row["content_hash"]),
            )
            for row in rows
        )

        expected_numbers = tuple(
            range(1, len(pages) + 1)
        )

        if tuple(
            item[0]
            for item in pages
        ) != expected_numbers:
            raise SourceProtectedSemanticIntegrityError(
                "SourceRepresentation page map "
                "is not contiguous."
            )

        if existing is not None:
            self._require_existing_mapping(
                connection,
                existing,
                semantic_kind=PAGE_MAP_SEMANTIC_KIND,
                payload_version=PAGE_MAP_PAYLOAD_VERSION,
                protection_scope_id=protection_scope_id,
            )

            for page_number, content_hash in pages:
                if content_hash != page_neutral_content_hash(
                    representation_id,
                    page_number,
                ):
                    raise SourceProtectedSemanticIntegrityError(
                        "Protected page map is not "
                        "fully neutralized."
                    )

            return existing

        for page_number, content_hash in pages:
            if len(content_hash) != 32:
                raise SourceProtectedSemanticIntegrityError(
                    "SourceRepresentation page hash "
                    "is invalid."
                )

            if content_hash == page_neutral_content_hash(
                representation_id,
                page_number,
            ):
                raise SourceProtectedSemanticIntegrityError(
                    "Page map appears neutralized "
                    "without a protected mapping."
                )

        plaintext = self._encode_page_map_semantics(
            representation_id=representation_id,
            pages=pages,
        )

        protected_payload_id = payload_writer(
            connection,
            plaintext,
        )

        self._require_payload_scope(
            connection,
            protected_payload_id=protected_payload_id,
            protection_scope_id=protection_scope_id,
        )

        mapping = self._insert_semantic_mapping(
            connection,
            source_id=source_id,
            semantic_kind=PAGE_MAP_SEMANTIC_KIND,
            entity_id=representation_id,
            protection_scope_id=protection_scope_id,
            protected_payload_id=protected_payload_id,
            payload_version=PAGE_MAP_PAYLOAD_VERSION,
            created_at_us=created_at_us,
        )

        for page_number, original_hash in pages:
            updated = connection.execute(
                """
                UPDATE source_representation_pages
                SET content_hash = ?
                WHERE representation_id = ?
                  AND page_number = ?
                  AND content_hash = ?
                """,
                (
                    page_neutral_content_hash(
                        representation_id,
                        page_number,
                    ),
                    uuid_to_blob(representation_id),
                    page_number,
                    original_hash,
                ),
            )

            if updated.rowcount != 1:
                raise SourceProtectedSemanticIntegrityError(
                    "SourceRepresentation page map "
                    "changed during semantic cutover."
                )

        return mapping

    def _protect_structure_map_semantics(
        self,
        connection: sqlite3.Connection,
        *,
        source_id: uuid.UUID,
        representation_id: uuid.UUID,
        protection_scope_id: uuid.UUID,
        payload_writer: ProtectedSemanticPayloadWriter,
        created_at_us: int,
    ) -> SourceProtectedSemanticMapping | None:
        rows = connection.execute(
            """
            SELECT
                structure_id,
                structure_index,
                path,
                content_hash,
                metadata_json
            FROM source_representation_structures
            WHERE representation_id = ?
            ORDER BY structure_index
            """,
            (
                uuid_to_blob(representation_id),
            ),
        ).fetchall()

        existing = self._mapping_for(
            connection,
            source_id=source_id,
            semantic_kind=STRUCTURE_MAP_SEMANTIC_KIND,
            entity_id=representation_id,
        )

        if not rows:
            if existing is not None:
                raise SourceProtectedSemanticIntegrityError(
                    "Protected structure-map mapping exists "
                    "but the public structure map is missing."
                )
            return None

        structures = tuple(
            (
                uuid_from_blob(
                    bytes(row["structure_id"])
                ),
                int(row["structure_index"]),
                str(row["path"]),
                bytes(row["content_hash"]),
                str(row["metadata_json"]),
            )
            for row in rows
        )

        expected_indexes = tuple(
            range(len(structures))
        )

        if tuple(
            item[1]
            for item in structures
        ) != expected_indexes:
            raise SourceProtectedSemanticIntegrityError(
                "SourceRepresentation structure map "
                "is not contiguous."
            )

        if existing is not None:
            self._require_existing_mapping(
                connection,
                existing,
                semantic_kind=STRUCTURE_MAP_SEMANTIC_KIND,
                payload_version=STRUCTURE_MAP_PAYLOAD_VERSION,
                protection_scope_id=protection_scope_id,
            )

            for (
                structure_id,
                structure_index,
                path,
                content_hash,
                metadata_json,
            ) in structures:
                if (
                    path
                    != structure_neutral_path(
                        structure_id,
                        structure_index,
                    )
                    or content_hash
                    != structure_neutral_content_hash(
                        structure_id
                    )
                    or metadata_json
                    != _NEUTRAL_STRUCTURE_METADATA_JSON
                ):
                    raise SourceProtectedSemanticIntegrityError(
                        "Protected structure map is not "
                        "fully neutralized."
                    )

            return existing

        original_paths: set[str] = set()

        for (
            structure_id,
            structure_index,
            path,
            content_hash,
            metadata_json,
        ) in structures:
            if not path:
                raise SourceProtectedSemanticIntegrityError(
                    "SourceRepresentation structure "
                    "path is empty."
                )

            if path in original_paths:
                raise SourceProtectedSemanticIntegrityError(
                    "SourceRepresentation structure "
                    "paths are not unique."
                )

            original_paths.add(path)

            if len(content_hash) != 32:
                raise SourceProtectedSemanticIntegrityError(
                    "SourceRepresentation structure "
                    "hash is invalid."
                )

            try:
                metadata = json.loads(
                    metadata_json
                )
            except json.JSONDecodeError as exc:
                raise SourceProtectedSemanticIntegrityError(
                    "SourceRepresentation structure "
                    "metadata is not valid JSON."
                ) from exc

            if not isinstance(metadata, dict):
                raise SourceProtectedSemanticIntegrityError(
                    "SourceRepresentation structure "
                    "metadata must be a JSON object."
                )

            if (
                path
                == structure_neutral_path(
                    structure_id,
                    structure_index,
                )
                or content_hash
                == structure_neutral_content_hash(
                    structure_id
                )
            ):
                raise SourceProtectedSemanticIntegrityError(
                    "Structure map appears neutralized "
                    "without a protected mapping."
                )

        plaintext = (
            self._encode_structure_map_semantics(
                representation_id=representation_id,
                structures=structures,
            )
        )

        protected_payload_id = payload_writer(
            connection,
            plaintext,
        )

        self._require_payload_scope(
            connection,
            protected_payload_id=protected_payload_id,
            protection_scope_id=protection_scope_id,
        )

        mapping = self._insert_semantic_mapping(
            connection,
            source_id=source_id,
            semantic_kind=STRUCTURE_MAP_SEMANTIC_KIND,
            entity_id=representation_id,
            protection_scope_id=protection_scope_id,
            protected_payload_id=protected_payload_id,
            payload_version=STRUCTURE_MAP_PAYLOAD_VERSION,
            created_at_us=created_at_us,
        )

        for (
            structure_id,
            structure_index,
            original_path,
            original_hash,
            original_metadata,
        ) in structures:
            updated = connection.execute(
                """
                UPDATE source_representation_structures
                SET path = ?,
                    content_hash = ?,
                    metadata_json = ?
                WHERE structure_id = ?
                  AND representation_id = ?
                  AND structure_index = ?
                  AND path = ?
                  AND content_hash = ?
                  AND metadata_json = ?
                """,
                (
                    structure_neutral_path(
                        structure_id,
                        structure_index,
                    ),
                    structure_neutral_content_hash(
                        structure_id
                    ),
                    _NEUTRAL_STRUCTURE_METADATA_JSON,
                    uuid_to_blob(structure_id),
                    uuid_to_blob(representation_id),
                    structure_index,
                    original_path,
                    original_hash,
                    original_metadata,
                ),
            )

            if updated.rowcount != 1:
                raise SourceProtectedSemanticIntegrityError(
                    "SourceRepresentation structure map "
                    "changed during semantic cutover."
                )

        return mapping

    @staticmethod
    def _encode_page_map_semantics(
        *,
        representation_id: uuid.UUID,
        pages: tuple[
            tuple[int, bytes],
            ...,
        ],
    ) -> bytes:
        payload = {
            "entity_id": str(representation_id),
            "fields": {
                "pages": [
                    {
                        "content_hash_hex": content_hash.hex(),
                        "page_number": page_number,
                    }
                    for page_number, content_hash in pages
                ]
            },
            "payload_version": PAGE_MAP_PAYLOAD_VERSION,
            "semantic_kind": PAGE_MAP_SEMANTIC_KIND,
        }

        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")

    @staticmethod
    def _encode_structure_map_semantics(
        *,
        representation_id: uuid.UUID,
        structures: tuple[
            tuple[
                uuid.UUID,
                int,
                str,
                bytes,
                str,
            ],
            ...,
        ],
    ) -> bytes:
        payload = {
            "entity_id": str(representation_id),
            "fields": {
                "structures": [
                    {
                        "content_hash_hex": content_hash.hex(),
                        "metadata_json": metadata_json,
                        "path": path,
                        "structure_id": str(structure_id),
                        "structure_index": structure_index,
                    }
                    for (
                        structure_id,
                        structure_index,
                        path,
                        content_hash,
                        metadata_json,
                    ) in structures
                ]
            },
            "payload_version": STRUCTURE_MAP_PAYLOAD_VERSION,
            "semantic_kind": STRUCTURE_MAP_SEMANTIC_KIND,
        }

        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")

    @staticmethod
    def _require_representation_source(
        connection: sqlite3.Connection,
        *,
        source_id: uuid.UUID,
        representation_id: uuid.UUID,
    ) -> None:
        row = connection.execute(
            """
            SELECT source_id
            FROM source_representations
            WHERE representation_id = ?
            """,
            (
                uuid_to_blob(representation_id),
            ),
        ).fetchone()

        if row is None:
            raise SourceProtectedSemanticNotFoundError(
                str(representation_id)
            )

        actual_source_id = uuid_from_blob(
            bytes(row["source_id"])
        )

        if actual_source_id != source_id:
            raise SourceProtectedSemanticIntegrityError(
                "SourceRepresentation does not belong "
                "to the requested Source."
            )

    @staticmethod
    def _require_active_scope(
        connection: sqlite3.Connection,
        protection_scope_id: uuid.UUID,
    ) -> None:
        row = connection.execute(
            """
            SELECT lifecycle_state
            FROM protection_scopes
            WHERE protection_scope_id = ?
            """,
            (
                uuid_to_blob(protection_scope_id),
            ),
        ).fetchone()

        if (
            row is None
            or str(row["lifecycle_state"]) != "active"
        ):
            raise SourceProtectedSemanticIntegrityError(
                "Representation-map semantic cutover "
                "requires an active ProtectionScope."
            )

    @staticmethod
    def _mapping_for(
        connection: sqlite3.Connection,
        *,
        source_id: uuid.UUID,
        semantic_kind: str,
        entity_id: uuid.UUID,
    ) -> SourceProtectedSemanticMapping | None:
        row = connection.execute(
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
                uuid_to_blob(source_id),
                semantic_kind,
                uuid_to_blob(entity_id),
            ),
        ).fetchone()

        if row is None:
            return None

        return SourceProtectedSemanticRepository._mapping_from_row(
            row
        )

    @staticmethod
    def _require_payload_scope(
        connection: sqlite3.Connection,
        *,
        protected_payload_id: uuid.UUID,
        protection_scope_id: uuid.UUID,
    ) -> None:
        row = connection.execute(
            """
            SELECT protection_scope_id
            FROM protected_payloads
            WHERE protected_payload_id = ?
            """,
            (
                uuid_to_blob(protected_payload_id),
            ),
        ).fetchone()

        if (
            row is None
            or uuid_from_blob(
                bytes(row["protection_scope_id"])
            )
            != protection_scope_id
        ):
            raise SourceProtectedSemanticIntegrityError(
                "Protected semantic payload writer "
                "returned an invalid payload reference."
            )

    @staticmethod
    def _require_existing_mapping(
        connection: sqlite3.Connection,
        mapping: SourceProtectedSemanticMapping,
        *,
        semantic_kind: str,
        payload_version: int,
        protection_scope_id: uuid.UUID,
    ) -> None:
        if (
            mapping.semantic_kind != semantic_kind
            or mapping.payload_version != payload_version
            or mapping.protection_scope_id
            != protection_scope_id
        ):
            raise SourceProtectedSemanticIntegrityError(
                "Existing representation-map mapping "
                "disagrees with the requested scope "
                "or payload version."
            )

        SourceProtectedSemanticRepository._require_payload_scope(
            connection,
            protected_payload_id=(
                mapping.protected_payload_id
            ),
            protection_scope_id=(
                protection_scope_id
            ),
        )

    @staticmethod
    def _insert_semantic_mapping(
        connection: sqlite3.Connection,
        *,
        source_id: uuid.UUID,
        semantic_kind: str,
        entity_id: uuid.UUID,
        protection_scope_id: uuid.UUID,
        protected_payload_id: uuid.UUID,
        payload_version: int,
        created_at_us: int,
    ) -> SourceProtectedSemanticMapping:
        try:
            connection.execute(
                """
                INSERT INTO source_protected_semantic_payloads (
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
                    uuid_to_blob(source_id),
                    semantic_kind,
                    uuid_to_blob(entity_id),
                    uuid_to_blob(protection_scope_id),
                    uuid_to_blob(protected_payload_id),
                    payload_version,
                    created_at_us,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise SourceProtectedSemanticIntegrityError(
                "Protected semantic mapping "
                "violates the v39 schema."
            ) from exc

        return SourceProtectedSemanticMapping(
            source_id=source_id,
            semantic_kind=semantic_kind,
            entity_id=entity_id,
            protection_scope_id=protection_scope_id,
            protected_payload_id=protected_payload_id,
            payload_version=payload_version,
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
