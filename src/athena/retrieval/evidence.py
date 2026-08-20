"""Typed evidence roles for memory-augmented chat retrieval."""

from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import dataclass
from enum import Enum

from athena.common.ids import uuid_to_blob
from athena.knowledge.models import EpistemicStatus
from athena.retrieval.hybrid import HybridSearchResult
from athena.retrieval.search import SearchEntityType
from athena.storage.database import SQLiteDatabase

MEMORY_EVIDENCE_POLICY_ID = "typed-provenance-v1"


class EvidenceClass(str, Enum):
    """Epistemic role of one retrieved item in a grounded answer."""

    CANONICAL = "canonical"
    USER_STATEMENT = "user_statement"
    CONVERSATION_RECORD = "conversation_record"
    SOURCE = "source"
    RESEARCH = "research"
    NEWS = "news"


class MemoryEvidencePolicyError(RuntimeError):
    """Raised when evidence cannot be classified without guessing."""


@dataclass(frozen=True, slots=True)
class MemoryEvidenceClassification:
    """Typed provenance for one retrieved hybrid result."""

    entity_id: uuid.UUID
    revision_id: uuid.UUID
    entity_type: SearchEntityType
    evidence_class: EvidenceClass
    message_type: str | None
    epistemic_status: EpistemicStatus | None = None


@dataclass(frozen=True, slots=True)
class MemoryEvidenceSelection:
    """Retrieved results plus deterministic epistemic-role classification."""

    policy_id: str
    results: tuple[HybridSearchResult, ...]
    classifications: tuple[MemoryEvidenceClassification, ...]

    def classification_for(
        self,
        *,
        entity_type: SearchEntityType,
        entity_id: uuid.UUID,
        revision_id: uuid.UUID,
    ) -> MemoryEvidenceClassification:
        for item in self.classifications:
            if (
                item.entity_type is entity_type
                and item.entity_id == entity_id
                and item.revision_id == revision_id
            ):
                return item
        raise MemoryEvidencePolicyError(
            "Context item has no evidence classification: "
            f"{entity_type.value}:{entity_id}:{revision_id}"
        )

    @property
    def counts(self) -> tuple[tuple[EvidenceClass, int], ...]:
        counts = Counter(item.evidence_class for item in self.classifications)
        return tuple(sorted(counts.items(), key=lambda item: item[0].value))


class MemoryEvidencePolicy:
    """Classify retrieval without converting raw conversation into knowledge.

    Knowledge and Claims are canonical semantic evidence. A raw user message is
    direct evidence of what the user said or self-reported, but it is not
    independent verification of an arbitrary world fact. Other chat messages
    remain conversation records: useful for continuity and recap, but not an
    independent factual authority.
    """

    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def classify(
        self,
        results: tuple[HybridSearchResult, ...],
    ) -> MemoryEvidenceSelection:
        classifications = tuple(self._classify_one(result) for result in results)
        return MemoryEvidenceSelection(
            policy_id=MEMORY_EVIDENCE_POLICY_ID,
            results=results,
            classifications=classifications,
        )

    def _canonical_epistemic_status(
        self,
        result: HybridSearchResult,
    ) -> EpistemicStatus:
        if result.entity_type is SearchEntityType.KNOWLEDGE:
            row = self.database.connection.execute(
                """
                SELECT kr.epistemic_status
                FROM knowledge_units AS k
                JOIN entity_registry AS e
                  ON e.entity_id = k.knowledge_id
                JOIN entity_heads AS h
                  ON h.entity_id = k.knowledge_id
                JOIN knowledge_unit_revisions AS kr
                  ON kr.revision_id = h.current_revision_id
                WHERE k.knowledge_id = ?
                  AND h.current_revision_id = ?
                  AND e.lifecycle_state = 'active'
                """,
                (
                    uuid_to_blob(result.entity_id),
                    uuid_to_blob(result.revision_id),
                ),
            ).fetchone()
        elif result.entity_type is SearchEntityType.CLAIM:
            row = self.database.connection.execute(
                """
                SELECT cr.epistemic_status
                FROM claims AS c
                JOIN entity_registry AS e
                  ON e.entity_id = c.claim_id
                JOIN entity_heads AS h
                  ON h.entity_id = c.claim_id
                JOIN claim_revisions AS cr
                  ON cr.revision_id = h.current_revision_id
                WHERE c.claim_id = ?
                  AND h.current_revision_id = ?
                  AND e.lifecycle_state = 'active'
                """,
                (
                    uuid_to_blob(result.entity_id),
                    uuid_to_blob(result.revision_id),
                ),
            ).fetchone()
        else:
            raise MemoryEvidencePolicyError(
                "Canonical epistemic status requires Knowledge or Claim."
            )

        if row is None:
            raise MemoryEvidencePolicyError(
                "Retrieved canonical evidence is not the active current revision: "
                f"{result.entity_type.value}:{result.entity_id}:"
                f"{result.revision_id}"
            )

        try:
            return EpistemicStatus(str(row["epistemic_status"]))
        except ValueError as exc:
            raise MemoryEvidencePolicyError(
                "Retrieved canonical evidence has an unsupported epistemic status."
            ) from exc

    def _classify_one(
        self,
        result: HybridSearchResult,
    ) -> MemoryEvidenceClassification:
        if result.entity_type in {
            SearchEntityType.KNOWLEDGE,
            SearchEntityType.CLAIM,
        }:
            return MemoryEvidenceClassification(
                entity_id=result.entity_id,
                revision_id=result.revision_id,
                entity_type=result.entity_type,
                evidence_class=EvidenceClass.CANONICAL,
                message_type=None,
                epistemic_status=self._canonical_epistemic_status(
                    result
                ),
            )

        if result.entity_type is not SearchEntityType.CHAT_MESSAGE:
            raise MemoryEvidencePolicyError(
                f"Unsupported memory evidence entity type: {result.entity_type.value}"
            )

        row = self.database.connection.execute(
            """
            SELECT message_type
            FROM chat_messages
            WHERE message_id = ?
            """,
            (uuid_to_blob(result.entity_id),),
        ).fetchone()
        if row is None:
            raise MemoryEvidencePolicyError(
                "Retrieved chat message is missing from canonical chat storage: "
                f"{result.entity_id}"
            )

        message_type = str(row["message_type"])
        if message_type not in {"user", "assistant", "tool_result", "system_event"}:
            raise MemoryEvidencePolicyError(
                "Retrieved chat message has an unsupported message type."
            )

        evidence_class = (
            EvidenceClass.USER_STATEMENT
            if message_type == "user"
            else EvidenceClass.CONVERSATION_RECORD
        )
        return MemoryEvidenceClassification(
            entity_id=result.entity_id,
            revision_id=result.revision_id,
            entity_type=result.entity_type,
            evidence_class=evidence_class,
            message_type=message_type,
            epistemic_status=None,
        )
