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

ANCHOR_SEMANTIC_KIND = "source_anchor"
ANCHOR_PAYLOAD_VERSION = 1
_NEUTRAL_ANCHOR_HASH_DOMAIN = (
    b"ATHENA_PROTECTED_SOURCE_"
    b"ANCHOR_SEMANTIC_V1:"
)
_NEUTRAL_ANCHOR_GEOMETRY_JSON = "{}"

EXTRACTION_EVIDENCE_SEMANTIC_KIND = "source_extraction_evidence"
EXTRACTION_EVIDENCE_PAYLOAD_VERSION = 1
_NEUTRAL_EXTRACTION_EVIDENCE_HASH_DOMAIN = (
    b"ATHENA_PROTECTED_SOURCE_"
    b"EXTRACTION_EVIDENCE_V1:"
)

ANALYSIS_SEMANTIC_KIND = "source_analysis"
ANALYSIS_PAYLOAD_VERSION = 1
ANALYSIS_ARTIFACT_SEMANTIC_KIND = "source_analysis_artifact"
ANALYSIS_ARTIFACT_PAYLOAD_VERSION = 1
ANALYSIS_NEUTRAL_ARTIFACT_CONTENT_JSON = "{}"

_NEUTRAL_ANALYSIS_QUESTION_DOMAIN = (
    b"ATHENA_PROTECTED_SOURCE_"
    b"ANALYSIS_QUESTION_V1:"
)
_NEUTRAL_ANALYSIS_ARTIFACT_HASH_DOMAIN = (
    b"ATHENA_PROTECTED_SOURCE_"
    b"ANALYSIS_ARTIFACT_V1:"
)

EXTRACTION_ARTIFACT_SEMANTIC_KIND = "source_extraction_artifacts"
EXTRACTION_ARTIFACT_PAYLOAD_VERSION = 1
EXTRACTION_NEUTRAL_ARTIFACT_CONTENT_JSON = "{}"
_NEUTRAL_EXTRACTION_ARTIFACT_HASH_DOMAIN = (
    b"ATHENA_PROTECTED_SOURCE_"
    b"EXTRACTION_ARTIFACT_V1:"
)

EXTRACTION_SNAPSHOT_SEMANTIC_KIND = "source_extraction_snapshots"
EXTRACTION_SNAPSHOT_PAYLOAD_VERSION = 1
EXTRACTION_SNAPSHOT_NEUTRAL_EVIDENCE_JSON = "{}"
EXTRACTION_SNAPSHOT_NEUTRAL_PROPOSALS_JSON = "{}"


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


@dataclass(frozen=True, slots=True)
class ProtectedSourceAnchorSemantics:
    anchor_id: uuid.UUID
    geometry_json: str | None
    quoted_hash: bytes | None


def anchor_neutral_quoted_hash(anchor_id: uuid.UUID) -> bytes:
    """Return a deterministic non-content SourceAnchor hash."""
    return hashlib.sha256(
        _NEUTRAL_ANCHOR_HASH_DOMAIN + anchor_id.bytes
    ).digest()


