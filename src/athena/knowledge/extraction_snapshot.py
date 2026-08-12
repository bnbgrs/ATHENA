"""Frozen extraction-result snapshots for reproducible acceptance after review."""

from __future__ import annotations

import json
import uuid
from typing import Any

from athena.common.ids import uuid_from_blob, uuid_to_blob
from athena.common.time import utc_now_us
from athena.knowledge.extraction_models import (
    ChatExtractionResult,
    ExtractionProposalSet,
    MergeCandidate,
    ProposalEntityType,
    ProposedClaim,
    ProposedKnowledgeUnit,
    ProposedRelation,
)
from athena.knowledge.models import ClaimKind, EpistemicStatus, KnowledgeKind
from athena.model.domain import ModelInfo
from athena.model.provenance import ModelRunRepository
from athena.storage.database import SQLiteDatabase


class ExtractionSnapshotNotFoundError(LookupError):
    """Raised when an extraction run has no frozen proposal snapshot."""


class ExtractionSnapshotRepository:
    """Persist and reload the exact validated proposal set for one ProcessingRun."""

    def __init__(self, database: SQLiteDatabase, runs: ModelRunRepository) -> None:
        self.database = database
        self.runs = runs

    def save(self, result: ChatExtractionResult) -> None:
        model_json = _canonical_json(
            {
                "provider": result.model.provider,
                "backend_model_id": result.model.backend_model_id,
                "display_name": result.model.display_name,
                "model_type": result.model.model_type,
                "context_capacity": result.model.context_capacity,
                "quantization": result.model.quantization,
                "loaded": result.model.loaded,
                "vision": result.model.vision,
                "trained_for_tool_use": result.model.trained_for_tool_use,
            }
        )
        proposals_json = _canonical_json(_proposal_payload(result.proposals))
        with self.database.write_transaction() as connection:
            connection.execute(
                """
                INSERT INTO extraction_result_snapshots (
                    processing_run_id, chat_id, model_json, proposals_json, created_at_us
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    uuid_to_blob(result.processing_run.processing_run_id),
                    uuid_to_blob(result.chat_id),
                    model_json,
                    proposals_json,
                    utc_now_us(),
                ),
            )

    def load(self, processing_run_id: uuid.UUID) -> ChatExtractionResult:
        row = self.database.connection.execute(
            """
            SELECT chat_id, model_json, proposals_json
            FROM extraction_result_snapshots
            WHERE processing_run_id = ?
            """,
            (uuid_to_blob(processing_run_id),),
        ).fetchone()
        if row is None:
            raise ExtractionSnapshotNotFoundError(
                f"No frozen extraction snapshot for ProcessingRun {processing_run_id}."
            )
        run = self.runs.load_run(processing_run_id)
        if run.status != "succeeded":
            raise ExtractionSnapshotNotFoundError(
                "Only succeeded extraction runs can be accepted."
            )
        if run.model_signature_id is None:
            raise ExtractionSnapshotNotFoundError(
                "Frozen extraction run lacks a ModelSignature."
            )
        signature = self.runs.load_signature(run.model_signature_id)
        model_data = json.loads(str(row["model_json"]))
        proposals_data = json.loads(str(row["proposals_json"]))
        return ChatExtractionResult(
            chat_id=uuid_from_blob(bytes(row["chat_id"])),
            model=ModelInfo(
                provider=str(model_data["provider"]),
                backend_model_id=str(model_data["backend_model_id"]),
                display_name=str(model_data["display_name"]),
                model_type=str(model_data["model_type"]),
                context_capacity=_optional_int(model_data["context_capacity"]),
                quantization=_optional_str(model_data["quantization"]),
                loaded=bool(model_data["loaded"]),
                vision=_optional_bool(model_data["vision"]),
                trained_for_tool_use=_optional_bool(model_data["trained_for_tool_use"]),
            ),
            model_signature=signature,
            processing_run=run,
            proposals=_proposals_from_payload(proposals_data),
        )


def _proposal_payload(proposals: ExtractionProposalSet) -> dict[str, Any]:
    return {
        "knowledge_units": [
            {
                "source_sequence_no": item.source_sequence_no,
                "source_quote": item.source_quote,
                "knowledge_kind": item.knowledge_kind.value,
                "title": item.title,
                "body": item.body,
                "epistemic_status": item.epistemic_status.value,
                "confidence": item.confidence,
            }
            for item in proposals.knowledge_units
        ],
        "claims": [
            {
                "source_sequence_no": item.source_sequence_no,
                "source_quote": item.source_quote,
                "claim_kind": item.claim_kind.value,
                "statement": item.statement,
                "epistemic_status": item.epistemic_status.value,
                "confidence": item.confidence,
            }
            for item in proposals.claims
        ],
        "relations": [
            {
                "left_type": item.left_type.value,
                "left_index": item.left_index,
                "relation_type": item.relation_type,
                "right_type": item.right_type.value,
                "right_index": item.right_index,
                "confidence": item.confidence,
            }
            for item in proposals.relations
        ],
        "merge_candidates": [
            {
                "proposal_type": item.proposal_type.value,
                "proposal_index": item.proposal_index,
                "reason": item.reason,
                "confidence": item.confidence,
            }
            for item in proposals.merge_candidates
        ],
    }


def _proposals_from_payload(value: object) -> ExtractionProposalSet:
    if not isinstance(value, dict):
        raise ExtractionSnapshotNotFoundError("Frozen proposal snapshot is invalid.")
    return ExtractionProposalSet(
        knowledge_units=tuple(
            ProposedKnowledgeUnit(
                source_sequence_no=_required_int(item["source_sequence_no"]),
                source_quote=str(item["source_quote"]),
                knowledge_kind=KnowledgeKind(str(item["knowledge_kind"])),
                title=None if item["title"] is None else str(item["title"]),
                body=str(item["body"]),
                epistemic_status=EpistemicStatus(str(item["epistemic_status"])),
                confidence=_required_float(item["confidence"]),
            )
            for item in _dict_list(value.get("knowledge_units"))
        ),
        claims=tuple(
            ProposedClaim(
                source_sequence_no=_required_int(item["source_sequence_no"]),
                source_quote=str(item["source_quote"]),
                claim_kind=ClaimKind(str(item["claim_kind"])),
                statement=str(item["statement"]),
                epistemic_status=EpistemicStatus(str(item["epistemic_status"])),
                confidence=_required_float(item["confidence"]),
            )
            for item in _dict_list(value.get("claims"))
        ),
        relations=tuple(
            ProposedRelation(
                left_type=ProposalEntityType(str(item["left_type"])),
                left_index=_required_int(item["left_index"]),
                relation_type=str(item["relation_type"]),
                right_type=ProposalEntityType(str(item["right_type"])),
                right_index=_required_int(item["right_index"]),
                confidence=_required_float(item["confidence"]),
            )
            for item in _dict_list(value.get("relations"))
        ),
        merge_candidates=tuple(
            MergeCandidate(
                proposal_type=ProposalEntityType(str(item["proposal_type"])),
                proposal_index=_required_int(item["proposal_index"]),
                reason=str(item["reason"]),
                confidence=_required_float(item["confidence"]),
            )
            for item in _dict_list(value.get("merge_candidates"))
        ),
    )


def _dict_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ExtractionSnapshotNotFoundError("Frozen proposal snapshot is invalid.")
    return [dict(item) for item in value]


def _canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _required_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ExtractionSnapshotNotFoundError(
            "Frozen proposal snapshot contains an invalid integer."
        )
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ExtractionSnapshotNotFoundError(
            "Frozen proposal snapshot contains an invalid integer."
        ) from exc


def _required_float(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ExtractionSnapshotNotFoundError(
            "Frozen proposal snapshot contains an invalid number."
        )
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ExtractionSnapshotNotFoundError(
            "Frozen proposal snapshot contains an invalid number."
        ) from exc


def _optional_int(value: object) -> int | None:
    return None if value is None else _required_int(value)


def _optional_str(value: object) -> str | None:
    return None if value is None else str(value)


def _optional_bool(value: object) -> bool | None:
    return None if value is None else bool(value)