def decode_source_anchor_semantics(
    plaintext: bytes,
) -> ProtectedSourceAnchorSemantics:
    """Validate and decode one protected SourceAnchor semantic payload."""
    try:
        payload = json.loads(plaintext.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceProtectedSemanticIntegrityError(
            "Protected SourceAnchor payload is not valid canonical JSON."
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
            "Protected SourceAnchor payload has an invalid envelope."
        )

    if (
        payload["semantic_kind"] != ANCHOR_SEMANTIC_KIND
        or payload["payload_version"] != ANCHOR_PAYLOAD_VERSION
    ):
        raise SourceProtectedSemanticIntegrityError(
            "Protected SourceAnchor payload version is unsupported."
        )

    try:
        anchor_id = uuid.UUID(str(payload["entity_id"]))
    except ValueError as exc:
        raise SourceProtectedSemanticIntegrityError(
            "Protected SourceAnchor payload has an invalid entity ID."
        ) from exc

    fields = payload["fields"]

    if (
        not isinstance(fields, dict)
        or set(fields) != {"geometry_json", "quoted_hash_hex"}
    ):
        raise SourceProtectedSemanticIntegrityError(
            "Protected SourceAnchor payload fields are invalid."
        )

    geometry_json = fields["geometry_json"]

    if geometry_json is not None:
        if not isinstance(geometry_json, str):
            raise SourceProtectedSemanticIntegrityError(
                "Protected SourceAnchor geometry is invalid."
            )

        try:
            json.loads(geometry_json)
        except json.JSONDecodeError as exc:
            raise SourceProtectedSemanticIntegrityError(
                "Protected SourceAnchor geometry is not valid JSON."
            ) from exc

    quoted_hash_hex = fields["quoted_hash_hex"]

    if quoted_hash_hex is None:
        quoted_hash = None
    elif isinstance(quoted_hash_hex, str):
        try:
            quoted_hash = bytes.fromhex(quoted_hash_hex)
        except ValueError as exc:
            raise SourceProtectedSemanticIntegrityError(
                "Protected SourceAnchor quoted hash is invalid."
            ) from exc

        if len(quoted_hash) != 32:
            raise SourceProtectedSemanticIntegrityError(
                "Protected SourceAnchor quoted hash is not SHA-256."
            )
    else:
        raise SourceProtectedSemanticIntegrityError(
            "Protected SourceAnchor quoted hash is invalid."
        )

    return ProtectedSourceAnchorSemantics(
        anchor_id=anchor_id,
        geometry_json=geometry_json,
        quoted_hash=quoted_hash,
    )

@dataclass(frozen=True, slots=True)
class ProtectedSourceExtractionEvidenceEntry:
    sequence_no: int
    source_anchor_id: uuid.UUID
    quoted_hash: bytes


@dataclass(frozen=True, slots=True)
class ProtectedSourceExtractionEvidenceSemantics:
    extraction_id: uuid.UUID
    evidence: tuple[ProtectedSourceExtractionEvidenceEntry, ...]


def extraction_evidence_neutral_quoted_hash(
    extraction_id: uuid.UUID,
    sequence_no: int,
    source_anchor_id: uuid.UUID,
) -> bytes:
    """Return a deterministic non-content extraction-evidence hash."""
    if sequence_no < 1 or sequence_no > 0x7FFF_FFFF_FFFF_FFFF:
        raise ValueError("Extraction evidence sequence must fit positive SQLite INTEGER.")

    return hashlib.sha256(
        _NEUTRAL_EXTRACTION_EVIDENCE_HASH_DOMAIN
        + extraction_id.bytes
        + sequence_no.to_bytes(8, "big", signed=False)
        + source_anchor_id.bytes
    ).digest()


def decode_source_extraction_evidence_semantics(
    plaintext: bytes,
) -> ProtectedSourceExtractionEvidenceSemantics:
    """Validate and decode one protected extraction-evidence payload."""
    try:
        payload = json.loads(plaintext.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceProtectedSemanticIntegrityError(
            "Protected SourceExtraction evidence payload is not valid canonical JSON."
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
            "Protected SourceExtraction evidence payload has an invalid envelope."
        )

    if (
        payload["semantic_kind"] != EXTRACTION_EVIDENCE_SEMANTIC_KIND
        or payload["payload_version"] != EXTRACTION_EVIDENCE_PAYLOAD_VERSION
    ):
        raise SourceProtectedSemanticIntegrityError(
            "Protected SourceExtraction evidence payload version is unsupported."
        )

    try:
        extraction_id = uuid.UUID(str(payload["entity_id"]))
    except ValueError as exc:
        raise SourceProtectedSemanticIntegrityError(
            "Protected SourceExtraction evidence payload has an invalid entity ID."
        ) from exc

    fields = payload["fields"]

    if not isinstance(fields, dict) or set(fields) != {"evidence"}:
        raise SourceProtectedSemanticIntegrityError(
            "Protected SourceExtraction evidence payload fields are invalid."
        )

    raw_evidence = fields["evidence"]

    if not isinstance(raw_evidence, list) or not raw_evidence:
        raise SourceProtectedSemanticIntegrityError(
            "Protected SourceExtraction evidence payload has no evidence rows."
        )

    evidence: list[ProtectedSourceExtractionEvidenceEntry] = []
    seen_anchor_ids: set[uuid.UUID] = set()

    for expected_sequence, raw_entry in enumerate(raw_evidence, 1):
        if (
            not isinstance(raw_entry, dict)
            or set(raw_entry)
            != {
                "quoted_hash_hex",
                "sequence_no",
                "source_anchor_id",
            }
        ):
            raise SourceProtectedSemanticIntegrityError(
                "Protected SourceExtraction evidence entry is invalid."
            )

        sequence_no = raw_entry["sequence_no"]

        if (
            isinstance(sequence_no, bool)
            or not isinstance(sequence_no, int)
            or sequence_no != expected_sequence
        ):
            raise SourceProtectedSemanticIntegrityError(
                "Protected SourceExtraction evidence slots are not contiguous."
            )

        try:
            source_anchor_id = uuid.UUID(str(raw_entry["source_anchor_id"]))
        except ValueError as exc:
            raise SourceProtectedSemanticIntegrityError(
                "Protected SourceExtraction evidence has an invalid SourceAnchor ID."
            ) from exc

        if source_anchor_id in seen_anchor_ids:
            raise SourceProtectedSemanticIntegrityError(
                "Protected SourceExtraction evidence contains duplicate SourceAnchors."
            )
        seen_anchor_ids.add(source_anchor_id)

        quoted_hash_hex = raw_entry["quoted_hash_hex"]

        if not isinstance(quoted_hash_hex, str):
            raise SourceProtectedSemanticIntegrityError(
                "Protected SourceExtraction evidence hash is invalid."
            )

        try:
            quoted_hash = bytes.fromhex(quoted_hash_hex)
        except ValueError as exc:
            raise SourceProtectedSemanticIntegrityError(
                "Protected SourceExtraction evidence hash is invalid."
            ) from exc

        if len(quoted_hash) != 32:
            raise SourceProtectedSemanticIntegrityError(
                "Protected SourceExtraction evidence hash is not SHA-256."
            )

        evidence.append(
            ProtectedSourceExtractionEvidenceEntry(
                sequence_no=sequence_no,
                source_anchor_id=source_anchor_id,
                quoted_hash=quoted_hash,
            )
        )

    return ProtectedSourceExtractionEvidenceSemantics(
        extraction_id=extraction_id,
        evidence=tuple(evidence),
    )



@dataclass(frozen=True, slots=True)
class ProtectedSourceAnalysisSemantics:
    analysis_id: uuid.UUID
    question: str


@dataclass(frozen=True, slots=True)
class ProtectedSourceAnalysisArtifactSemantics:
    artifact_id: uuid.UUID
    analysis_id: uuid.UUID
    content_json: str
    content_hash: bytes


def analysis_neutral_question(analysis_id: uuid.UUID) -> str:
    """Return a deterministic non-content SourceAnalysis question placeholder."""
    digest = hashlib.sha256(
        _NEUTRAL_ANALYSIS_QUESTION_DOMAIN + analysis_id.bytes
    ).hexdigest()
    return f"protected-source-analysis:{digest}"


def analysis_artifact_neutral_content_hash(
    artifact_id: uuid.UUID,
) -> bytes:
    """Return a deterministic non-content SourceAnalysis artifact hash."""
    return hashlib.sha256(
        _NEUTRAL_ANALYSIS_ARTIFACT_HASH_DOMAIN + artifact_id.bytes
    ).digest()


def decode_source_analysis_semantics(
    plaintext: bytes,
) -> ProtectedSourceAnalysisSemantics:
    """Validate and decode one protected SourceAnalysis question payload."""
    try:
        payload = json.loads(plaintext.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceProtectedSemanticIntegrityError(
            "Protected SourceAnalysis payload is not valid canonical JSON."
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
            "Protected SourceAnalysis payload has an invalid envelope."
        )

    if (
        payload["semantic_kind"] != ANALYSIS_SEMANTIC_KIND
        or payload["payload_version"] != ANALYSIS_PAYLOAD_VERSION
    ):
        raise SourceProtectedSemanticIntegrityError(
            "Protected SourceAnalysis payload version is unsupported."
        )

    try:
        analysis_id = uuid.UUID(str(payload["entity_id"]))
    except ValueError as exc:
        raise SourceProtectedSemanticIntegrityError(
            "Protected SourceAnalysis payload has an invalid entity ID."
        ) from exc

    fields = payload["fields"]

    if not isinstance(fields, dict) or set(fields) != {"question"}:
        raise SourceProtectedSemanticIntegrityError(
            "Protected SourceAnalysis payload fields are invalid."
        )

    question = fields["question"]

    if not isinstance(question, str) or not question.strip():
        raise SourceProtectedSemanticIntegrityError(
            "Protected SourceAnalysis question is invalid."
        )

    return ProtectedSourceAnalysisSemantics(
        analysis_id=analysis_id,
        question=question,
    )


def decode_source_analysis_artifact_semantics(
    plaintext: bytes,
) -> ProtectedSourceAnalysisArtifactSemantics:
    """Validate and decode one protected SourceAnalysis artifact payload."""
    try:
        payload = json.loads(plaintext.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceProtectedSemanticIntegrityError(
            "Protected SourceAnalysis artifact payload is not valid canonical JSON."
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
            "Protected SourceAnalysis artifact payload has an invalid envelope."
        )

    if (
        payload["semantic_kind"] != ANALYSIS_ARTIFACT_SEMANTIC_KIND
        or payload["payload_version"] != ANALYSIS_ARTIFACT_PAYLOAD_VERSION
    ):
        raise SourceProtectedSemanticIntegrityError(
            "Protected SourceAnalysis artifact payload version is unsupported."
        )

    try:
        artifact_id = uuid.UUID(str(payload["entity_id"]))
    except ValueError as exc:
        raise SourceProtectedSemanticIntegrityError(
            "Protected SourceAnalysis artifact payload has an invalid entity ID."
        ) from exc

    fields = payload["fields"]

    if (
        not isinstance(fields, dict)
        or set(fields)
        != {
            "analysis_id",
            "content_hash_hex",
            "content_json",
        }
    ):
        raise SourceProtectedSemanticIntegrityError(
            "Protected SourceAnalysis artifact payload fields are invalid."
        )

    try:
        analysis_id = uuid.UUID(str(fields["analysis_id"]))
    except ValueError as exc:
        raise SourceProtectedSemanticIntegrityError(
            "Protected SourceAnalysis artifact has an invalid Analysis ID."
        ) from exc

    content_json = fields["content_json"]
    content_hash_hex = fields["content_hash_hex"]

    if not isinstance(content_json, str):
        raise SourceProtectedSemanticIntegrityError(
            "Protected SourceAnalysis artifact content is invalid."
        )

    try:
        json.loads(content_json)
    except json.JSONDecodeError as exc:
        raise SourceProtectedSemanticIntegrityError(
            "Protected SourceAnalysis artifact content is not valid JSON."
        ) from exc

    if not isinstance(content_hash_hex, str):
        raise SourceProtectedSemanticIntegrityError(
            "Protected SourceAnalysis artifact hash is invalid."
        )

    try:
        content_hash = bytes.fromhex(content_hash_hex)
    except ValueError as exc:
        raise SourceProtectedSemanticIntegrityError(
            "Protected SourceAnalysis artifact hash is invalid."
        ) from exc

    if len(content_hash) != 32:
        raise SourceProtectedSemanticIntegrityError(
            "Protected SourceAnalysis artifact hash is not SHA-256."
        )

    expected_hash = hashlib.sha256(
        content_json.encode("utf-8")
    ).digest()

    if content_hash != expected_hash:
        raise SourceProtectedSemanticIntegrityError(
            "Protected SourceAnalysis artifact hash disagrees with content."
        )

    return ProtectedSourceAnalysisArtifactSemantics(
        artifact_id=artifact_id,
        analysis_id=analysis_id,
        content_json=content_json,
        content_hash=content_hash,
    )


@dataclass(frozen=True, slots=True)
class ProtectedSourceExtractionArtifactEntry:
    artifact_id: uuid.UUID
    content_json: str
    content_hash: bytes


@dataclass(frozen=True, slots=True)
class ProtectedSourceExtractionArtifactSemantics:
    extraction_id: uuid.UUID
    artifacts: tuple[ProtectedSourceExtractionArtifactEntry, ...]


def extraction_artifact_neutral_content_hash(
    artifact_id: uuid.UUID,
) -> bytes:
    """Return a deterministic non-content SourceExtraction artifact hash."""
    return hashlib.sha256(
        _NEUTRAL_EXTRACTION_ARTIFACT_HASH_DOMAIN + artifact_id.bytes
    ).digest()


def decode_source_extraction_artifact_semantics(
    plaintext: bytes,
) -> ProtectedSourceExtractionArtifactSemantics:
    """Validate and decode one protected SourceExtraction artifact-set payload."""
    try:
        payload = json.loads(plaintext.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceProtectedSemanticIntegrityError(
            "Protected SourceExtraction artifact payload is not valid canonical JSON."
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
            "Protected SourceExtraction artifact payload has an invalid envelope."
        )

    if (
        payload["semantic_kind"] != EXTRACTION_ARTIFACT_SEMANTIC_KIND
        or payload["payload_version"] != EXTRACTION_ARTIFACT_PAYLOAD_VERSION
    ):
        raise SourceProtectedSemanticIntegrityError(
            "Protected SourceExtraction artifact payload version is unsupported."
        )

    try:
        extraction_id = uuid.UUID(str(payload["entity_id"]))
    except ValueError as exc:
        raise SourceProtectedSemanticIntegrityError(
            "Protected SourceExtraction artifact payload has an invalid entity ID."
        ) from exc

    fields = payload["fields"]
    if not isinstance(fields, dict) or set(fields) != {"artifacts"}:
        raise SourceProtectedSemanticIntegrityError(
            "Protected SourceExtraction artifact payload fields are invalid."
        )

    raw_artifacts = fields["artifacts"]
    if not isinstance(raw_artifacts, list):
        raise SourceProtectedSemanticIntegrityError(
            "Protected SourceExtraction artifact entries are invalid."
        )

    artifacts: list[ProtectedSourceExtractionArtifactEntry] = []
    seen_ids: set[uuid.UUID] = set()

    for raw in raw_artifacts:
        if (
            not isinstance(raw, dict)
            or set(raw)
            != {
                "artifact_id",
                "content_hash_hex",
                "content_json",
            }
        ):
            raise SourceProtectedSemanticIntegrityError(
                "Protected SourceExtraction artifact entry is invalid."
            )

        try:
            artifact_id = uuid.UUID(str(raw["artifact_id"]))
        except ValueError as exc:
            raise SourceProtectedSemanticIntegrityError(
                "Protected SourceExtraction artifact has an invalid artifact ID."
            ) from exc

        if artifact_id in seen_ids:
            raise SourceProtectedSemanticIntegrityError(
                "Protected SourceExtraction artifact payload contains duplicate artifacts."
            )
        seen_ids.add(artifact_id)

        content_json = raw["content_json"]
        content_hash_hex = raw["content_hash_hex"]

        if not isinstance(content_json, str):
            raise SourceProtectedSemanticIntegrityError(
                "Protected SourceExtraction artifact content is invalid."
            )

        try:
            json.loads(content_json)
        except json.JSONDecodeError as exc:
            raise SourceProtectedSemanticIntegrityError(
                "Protected SourceExtraction artifact content is not valid JSON."
            ) from exc

        if not isinstance(content_hash_hex, str):
            raise SourceProtectedSemanticIntegrityError(
                "Protected SourceExtraction artifact hash is invalid."
            )

        try:
            content_hash = bytes.fromhex(content_hash_hex)
        except ValueError as exc:
            raise SourceProtectedSemanticIntegrityError(
                "Protected SourceExtraction artifact hash is invalid."
            ) from exc

        if len(content_hash) != 32:
            raise SourceProtectedSemanticIntegrityError(
                "Protected SourceExtraction artifact hash is not SHA-256."
            )

        if hashlib.sha256(content_json.encode("utf-8")).digest() != content_hash:
            raise SourceProtectedSemanticIntegrityError(
                "Protected SourceExtraction artifact hash disagrees with content."
            )

        artifacts.append(
            ProtectedSourceExtractionArtifactEntry(
                artifact_id=artifact_id,
                content_json=content_json,
                content_hash=content_hash,
            )
        )

    if tuple(item.artifact_id.bytes for item in artifacts) != tuple(
        sorted(item.artifact_id.bytes for item in artifacts)
    ):
        raise SourceProtectedSemanticIntegrityError(
            "Protected SourceExtraction artifact ordering is invalid."
        )

    return ProtectedSourceExtractionArtifactSemantics(
        extraction_id=extraction_id,
        artifacts=tuple(artifacts),
    )



@dataclass(frozen=True, slots=True)
class ProtectedSourceExtractionSnapshotEntry:
    processing_run_id: uuid.UUID
    final_artifact_id: uuid.UUID
    evidence_json: str
    proposals_json: str


@dataclass(frozen=True, slots=True)
class ProtectedSourceExtractionSnapshotSemantics:
    analysis_id: uuid.UUID
    snapshots: tuple[ProtectedSourceExtractionSnapshotEntry, ...]


def _validate_source_extraction_snapshot_semantic_json(
    evidence_json: str,
    proposals_json: str,
) -> None:
    try:
        evidence = json.loads(evidence_json)
        proposals = json.loads(proposals_json)
    except json.JSONDecodeError as exc:
        raise SourceProtectedSemanticIntegrityError(
            "SourceExtraction snapshot semantics are not valid JSON."
        ) from exc

    if (
        not isinstance(evidence, dict)
        or set(evidence) != {"items"}
        or not isinstance(evidence["items"], list)
    ):
        raise SourceProtectedSemanticIntegrityError(
            "SourceExtraction snapshot evidence is invalid."
        )

    seen_anchor_ids: set[uuid.UUID] = set()
    for expected_sequence, item in enumerate(evidence["items"], 1):
        if (
            not isinstance(item, dict)
            or set(item) != {"anchor_id", "quoted_hash", "sequence_no"}
            or item["sequence_no"] != expected_sequence
            or isinstance(item["sequence_no"], bool)
        ):
            raise SourceProtectedSemanticIntegrityError(
                "SourceExtraction snapshot evidence slots are invalid."
            )

        try:
            anchor_id = uuid.UUID(str(item["anchor_id"]))
        except ValueError as exc:
            raise SourceProtectedSemanticIntegrityError(
                "SourceExtraction snapshot evidence has an invalid SourceAnchor ID."
            ) from exc

        if anchor_id in seen_anchor_ids:
            raise SourceProtectedSemanticIntegrityError(
                "SourceExtraction snapshot evidence contains duplicate SourceAnchors."
            )
        seen_anchor_ids.add(anchor_id)

        quoted_hash = item["quoted_hash"]
        if not isinstance(quoted_hash, str):
            raise SourceProtectedSemanticIntegrityError(
                "SourceExtraction snapshot evidence hash is invalid."
            )

        try:
            digest = bytes.fromhex(quoted_hash)
        except ValueError as exc:
            raise SourceProtectedSemanticIntegrityError(
                "SourceExtraction snapshot evidence hash is invalid."
            ) from exc

        if len(digest) != 32:
            raise SourceProtectedSemanticIntegrityError(
                "SourceExtraction snapshot evidence hash is not SHA-256."
            )

    if (
        not isinstance(proposals, dict)
        or set(proposals)
        != {
            "claims",
            "knowledge_units",
            "merge_candidates",
            "relations",
        }
        or not all(
            isinstance(proposals[name], list)
            for name in (
                "claims",
                "knowledge_units",
                "merge_candidates",
                "relations",
            )
        )
    ):
        raise SourceProtectedSemanticIntegrityError(
            "SourceExtraction snapshot proposals are invalid."
        )


def decode_source_extraction_snapshot_semantics(
    plaintext: bytes,
) -> ProtectedSourceExtractionSnapshotSemantics:
    """Validate and decode one protected SourceExtraction snapshot-set payload."""
    try:
        payload = json.loads(plaintext.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceProtectedSemanticIntegrityError(
            "Protected SourceExtraction snapshot payload is not valid canonical JSON."
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
            "Protected SourceExtraction snapshot payload has an invalid envelope."
        )

    if (
        payload["semantic_kind"] != EXTRACTION_SNAPSHOT_SEMANTIC_KIND
        or payload["payload_version"] != EXTRACTION_SNAPSHOT_PAYLOAD_VERSION
    ):
        raise SourceProtectedSemanticIntegrityError(
            "Protected SourceExtraction snapshot payload version is unsupported."
        )

    try:
        analysis_id = uuid.UUID(str(payload["entity_id"]))
    except ValueError as exc:
        raise SourceProtectedSemanticIntegrityError(
            "Protected SourceExtraction snapshot payload has an invalid Analysis ID."
        ) from exc

    fields = payload["fields"]
    if not isinstance(fields, dict) or set(fields) != {"snapshots"}:
        raise SourceProtectedSemanticIntegrityError(
            "Protected SourceExtraction snapshot payload fields are invalid."
        )

    raw_snapshots = fields["snapshots"]
    if not isinstance(raw_snapshots, list):
        raise SourceProtectedSemanticIntegrityError(
            "Protected SourceExtraction snapshot entries are invalid."
        )

    snapshots: list[ProtectedSourceExtractionSnapshotEntry] = []
    seen_run_ids: set[uuid.UUID] = set()

    for raw in raw_snapshots:
        if (
            not isinstance(raw, dict)
            or set(raw)
            != {
                "evidence_json",
                "final_artifact_id",
                "processing_run_id",
                "proposals_json",
            }
        ):
            raise SourceProtectedSemanticIntegrityError(
                "Protected SourceExtraction snapshot entry is invalid."
            )

        try:
            processing_run_id = uuid.UUID(str(raw["processing_run_id"]))
            final_artifact_id = uuid.UUID(str(raw["final_artifact_id"]))
        except ValueError as exc:
            raise SourceProtectedSemanticIntegrityError(
                "Protected SourceExtraction snapshot identity is invalid."
            ) from exc

        if processing_run_id in seen_run_ids:
            raise SourceProtectedSemanticIntegrityError(
                "Protected SourceExtraction snapshot payload contains duplicate runs."
            )
        seen_run_ids.add(processing_run_id)

        evidence_json = raw["evidence_json"]
        proposals_json = raw["proposals_json"]

        if not isinstance(evidence_json, str) or not isinstance(proposals_json, str):
            raise SourceProtectedSemanticIntegrityError(
                "Protected SourceExtraction snapshot semantic JSON is invalid."
            )

        _validate_source_extraction_snapshot_semantic_json(
            evidence_json,
            proposals_json,
        )

        snapshots.append(
            ProtectedSourceExtractionSnapshotEntry(
                processing_run_id=processing_run_id,
                final_artifact_id=final_artifact_id,
                evidence_json=evidence_json,
                proposals_json=proposals_json,
            )
        )

    if tuple(item.processing_run_id.bytes for item in snapshots) != tuple(
        sorted(item.processing_run_id.bytes for item in snapshots)
    ):
        raise SourceProtectedSemanticIntegrityError(
            "Protected SourceExtraction snapshot ordering is invalid."
        )

    return ProtectedSourceExtractionSnapshotSemantics(
        analysis_id=analysis_id,
        snapshots=tuple(snapshots),
    )


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

    def protect_anchor_semantics(
        self,
        connection: sqlite3.Connection,
        *,
        source_id: uuid.UUID,
        anchor_id: uuid.UUID,
        protection_scope_id: uuid.UUID,
        payload_writer: ProtectedSemanticPayloadWriter,
        now_us: int | None = None,
    ) -> SourceProtectedSemanticMapping:
        """Protect one SourceAnchor semantic payload in the caller transaction."""
        if not connection.in_transaction:
            raise RuntimeError(
                "Protected Source semantic cutover requires an active transaction."
            )

        row = connection.execute(
            """
            SELECT anchor_id, source_id, geometry_json, quoted_hash
            FROM source_anchors
            WHERE anchor_id = ?
            """,
            (uuid_to_blob(anchor_id),),
        ).fetchone()

        if row is None:
            raise SourceProtectedSemanticNotFoundError(str(anchor_id))

        actual_source_id = uuid_from_blob(bytes(row["source_id"]))

        if actual_source_id != source_id:
            raise SourceProtectedSemanticIntegrityError(
                "SourceAnchor does not belong to the requested Source."
            )

        self._require_active_scope(
            connection,
            protection_scope_id,
        )

        created_at_us = utc_now_us() if now_us is None else now_us

        return self._protect_anchor_semantic_row(
            connection,
            row=row,
            source_id=source_id,
            protection_scope_id=protection_scope_id,
            payload_writer=payload_writer,
            created_at_us=created_at_us,
        )

    def protect_source_anchor_semantics(
        self,
        connection: sqlite3.Connection,
        *,
        source_id: uuid.UUID,
        protection_scope_id: uuid.UUID,
        payload_writer: ProtectedSemanticPayloadWriter,
        now_us: int | None = None,
    ) -> tuple[SourceProtectedSemanticMapping, ...]:
        """Protect all persisted SourceAnchor semantics for one Source."""
        if not connection.in_transaction:
            raise RuntimeError(
                "Protected Source semantic cutover requires an active transaction."
            )

        self._require_source(
            connection,
            source_id,
        )

        self._require_active_scope(
            connection,
            protection_scope_id,
        )

        rows = connection.execute(
            """
            SELECT anchor_id, source_id, geometry_json, quoted_hash
            FROM source_anchors
            WHERE source_id = ?
            ORDER BY anchor_id
            """,
            (uuid_to_blob(source_id),),
        ).fetchall()

        if not rows:
            return ()

        created_at_us = utc_now_us() if now_us is None else now_us

        return tuple(
            self._protect_anchor_semantic_row(
                connection,
                row=row,
                source_id=source_id,
                protection_scope_id=protection_scope_id,
                payload_writer=payload_writer,
                created_at_us=created_at_us,
            )
            for row in rows
        )

    def _protect_anchor_semantic_row(
        self,
        connection: sqlite3.Connection,
        *,
        row: sqlite3.Row,
        source_id: uuid.UUID,
        protection_scope_id: uuid.UUID,
        payload_writer: ProtectedSemanticPayloadWriter,
        created_at_us: int,
    ) -> SourceProtectedSemanticMapping:
        anchor_id = uuid_from_blob(bytes(row["anchor_id"]))
        actual_source_id = uuid_from_blob(bytes(row["source_id"]))

        if actual_source_id != source_id:
            raise SourceProtectedSemanticIntegrityError(
                "SourceAnchor does not belong to the requested Source."
            )

        geometry_json = (
            None
            if row["geometry_json"] is None
            else str(row["geometry_json"])
        )

        quoted_hash = (
            None
            if row["quoted_hash"] is None
            else bytes(row["quoted_hash"])
        )

        existing = self._mapping_for(
            connection,
            source_id=source_id,
            semantic_kind=ANCHOR_SEMANTIC_KIND,
            entity_id=anchor_id,
        )

        neutral_hash = anchor_neutral_quoted_hash(anchor_id)

        if existing is not None:
            self._require_existing_mapping(
                connection,
                existing,
                semantic_kind=ANCHOR_SEMANTIC_KIND,
                payload_version=ANCHOR_PAYLOAD_VERSION,
                protection_scope_id=protection_scope_id,
            )

            if (
                geometry_json != _NEUTRAL_ANCHOR_GEOMETRY_JSON
                or quoted_hash != neutral_hash
            ):
                raise SourceProtectedSemanticIntegrityError(
                    "Protected SourceAnchor is not fully neutralized."
                )

            return existing

        if quoted_hash is not None and len(quoted_hash) != 32:
            raise SourceProtectedSemanticIntegrityError(
                "SourceAnchor quoted hash is invalid."
            )

        if geometry_json is not None:
            try:
                json.loads(geometry_json)
            except json.JSONDecodeError as exc:
                raise SourceProtectedSemanticIntegrityError(
                    "SourceAnchor geometry is not valid JSON."
                ) from exc

        if quoted_hash == neutral_hash:
            raise SourceProtectedSemanticIntegrityError(
                "SourceAnchor appears neutralized without a protected mapping."
            )

        plaintext = self._encode_anchor_semantics(
            anchor_id=anchor_id,
            geometry_json=geometry_json,
            quoted_hash=quoted_hash,
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
            semantic_kind=ANCHOR_SEMANTIC_KIND,
            entity_id=anchor_id,
            protection_scope_id=protection_scope_id,
            protected_payload_id=protected_payload_id,
            payload_version=ANCHOR_PAYLOAD_VERSION,
            created_at_us=created_at_us,
        )

        updated = connection.execute(
            """
            UPDATE source_anchors
            SET geometry_json = ?,
                quoted_hash = ?
            WHERE anchor_id = ?
              AND source_id = ?
              AND geometry_json IS ?
              AND quoted_hash IS ?
            """,
            (
                _NEUTRAL_ANCHOR_GEOMETRY_JSON,
                neutral_hash,
                uuid_to_blob(anchor_id),
                uuid_to_blob(source_id),
                geometry_json,
                quoted_hash,
            ),
        )

        if updated.rowcount != 1:
            raise SourceProtectedSemanticIntegrityError(
                "SourceAnchor changed during semantic cutover."
            )

        return mapping

    def protect_extraction_evidence_semantics(
        self,
        connection: sqlite3.Connection,
        *,
        source_id: uuid.UUID,
        extraction_id: uuid.UUID,
        protection_scope_id: uuid.UUID,
        payload_writer: ProtectedSemanticPayloadWriter,
        now_us: int | None = None,
    ) -> SourceProtectedSemanticMapping:
        """Protect one SourceExtraction frozen evidence map."""
        if not connection.in_transaction:
            raise RuntimeError(
                "Protected Source semantic cutover requires an active transaction."
            )

        extraction = connection.execute(
            """
            SELECT x.extraction_id, a.source_id
            FROM source_extractions AS x
            JOIN source_analyses AS a
              ON a.analysis_id = x.analysis_id
            WHERE x.extraction_id = ?
            """,
            (uuid_to_blob(extraction_id),),
        ).fetchone()

        if extraction is None:
            raise SourceProtectedSemanticNotFoundError(str(extraction_id))

        actual_source_id = uuid_from_blob(bytes(extraction["source_id"]))

        if actual_source_id != source_id:
            raise SourceProtectedSemanticIntegrityError(
                "SourceExtraction does not belong to the requested Source."
            )

        self._require_active_scope(
            connection,
            protection_scope_id,
        )

        created_at_us = utc_now_us() if now_us is None else now_us
        rows = self._extraction_evidence_rows(
            connection,
            extraction_id,
        )

        return self._protect_extraction_evidence_rows(
            connection,
            rows=rows,
            source_id=source_id,
            extraction_id=extraction_id,
            protection_scope_id=protection_scope_id,
            payload_writer=payload_writer,
            created_at_us=created_at_us,
        )

    def protect_source_extraction_evidence_semantics(
        self,
        connection: sqlite3.Connection,
        *,
        source_id: uuid.UUID,
        protection_scope_id: uuid.UUID,
        payload_writer: ProtectedSemanticPayloadWriter,
        now_us: int | None = None,
    ) -> tuple[SourceProtectedSemanticMapping, ...]:
        """Protect every persisted SourceExtraction evidence map for one Source."""
        if not connection.in_transaction:
            raise RuntimeError(
                "Protected Source semantic cutover requires an active transaction."
            )

        self._require_source(
            connection,
            source_id,
        )
        self._require_active_scope(
            connection,
            protection_scope_id,
        )

        extraction_rows = connection.execute(
            """
            SELECT x.extraction_id
            FROM source_extractions AS x
            JOIN source_analyses AS a
              ON a.analysis_id = x.analysis_id
            WHERE a.source_id = ?
            ORDER BY x.extraction_id
            """,
            (uuid_to_blob(source_id),),
        ).fetchall()

        if not extraction_rows:
            return ()

        created_at_us = utc_now_us() if now_us is None else now_us
        mappings: list[SourceProtectedSemanticMapping] = []

        for extraction_row in extraction_rows:
            extraction_id = uuid_from_blob(
                bytes(extraction_row["extraction_id"])
            )
            rows = self._extraction_evidence_rows(
                connection,
                extraction_id,
            )
            mappings.append(
                self._protect_extraction_evidence_rows(
                    connection,
                    rows=rows,
                    source_id=source_id,
                    extraction_id=extraction_id,
                    protection_scope_id=protection_scope_id,
                    payload_writer=payload_writer,
                    created_at_us=created_at_us,
                )
            )

        return tuple(mappings)

    @staticmethod
    def _extraction_evidence_rows(
        connection: sqlite3.Connection,
        extraction_id: uuid.UUID,
    ) -> list[sqlite3.Row]:
        return connection.execute(
            """
            SELECT
                e.sequence_no,
                e.source_anchor_id,
                e.quoted_hash,
                a.source_id AS anchor_source_id
            FROM source_extraction_evidence AS e
            JOIN source_anchors AS a
              ON a.anchor_id = e.source_anchor_id
            WHERE e.extraction_id = ?
            ORDER BY e.sequence_no
            """,
            (uuid_to_blob(extraction_id),),
        ).fetchall()

    def _protect_extraction_evidence_rows(
        self,
        connection: sqlite3.Connection,
        *,
        rows: list[sqlite3.Row],
        source_id: uuid.UUID,
        extraction_id: uuid.UUID,
        protection_scope_id: uuid.UUID,
        payload_writer: ProtectedSemanticPayloadWriter,
        created_at_us: int,
    ) -> SourceProtectedSemanticMapping:
        existing = self._mapping_for(
            connection,
            source_id=source_id,
            semantic_kind=EXTRACTION_EVIDENCE_SEMANTIC_KIND,
            entity_id=extraction_id,
        )

        if not rows:
            if existing is not None:
                raise SourceProtectedSemanticIntegrityError(
                    "Protected SourceExtraction evidence mapping exists "
                    "but the public evidence map is missing."
                )
            raise SourceProtectedSemanticIntegrityError(
                "SourceExtraction has no frozen evidence rows."
            )

        evidence: list[tuple[int, uuid.UUID, bytes]] = []
        seen_anchor_ids: set[uuid.UUID] = set()

        for expected_sequence, row in enumerate(rows, 1):
            sequence_no = int(row["sequence_no"])
            source_anchor_id = uuid_from_blob(
                bytes(row["source_anchor_id"])
            )
            quoted_hash = bytes(row["quoted_hash"])
            anchor_source_id = uuid_from_blob(
                bytes(row["anchor_source_id"])
            )

            if sequence_no != expected_sequence:
                raise SourceProtectedSemanticIntegrityError(
                    "SourceExtraction evidence slots are not contiguous."
                )

            if source_anchor_id in seen_anchor_ids:
                raise SourceProtectedSemanticIntegrityError(
                    "SourceExtraction evidence contains duplicate SourceAnchors."
                )
            seen_anchor_ids.add(source_anchor_id)

            if anchor_source_id != source_id:
                raise SourceProtectedSemanticIntegrityError(
                    "SourceExtraction evidence crossed the requested Source."
                )

            if len(quoted_hash) != 32:
                raise SourceProtectedSemanticIntegrityError(
                    "SourceExtraction evidence hash is invalid."
                )

            evidence.append(
                (
                    sequence_no,
                    source_anchor_id,
                    quoted_hash,
                )
            )

        frozen = tuple(evidence)

        if existing is not None:
            self._require_existing_mapping(
                connection,
                existing,
                semantic_kind=EXTRACTION_EVIDENCE_SEMANTIC_KIND,
                payload_version=EXTRACTION_EVIDENCE_PAYLOAD_VERSION,
                protection_scope_id=protection_scope_id,
            )

            for sequence_no, source_anchor_id, quoted_hash in frozen:
                if quoted_hash != extraction_evidence_neutral_quoted_hash(
                    extraction_id,
                    sequence_no,
                    source_anchor_id,
                ):
                    raise SourceProtectedSemanticIntegrityError(
                        "Protected SourceExtraction evidence is not fully neutralized."
                    )

            return existing

        for sequence_no, source_anchor_id, quoted_hash in frozen:
            if quoted_hash == extraction_evidence_neutral_quoted_hash(
                extraction_id,
                sequence_no,
                source_anchor_id,
            ):
                raise SourceProtectedSemanticIntegrityError(
                    "SourceExtraction evidence appears neutralized "
                    "without a protected mapping."
                )

        plaintext = self._encode_extraction_evidence_semantics(
            extraction_id=extraction_id,
            evidence=frozen,
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
            semantic_kind=EXTRACTION_EVIDENCE_SEMANTIC_KIND,
            entity_id=extraction_id,
            protection_scope_id=protection_scope_id,
            protected_payload_id=protected_payload_id,
            payload_version=EXTRACTION_EVIDENCE_PAYLOAD_VERSION,
            created_at_us=created_at_us,
        )

        for sequence_no, source_anchor_id, original_hash in frozen:
            neutral_hash = extraction_evidence_neutral_quoted_hash(
                extraction_id,
                sequence_no,
                source_anchor_id,
            )
            updated = connection.execute(
                """
                UPDATE source_extraction_evidence
                SET quoted_hash = ?
                WHERE extraction_id = ?
                  AND sequence_no = ?
                  AND source_anchor_id = ?
                  AND quoted_hash = ?
                """,
                (
                    neutral_hash,
                    uuid_to_blob(extraction_id),
                    sequence_no,
                    uuid_to_blob(source_anchor_id),
                    original_hash,
                ),
            )

            if updated.rowcount != 1:
                raise SourceProtectedSemanticIntegrityError(
                    "SourceExtraction evidence changed during semantic cutover."
                )

        return mapping

    def protect_analysis_semantics(
        self,
        connection: sqlite3.Connection,
        *,
        source_id: uuid.UUID,
        analysis_id: uuid.UUID,
        protection_scope_id: uuid.UUID,
        payload_writer: ProtectedSemanticPayloadWriter,
        now_us: int | None = None,
    ) -> tuple[SourceProtectedSemanticMapping, ...]:
        """Protect one SourceAnalysis question and all persisted artifacts."""
        if not connection.in_transaction:
            raise RuntimeError(
                "Protected Source semantic cutover requires an active transaction."
            )

        row = connection.execute(
            """
            SELECT analysis_id, source_id, question
            FROM source_analyses
            WHERE analysis_id = ?
            """,
            (uuid_to_blob(analysis_id),),
        ).fetchone()

        if row is None:
            raise SourceProtectedSemanticNotFoundError(str(analysis_id))

        actual_source_id = uuid_from_blob(bytes(row["source_id"]))

        if actual_source_id != source_id:
            raise SourceProtectedSemanticIntegrityError(
                "SourceAnalysis does not belong to the requested Source."
            )

        self._require_active_scope(
            connection,
            protection_scope_id,
        )

        created_at_us = utc_now_us() if now_us is None else now_us

        question_mapping = self._protect_analysis_question_row(
            connection,
            row=row,
            source_id=source_id,
            analysis_id=analysis_id,
            protection_scope_id=protection_scope_id,
            payload_writer=payload_writer,
            created_at_us=created_at_us,
        )

        artifact_rows = self._analysis_artifact_rows(
            connection,
            analysis_id,
        )

        artifact_mappings = tuple(
            self._protect_analysis_artifact_row(
                connection,
                row=artifact_row,
                source_id=source_id,
                analysis_id=analysis_id,
                protection_scope_id=protection_scope_id,
                payload_writer=payload_writer,
                created_at_us=created_at_us,
            )
            for artifact_row in artifact_rows
        )

        return (
            question_mapping,
            *artifact_mappings,
        )

    def protect_source_analysis_semantics(
        self,
        connection: sqlite3.Connection,
        *,
        source_id: uuid.UUID,
        protection_scope_id: uuid.UUID,
        payload_writer: ProtectedSemanticPayloadWriter,
        now_us: int | None = None,
    ) -> tuple[SourceProtectedSemanticMapping, ...]:
        """Protect every persisted SourceAnalysis semantic row for one Source."""
        if not connection.in_transaction:
            raise RuntimeError(
                "Protected Source semantic cutover requires an active transaction."
            )

        self._require_source(
            connection,
            source_id,
        )
        self._require_active_scope(
            connection,
            protection_scope_id,
        )

        rows = connection.execute(
            """
            SELECT analysis_id
            FROM source_analyses
            WHERE source_id = ?
            ORDER BY analysis_id
            """,
            (uuid_to_blob(source_id),),
        ).fetchall()

        if not rows:
            return ()

        created_at_us = utc_now_us() if now_us is None else now_us
        mappings: list[SourceProtectedSemanticMapping] = []

        for row in rows:
            analysis_id = uuid_from_blob(bytes(row["analysis_id"]))
            mappings.extend(
                self.protect_analysis_semantics(
                    connection,
                    source_id=source_id,
                    analysis_id=analysis_id,
                    protection_scope_id=protection_scope_id,
                    payload_writer=payload_writer,
                    now_us=created_at_us,
                )
            )

        return tuple(mappings)

    @staticmethod
    def _analysis_artifact_rows(
        connection: sqlite3.Connection,
        analysis_id: uuid.UUID,
    ) -> list[sqlite3.Row]:
        return connection.execute(
            """
            SELECT
                a.artifact_id,
                a.analysis_id,
                a.content_json,
                a.content_hash,
                s.source_id
            FROM source_analysis_artifacts AS a
            JOIN source_analyses AS s
              ON s.analysis_id = a.analysis_id
            WHERE a.analysis_id = ?
            ORDER BY a.artifact_id
            """,
            (uuid_to_blob(analysis_id),),
        ).fetchall()

    def _protect_analysis_question_row(
        self,
        connection: sqlite3.Connection,
        *,
        row: sqlite3.Row,
        source_id: uuid.UUID,
        analysis_id: uuid.UUID,
        protection_scope_id: uuid.UUID,
        payload_writer: ProtectedSemanticPayloadWriter,
        created_at_us: int,
    ) -> SourceProtectedSemanticMapping:
        actual_analysis_id = uuid_from_blob(bytes(row["analysis_id"]))
        actual_source_id = uuid_from_blob(bytes(row["source_id"]))

        if actual_analysis_id != analysis_id or actual_source_id != source_id:
            raise SourceProtectedSemanticIntegrityError(
                "SourceAnalysis identity changed during semantic cutover."
            )

        question = str(row["question"])
        neutral_question = analysis_neutral_question(analysis_id)

        existing = self._mapping_for(
            connection,
            source_id=source_id,
            semantic_kind=ANALYSIS_SEMANTIC_KIND,
            entity_id=analysis_id,
        )

        if existing is not None:
            self._require_existing_mapping(
                connection,
                existing,
                semantic_kind=ANALYSIS_SEMANTIC_KIND,
                payload_version=ANALYSIS_PAYLOAD_VERSION,
                protection_scope_id=protection_scope_id,
            )

            if question != neutral_question:
                raise SourceProtectedSemanticIntegrityError(
                    "Protected SourceAnalysis is not fully neutralized."
                )

            return existing

        if not question.strip():
            raise SourceProtectedSemanticIntegrityError(
                "SourceAnalysis question is empty."
            )

        if question == neutral_question:
            raise SourceProtectedSemanticIntegrityError(
                "SourceAnalysis appears neutralized without a protected mapping."
            )

        plaintext = self._encode_analysis_semantics(
            analysis_id=analysis_id,
            question=question,
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
            semantic_kind=ANALYSIS_SEMANTIC_KIND,
            entity_id=analysis_id,
            protection_scope_id=protection_scope_id,
            protected_payload_id=protected_payload_id,
            payload_version=ANALYSIS_PAYLOAD_VERSION,
            created_at_us=created_at_us,
        )

        updated = connection.execute(
            """
            UPDATE source_analyses
            SET question = ?
            WHERE analysis_id = ?
              AND source_id = ?
              AND question = ?
            """,
            (
                neutral_question,
                uuid_to_blob(analysis_id),
                uuid_to_blob(source_id),
                question,
            ),
        )

        if updated.rowcount != 1:
            raise SourceProtectedSemanticIntegrityError(
                "SourceAnalysis changed during semantic cutover."
            )

        return mapping

    def _protect_analysis_artifact_row(
        self,
        connection: sqlite3.Connection,
        *,
        row: sqlite3.Row,
        source_id: uuid.UUID,
        analysis_id: uuid.UUID,
        protection_scope_id: uuid.UUID,
        payload_writer: ProtectedSemanticPayloadWriter,
        created_at_us: int,
    ) -> SourceProtectedSemanticMapping:
        artifact_id = uuid_from_blob(bytes(row["artifact_id"]))
        actual_analysis_id = uuid_from_blob(bytes(row["analysis_id"]))
        actual_source_id = uuid_from_blob(bytes(row["source_id"]))

        if actual_analysis_id != analysis_id or actual_source_id != source_id:
            raise SourceProtectedSemanticIntegrityError(
                "SourceAnalysis artifact crossed the requested Source."
            )

        content_json = str(row["content_json"])
        content_hash = bytes(row["content_hash"])
        neutral_hash = analysis_artifact_neutral_content_hash(artifact_id)

        existing = self._mapping_for(
            connection,
            source_id=source_id,
            semantic_kind=ANALYSIS_ARTIFACT_SEMANTIC_KIND,
            entity_id=artifact_id,
        )

        if existing is not None:
            self._require_existing_mapping(
                connection,
                existing,
                semantic_kind=ANALYSIS_ARTIFACT_SEMANTIC_KIND,
                payload_version=ANALYSIS_ARTIFACT_PAYLOAD_VERSION,
                protection_scope_id=protection_scope_id,
            )

            if (
                content_json != ANALYSIS_NEUTRAL_ARTIFACT_CONTENT_JSON
                or content_hash != neutral_hash
            ):
                raise SourceProtectedSemanticIntegrityError(
                    "Protected SourceAnalysis artifact is not fully neutralized."
                )

            return existing

        if len(content_hash) != 32:
            raise SourceProtectedSemanticIntegrityError(
                "SourceAnalysis artifact hash is invalid."
            )

        try:
            json.loads(content_json)
        except json.JSONDecodeError as exc:
            raise SourceProtectedSemanticIntegrityError(
                "SourceAnalysis artifact content is not valid JSON."
            ) from exc

        expected_hash = hashlib.sha256(
            content_json.encode("utf-8")
        ).digest()

        if content_hash != expected_hash:
            raise SourceProtectedSemanticIntegrityError(
                "SourceAnalysis artifact hash disagrees with content."
            )

        if (
            content_json == ANALYSIS_NEUTRAL_ARTIFACT_CONTENT_JSON
            and content_hash == neutral_hash
        ):
            raise SourceProtectedSemanticIntegrityError(
                "SourceAnalysis artifact appears neutralized "
                "without a protected mapping."
            )

        plaintext = self._encode_analysis_artifact_semantics(
            artifact_id=artifact_id,
            analysis_id=analysis_id,
            content_json=content_json,
            content_hash=content_hash,
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
            semantic_kind=ANALYSIS_ARTIFACT_SEMANTIC_KIND,
            entity_id=artifact_id,
            protection_scope_id=protection_scope_id,
            protected_payload_id=protected_payload_id,
            payload_version=ANALYSIS_ARTIFACT_PAYLOAD_VERSION,
            created_at_us=created_at_us,
        )

        updated = connection.execute(
            """
            UPDATE source_analysis_artifacts
            SET content_json = ?,
                content_hash = ?
            WHERE artifact_id = ?
              AND analysis_id = ?
              AND content_json = ?
              AND content_hash = ?
            """,
            (
                ANALYSIS_NEUTRAL_ARTIFACT_CONTENT_JSON,
                neutral_hash,
                uuid_to_blob(artifact_id),
                uuid_to_blob(analysis_id),
                content_json,
                content_hash,
            ),
        )

        if updated.rowcount != 1:
            raise SourceProtectedSemanticIntegrityError(
                "SourceAnalysis artifact changed during semantic cutover."
            )

        return mapping


    def protect_extraction_artifact_semantics(
        self,
        connection: sqlite3.Connection,
        *,
        source_id: uuid.UUID,
        extraction_id: uuid.UUID,
        protection_scope_id: uuid.UUID,
        payload_writer: ProtectedSemanticPayloadWriter,
        now_us: int | None = None,
    ) -> SourceProtectedSemanticMapping:
        """Protect the complete persisted artifact set for one SourceExtraction."""
        if not connection.in_transaction:
            raise RuntimeError(
                "Protected Source semantic cutover requires an active transaction."
            )

        extraction = connection.execute(
            """
            SELECT x.extraction_id, a.source_id
            FROM source_extractions AS x
            JOIN source_analyses AS a
              ON a.analysis_id = x.analysis_id
            WHERE x.extraction_id = ?
            """,
            (uuid_to_blob(extraction_id),),
        ).fetchone()

        if extraction is None:
            raise SourceProtectedSemanticNotFoundError(str(extraction_id))

        actual_source_id = uuid_from_blob(bytes(extraction["source_id"]))
        if actual_source_id != source_id:
            raise SourceProtectedSemanticIntegrityError(
                "SourceExtraction does not belong to the requested Source."
            )

        self._require_active_scope(
            connection,
            protection_scope_id,
        )

        created_at_us = utc_now_us() if now_us is None else now_us
        rows = self._extraction_artifact_rows(
            connection,
            extraction_id,
        )

        return self._protect_extraction_artifact_rows(
            connection,
            rows=rows,
            source_id=source_id,
            extraction_id=extraction_id,
            protection_scope_id=protection_scope_id,
            payload_writer=payload_writer,
            created_at_us=created_at_us,
        )

    def protect_source_extraction_artifact_semantics(
        self,
        connection: sqlite3.Connection,
        *,
        source_id: uuid.UUID,
        protection_scope_id: uuid.UUID,
        payload_writer: ProtectedSemanticPayloadWriter,
        now_us: int | None = None,
    ) -> tuple[SourceProtectedSemanticMapping, ...]:
        """Protect every persisted SourceExtraction artifact set for one Source."""
        if not connection.in_transaction:
            raise RuntimeError(
                "Protected Source semantic cutover requires an active transaction."
            )

        self._require_source(
            connection,
            source_id,
        )
        self._require_active_scope(
            connection,
            protection_scope_id,
        )

        extraction_rows = connection.execute(
            """
            SELECT x.extraction_id
            FROM source_extractions AS x
            JOIN source_analyses AS a
              ON a.analysis_id = x.analysis_id
            WHERE a.source_id = ?
            ORDER BY x.extraction_id
            """,
            (uuid_to_blob(source_id),),
        ).fetchall()

        if not extraction_rows:
            return ()

        created_at_us = utc_now_us() if now_us is None else now_us
        mappings: list[SourceProtectedSemanticMapping] = []

        for extraction_row in extraction_rows:
            extraction_id = uuid_from_blob(
                bytes(extraction_row["extraction_id"])
            )
            mappings.append(
                self.protect_extraction_artifact_semantics(
                    connection,
                    source_id=source_id,
                    extraction_id=extraction_id,
                    protection_scope_id=protection_scope_id,
                    payload_writer=payload_writer,
                    now_us=created_at_us,
                )
            )

        return tuple(mappings)

    @staticmethod
    def _extraction_artifact_rows(
        connection: sqlite3.Connection,
        extraction_id: uuid.UUID,
    ) -> list[sqlite3.Row]:
        return connection.execute(
            """
            SELECT
                art.artifact_id,
                art.extraction_id,
                art.content_json,
                art.content_hash,
                a.source_id
            FROM source_extraction_artifacts AS art
            JOIN source_extractions AS x
              ON x.extraction_id = art.extraction_id
            JOIN source_analyses AS a
              ON a.analysis_id = x.analysis_id
            WHERE art.extraction_id = ?
            ORDER BY art.artifact_id
            """,
            (uuid_to_blob(extraction_id),),
        ).fetchall()

    def _protect_extraction_artifact_rows(
        self,
        connection: sqlite3.Connection,
        *,
        rows: list[sqlite3.Row],
        source_id: uuid.UUID,
        extraction_id: uuid.UUID,
        protection_scope_id: uuid.UUID,
        payload_writer: ProtectedSemanticPayloadWriter,
        created_at_us: int,
    ) -> SourceProtectedSemanticMapping:
        existing = self._mapping_for(
            connection,
            source_id=source_id,
            semantic_kind=EXTRACTION_ARTIFACT_SEMANTIC_KIND,
            entity_id=extraction_id,
        )

        frozen: list[tuple[uuid.UUID, str, bytes]] = []

        for row in rows:
            artifact_id = uuid_from_blob(bytes(row["artifact_id"]))
            actual_extraction_id = uuid_from_blob(bytes(row["extraction_id"]))
            actual_source_id = uuid_from_blob(bytes(row["source_id"]))
            content_json = str(row["content_json"])
            content_hash = bytes(row["content_hash"])

            if (
                actual_extraction_id != extraction_id
                or actual_source_id != source_id
            ):
                raise SourceProtectedSemanticIntegrityError(
                    "SourceExtraction artifact crossed the requested Source."
                )

            neutral_hash = extraction_artifact_neutral_content_hash(
                artifact_id
            )

            if existing is not None:
                if (
                    content_json != EXTRACTION_NEUTRAL_ARTIFACT_CONTENT_JSON
                    or content_hash != neutral_hash
                ):
                    raise SourceProtectedSemanticIntegrityError(
                        "Protected SourceExtraction artifacts are not fully neutralized."
                    )

                frozen.append(
                    (
                        artifact_id,
                        content_json,
                        content_hash,
                    )
                )
                continue

            if len(content_hash) != 32:
                raise SourceProtectedSemanticIntegrityError(
                    "SourceExtraction artifact hash is invalid."
                )

            try:
                json.loads(content_json)
            except json.JSONDecodeError as exc:
                raise SourceProtectedSemanticIntegrityError(
                    "SourceExtraction artifact content is not valid JSON."
                ) from exc

            expected_hash = hashlib.sha256(
                content_json.encode("utf-8")
            ).digest()

            if content_hash != expected_hash:
                raise SourceProtectedSemanticIntegrityError(
                    "SourceExtraction artifact hash disagrees with content."
                )

            if (
                content_json == EXTRACTION_NEUTRAL_ARTIFACT_CONTENT_JSON
                and content_hash == neutral_hash
            ):
                raise SourceProtectedSemanticIntegrityError(
                    "SourceExtraction artifact appears neutralized "
                    "without a protected mapping."
                )

            frozen.append(
                (
                    artifact_id,
                    content_json,
                    content_hash,
                )
            )

        if existing is not None:
            self._require_existing_mapping(
                connection,
                existing,
                semantic_kind=EXTRACTION_ARTIFACT_SEMANTIC_KIND,
                payload_version=EXTRACTION_ARTIFACT_PAYLOAD_VERSION,
                protection_scope_id=protection_scope_id,
            )
            return existing

        original_artifacts = tuple(frozen)

        plaintext = self._encode_extraction_artifact_semantics(
            extraction_id=extraction_id,
            artifacts=original_artifacts,
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
            semantic_kind=EXTRACTION_ARTIFACT_SEMANTIC_KIND,
            entity_id=extraction_id,
            protection_scope_id=protection_scope_id,
            protected_payload_id=protected_payload_id,
            payload_version=EXTRACTION_ARTIFACT_PAYLOAD_VERSION,
            created_at_us=created_at_us,
        )

        for artifact_id, content_json, content_hash in original_artifacts:
            updated = connection.execute(
                """
                UPDATE source_extraction_artifacts
                SET content_json = ?,
                    content_hash = ?
                WHERE artifact_id = ?
                  AND extraction_id = ?
                  AND content_json = ?
                  AND content_hash = ?
                """,
                (
                    EXTRACTION_NEUTRAL_ARTIFACT_CONTENT_JSON,
                    extraction_artifact_neutral_content_hash(
                        artifact_id
                    ),
                    uuid_to_blob(artifact_id),
                    uuid_to_blob(extraction_id),
                    content_json,
                    content_hash,
                ),
            )

            if updated.rowcount != 1:
                raise SourceProtectedSemanticIntegrityError(
                    "SourceExtraction artifact changed during semantic cutover."
                )

        return mapping


    def protect_analysis_extraction_snapshot_semantics(
        self,
        connection: sqlite3.Connection,
        *,
        source_id: uuid.UUID,
        analysis_id: uuid.UUID,
        protection_scope_id: uuid.UUID,
        payload_writer: ProtectedSemanticPayloadWriter,
        now_us: int | None = None,
    ) -> SourceProtectedSemanticMapping:
        """Protect every frozen SourceExtraction snapshot for one SourceAnalysis."""
        if not connection.in_transaction:
            raise RuntimeError(
                "Protected Source semantic cutover requires an active transaction."
            )

        analysis = connection.execute(
            """
            SELECT analysis_id, source_id
            FROM source_analyses
            WHERE analysis_id = ?
            """,
            (uuid_to_blob(analysis_id),),
        ).fetchone()

        if analysis is None:
            raise SourceProtectedSemanticNotFoundError(str(analysis_id))

        actual_source_id = uuid_from_blob(bytes(analysis["source_id"]))
        if actual_source_id != source_id:
            raise SourceProtectedSemanticIntegrityError(
                "SourceAnalysis does not belong to the requested Source."
            )

        self._require_active_scope(
            connection,
            protection_scope_id,
        )

        created_at_us = utc_now_us() if now_us is None else now_us
        rows = self._extraction_snapshot_rows(
            connection,
            analysis_id,
        )

        return self._protect_extraction_snapshot_rows(
            connection,
            rows=rows,
            source_id=source_id,
            analysis_id=analysis_id,
            protection_scope_id=protection_scope_id,
            payload_writer=payload_writer,
            created_at_us=created_at_us,
        )

    def protect_source_extraction_snapshot_semantics(
        self,
        connection: sqlite3.Connection,
        *,
        source_id: uuid.UUID,
        protection_scope_id: uuid.UUID,
        payload_writer: ProtectedSemanticPayloadWriter,
        now_us: int | None = None,
    ) -> tuple[SourceProtectedSemanticMapping, ...]:
        """Protect all frozen SourceExtraction snapshot sets for one Source."""
        if not connection.in_transaction:
            raise RuntimeError(
                "Protected Source semantic cutover requires an active transaction."
            )

        self._require_source(
            connection,
            source_id,
        )
        self._require_active_scope(
            connection,
            protection_scope_id,
        )

        analysis_rows = connection.execute(
            """
            SELECT analysis_id
            FROM source_analyses
            WHERE source_id = ?
            ORDER BY analysis_id
            """,
            (uuid_to_blob(source_id),),
        ).fetchall()

        if not analysis_rows:
            return ()

        created_at_us = utc_now_us() if now_us is None else now_us
        mappings: list[SourceProtectedSemanticMapping] = []

        for analysis_row in analysis_rows:
            analysis_id = uuid_from_blob(
                bytes(analysis_row["analysis_id"])
            )
            mappings.append(
                self.protect_analysis_extraction_snapshot_semantics(
                    connection,
                    source_id=source_id,
                    analysis_id=analysis_id,
                    protection_scope_id=protection_scope_id,
                    payload_writer=payload_writer,
                    now_us=created_at_us,
                )
            )

        return tuple(mappings)

    @staticmethod
    def _extraction_snapshot_rows(
        connection: sqlite3.Connection,
        analysis_id: uuid.UUID,
    ) -> list[sqlite3.Row]:
        return connection.execute(
            """
            SELECT
                s.processing_run_id,
                s.analysis_id,
                s.final_artifact_id,
                s.evidence_json,
                s.proposals_json,
                a.source_id,
                f.analysis_id AS final_analysis_id,
                f.artifact_kind AS final_artifact_kind
            FROM source_extraction_result_snapshots AS s
            JOIN source_analyses AS a
              ON a.analysis_id = s.analysis_id
            JOIN source_analysis_artifacts AS f
              ON f.artifact_id = s.final_artifact_id
            WHERE s.analysis_id = ?
            ORDER BY s.processing_run_id
            """,
            (uuid_to_blob(analysis_id),),
        ).fetchall()

    def _protect_extraction_snapshot_rows(
        self,
        connection: sqlite3.Connection,
        *,
        rows: list[sqlite3.Row],
        source_id: uuid.UUID,
        analysis_id: uuid.UUID,
        protection_scope_id: uuid.UUID,
        payload_writer: ProtectedSemanticPayloadWriter,
        created_at_us: int,
    ) -> SourceProtectedSemanticMapping:
        existing = self._mapping_for(
            connection,
            source_id=source_id,
            semantic_kind=EXTRACTION_SNAPSHOT_SEMANTIC_KIND,
            entity_id=analysis_id,
        )

        snapshots: list[
            tuple[uuid.UUID, uuid.UUID, str, str]
        ] = []

        for row in rows:
            processing_run_id = uuid_from_blob(
                bytes(row["processing_run_id"])
            )
            actual_analysis_id = uuid_from_blob(
                bytes(row["analysis_id"])
            )
            final_artifact_id = uuid_from_blob(
                bytes(row["final_artifact_id"])
            )
            actual_source_id = uuid_from_blob(
                bytes(row["source_id"])
            )
            final_analysis_id = uuid_from_blob(
                bytes(row["final_analysis_id"])
            )
            final_artifact_kind = str(row["final_artifact_kind"])
            evidence_json = str(row["evidence_json"])
            proposals_json = str(row["proposals_json"])

            if (
                actual_analysis_id != analysis_id
                or actual_source_id != source_id
                or final_analysis_id != analysis_id
                or final_artifact_kind != "final"
            ):
                raise SourceProtectedSemanticIntegrityError(
                    "SourceExtraction snapshot crossed the requested SourceAnalysis."
                )

            if existing is not None:
                if (
                    evidence_json != EXTRACTION_SNAPSHOT_NEUTRAL_EVIDENCE_JSON
                    or proposals_json != EXTRACTION_SNAPSHOT_NEUTRAL_PROPOSALS_JSON
                ):
                    raise SourceProtectedSemanticIntegrityError(
                        "Protected SourceExtraction snapshots are not fully neutralized."
                    )

                snapshots.append(
                    (
                        processing_run_id,
                        final_artifact_id,
                        evidence_json,
                        proposals_json,
                    )
                )
                continue

            if (
                evidence_json == EXTRACTION_SNAPSHOT_NEUTRAL_EVIDENCE_JSON
                or proposals_json == EXTRACTION_SNAPSHOT_NEUTRAL_PROPOSALS_JSON
            ):
                raise SourceProtectedSemanticIntegrityError(
                    "SourceExtraction snapshot appears neutralized "
                    "without a protected mapping."
                )

            _validate_source_extraction_snapshot_semantic_json(
                evidence_json,
                proposals_json,
            )

            snapshots.append(
                (
                    processing_run_id,
                    final_artifact_id,
                    evidence_json,
                    proposals_json,
                )
            )

        if existing is not None:
            self._require_existing_mapping(
                connection,
                existing,
                semantic_kind=EXTRACTION_SNAPSHOT_SEMANTIC_KIND,
                payload_version=EXTRACTION_SNAPSHOT_PAYLOAD_VERSION,
                protection_scope_id=protection_scope_id,
            )
            return existing

        original_snapshots = tuple(snapshots)

        plaintext = self._encode_extraction_snapshot_semantics(
            analysis_id=analysis_id,
            snapshots=original_snapshots,
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
            semantic_kind=EXTRACTION_SNAPSHOT_SEMANTIC_KIND,
            entity_id=analysis_id,
            protection_scope_id=protection_scope_id,
            protected_payload_id=protected_payload_id,
            payload_version=EXTRACTION_SNAPSHOT_PAYLOAD_VERSION,
            created_at_us=created_at_us,
        )

        for (
            processing_run_id,
            _final_artifact_id,
            evidence_json,
            proposals_json,
        ) in original_snapshots:
            updated = connection.execute(
                """
                UPDATE source_extraction_result_snapshots
                SET evidence_json = ?,
                    proposals_json = ?
                WHERE processing_run_id = ?
                  AND analysis_id = ?
                  AND evidence_json = ?
                  AND proposals_json = ?
                """,
                (
                    EXTRACTION_SNAPSHOT_NEUTRAL_EVIDENCE_JSON,
                    EXTRACTION_SNAPSHOT_NEUTRAL_PROPOSALS_JSON,
                    uuid_to_blob(processing_run_id),
                    uuid_to_blob(analysis_id),
                    evidence_json,
                    proposals_json,
                ),
            )

            if updated.rowcount != 1:
                raise SourceProtectedSemanticIntegrityError(
                    "SourceExtraction snapshot changed during semantic cutover."
                )

        return mapping

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
    def _encode_extraction_evidence_semantics(
        *,
        extraction_id: uuid.UUID,
        evidence: tuple[
            tuple[int, uuid.UUID, bytes],
            ...,
        ],
    ) -> bytes:
        payload = {
            "entity_id": str(extraction_id),
            "fields": {
                "evidence": [
                    {
                        "quoted_hash_hex": quoted_hash.hex(),
                        "sequence_no": sequence_no,
                        "source_anchor_id": str(source_anchor_id),
                    }
                    for (
                        sequence_no,
                        source_anchor_id,
                        quoted_hash,
                    ) in evidence
                ]
            },
            "payload_version": EXTRACTION_EVIDENCE_PAYLOAD_VERSION,
            "semantic_kind": EXTRACTION_EVIDENCE_SEMANTIC_KIND,
        }

        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    @staticmethod
    def _encode_analysis_semantics(
        *,
        analysis_id: uuid.UUID,
        question: str,
    ) -> bytes:
        if not question.strip():
            raise SourceProtectedSemanticIntegrityError(
                "SourceAnalysis question is empty."
            )

        payload = {
            "entity_id": str(analysis_id),
            "fields": {
                "question": question,
            },
            "payload_version": ANALYSIS_PAYLOAD_VERSION,
            "semantic_kind": ANALYSIS_SEMANTIC_KIND,
        }

        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")

    @staticmethod
    def _encode_analysis_artifact_semantics(
        *,
        artifact_id: uuid.UUID,
        analysis_id: uuid.UUID,
        content_json: str,
        content_hash: bytes,
    ) -> bytes:
        if len(content_hash) != 32:
            raise SourceProtectedSemanticIntegrityError(
                "SourceAnalysis artifact hash is invalid."
            )

        try:
            json.loads(content_json)
        except json.JSONDecodeError as exc:
            raise SourceProtectedSemanticIntegrityError(
                "SourceAnalysis artifact content is not valid JSON."
            ) from exc

        if hashlib.sha256(content_json.encode("utf-8")).digest() != content_hash:
            raise SourceProtectedSemanticIntegrityError(
                "SourceAnalysis artifact hash disagrees with content."
            )

        payload = {
            "entity_id": str(artifact_id),
            "fields": {
                "analysis_id": str(analysis_id),
                "content_hash_hex": content_hash.hex(),
                "content_json": content_json,
            },
            "payload_version": ANALYSIS_ARTIFACT_PAYLOAD_VERSION,
            "semantic_kind": ANALYSIS_ARTIFACT_SEMANTIC_KIND,
        }

        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")


    @staticmethod
    def _encode_extraction_artifact_semantics(
        *,
        extraction_id: uuid.UUID,
        artifacts: tuple[
            tuple[uuid.UUID, str, bytes],
            ...,
        ],
    ) -> bytes:
        payload_artifacts: list[dict[str, str]] = []

        for artifact_id, content_json, content_hash in artifacts:
            if len(content_hash) != 32:
                raise SourceProtectedSemanticIntegrityError(
                    "SourceExtraction artifact hash is invalid."
                )

            try:
                json.loads(content_json)
            except json.JSONDecodeError as exc:
                raise SourceProtectedSemanticIntegrityError(
                    "SourceExtraction artifact content is not valid JSON."
                ) from exc

            if hashlib.sha256(content_json.encode("utf-8")).digest() != content_hash:
                raise SourceProtectedSemanticIntegrityError(
                    "SourceExtraction artifact hash disagrees with content."
                )

            payload_artifacts.append(
                {
                    "artifact_id": str(artifact_id),
                    "content_hash_hex": content_hash.hex(),
                    "content_json": content_json,
                }
            )

        payload = {
            "entity_id": str(extraction_id),
            "fields": {
                "artifacts": payload_artifacts,
            },
            "payload_version": EXTRACTION_ARTIFACT_PAYLOAD_VERSION,
            "semantic_kind": EXTRACTION_ARTIFACT_SEMANTIC_KIND,
        }

        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")


    @staticmethod
    def _encode_extraction_snapshot_semantics(
        *,
        analysis_id: uuid.UUID,
        snapshots: tuple[
            tuple[uuid.UUID, uuid.UUID, str, str],
            ...,
        ],
    ) -> bytes:
        payload_snapshots: list[dict[str, str]] = []

        for (
            processing_run_id,
            final_artifact_id,
            evidence_json,
            proposals_json,
        ) in snapshots:
            _validate_source_extraction_snapshot_semantic_json(
                evidence_json,
                proposals_json,
            )
            payload_snapshots.append(
                {
                    "evidence_json": evidence_json,
                    "final_artifact_id": str(final_artifact_id),
                    "processing_run_id": str(processing_run_id),
                    "proposals_json": proposals_json,
                }
            )

        payload = {
            "entity_id": str(analysis_id),
            "fields": {
                "snapshots": payload_snapshots,
            },
            "payload_version": EXTRACTION_SNAPSHOT_PAYLOAD_VERSION,
            "semantic_kind": EXTRACTION_SNAPSHOT_SEMANTIC_KIND,
        }

        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")

    @staticmethod
    def _encode_anchor_semantics(
        *,
        anchor_id: uuid.UUID,
        geometry_json: str | None,
        quoted_hash: bytes | None,
    ) -> bytes:
        payload = {
            "entity_id": str(anchor_id),
            "fields": {
                "geometry_json": geometry_json,
                "quoted_hash_hex": (
                    None if quoted_hash is None else quoted_hash.hex()
                ),
            },
            "payload_version": ANCHOR_PAYLOAD_VERSION,
            "semantic_kind": ANCHOR_SEMANTIC_KIND,
        }

        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")

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
    def _require_source(
        connection: sqlite3.Connection,
        source_id: uuid.UUID,
    ) -> None:
        row = connection.execute(
            "SELECT source_id FROM sources WHERE source_id = ?",
            (uuid_to_blob(source_id),),
        ).fetchone()

        if row is None:
            raise SourceProtectedSemanticNotFoundError(
                str(source_id)
            )

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
