"""Structured, snapshot-pinned model context packages."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any, Literal, Mapping

from athena.chat.models import ChatMessage, MessageType
from athena.chat.provenance import (
    strip_model_facing_assistant_trace,
    strip_turn_local_grounding_markers,
)
from athena.common.ids import new_uuid7, uuid_to_blob
from athena.model.domain import ModelChatMessage
from athena.model.provenance import ModelSignature
from athena.retrieval.context import ContextBundle
from athena.storage.database import SQLiteDatabase

_CONTEXT_PACKAGE_VERSION = 1
_CURRENT_USER_REF_ID = "CURRENT-USER"

ContextRole = Literal["system", "user", "assistant"]


class ContextPackageError(ValueError):
    """Raised when a model-facing ContextPackage is internally inconsistent."""


class ContextSnapshotDriftError(RuntimeError):
    """Raised when canonical state changes across a pinned context build."""


@dataclass(frozen=True, slots=True)
class ContextModelSignature:
    model_signature_id: uuid.UUID
    provider: str
    model_identifier: str
    quantization: str | None
    generation_parameters_json: str
    context_configuration_json: str | None
    signature_hash_hex: str


@dataclass(frozen=True, slots=True)
class ContextPackageBudget:
    effective_context_limit: int
    context_budget: int
    output_reserve: int
    safety_margin: int


@dataclass(frozen=True, slots=True)
class ContextTokenEstimates:
    conversation_tokens: int
    current_user_tokens: int
    system_tokens: int
    context_tokens: int
    estimated_input_tokens: int
    estimated_total_tokens: int


@dataclass(frozen=True, slots=True)
class ContextIncludedRef:
    ref_id: str
    entity_type: str
    entity_id: uuid.UUID
    revision_id: uuid.UUID | None


@dataclass(frozen=True, slots=True)
class ExcludedCandidateSummary:
    retrieval_candidate_count: int
    retrieval_included_count: int
    retrieval_excluded_count: int
    memory_candidate_count: int
    memory_included_count: int
    memory_excluded_count: int
    conversation_candidate_count: int
    conversation_included_count: int
    conversation_excluded_count: int


@dataclass(frozen=True, slots=True)
class ContextSection:
    name: str
    role: ContextRole
    content: str
    included_ref_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ContextPackage:
    """The complete model-facing input contract for one Primary Model call."""

    request_id: uuid.UUID
    model_signature: ContextModelSignature
    budget: ContextPackageBudget
    sections: tuple[ContextSection, ...]
    included_refs: tuple[ContextIncludedRef, ...]
    excluded_candidate_summary: ExcludedCandidateSummary
    token_estimates: ContextTokenEstimates
    snapshot_commit_seq: int
    structured_schema_id: str | None = None
    structured_schema_json: str | None = None

    def model_messages(self) -> tuple[ModelChatMessage, ...]:
        return tuple(
            ModelChatMessage(role=section.role, content=section.content)
            for section in self.sections
        )

    def current_user_ref(self) -> ContextIncludedRef:
        matches = tuple(
            item for item in self.included_refs if item.ref_id == _CURRENT_USER_REF_ID
        )
        if len(matches) != 1:
            raise ContextPackageError(
                "ContextPackage must contain exactly one CURRENT-USER reference."
            )
        return matches[0]

    def generation_controls(self) -> tuple[int | None, str | None]:
        try:
            payload = json.loads(self.model_signature.generation_parameters_json)
        except json.JSONDecodeError as exc:
            raise ContextPackageError(
                "ContextPackage ModelSignature has invalid generation JSON."
            ) from exc
        if not isinstance(payload, dict):
            raise ContextPackageError(
                "ContextPackage generation parameters must be a JSON object."
            )

        max_output_tokens = payload.get("max_output_tokens")
        if max_output_tokens is not None and (
            isinstance(max_output_tokens, bool)
            or not isinstance(max_output_tokens, int)
            or max_output_tokens < 1
        ):
            raise ContextPackageError(
                "ContextPackage max_output_tokens must be a positive integer."
            )

        reasoning_mode = payload.get("reasoning_mode")
        if reasoning_mode not in {None, "off"}:
            raise ContextPackageError(
                "ContextPackage reasoning_mode must be absent or 'off'."
            )
        return max_output_tokens, reasoning_mode

    def generation_temperature(self) -> float | None:
        """Return the optional pinned sampling temperature for this package."""
        try:
            payload = json.loads(self.model_signature.generation_parameters_json)
        except json.JSONDecodeError as exc:
            raise ContextPackageError(
                "ContextPackage ModelSignature has invalid generation JSON."
            ) from exc
        if not isinstance(payload, dict):
            raise ContextPackageError(
                "ContextPackage generation parameters must be a JSON object."
            )

        value = payload.get("temperature")
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ContextPackageError(
                "ContextPackage temperature must be numeric when provided."
            )
        temperature = float(value)
        if not 0.0 <= temperature <= 2.0:
            raise ContextPackageError(
                "ContextPackage temperature must be between 0.0 and 2.0."
            )
        return temperature

    def structured_schema(self) -> dict[str, Any] | None:
        if self.structured_schema_id is None and self.structured_schema_json is None:
            return None
        if self.structured_schema_id is None or self.structured_schema_json is None:
            raise ContextPackageError(
                "Structured ContextPackage requires both schema ID and schema JSON."
            )
        try:
            payload = json.loads(self.structured_schema_json)
        except json.JSONDecodeError as exc:
            raise ContextPackageError(
                "ContextPackage structured schema JSON is invalid."
            ) from exc
        if not isinstance(payload, dict):
            raise ContextPackageError(
                "ContextPackage structured schema must be a JSON object."
            )
        return payload

    def run_snapshot(self) -> dict[str, Any]:
        """Persist reconstructible package metadata without duplicating plaintext."""
        snapshot: dict[str, Any] = {
            "context_package_version": _CONTEXT_PACKAGE_VERSION,
            "request_id": str(self.request_id),
            "model_signature": {
                "model_signature_id": str(self.model_signature.model_signature_id),
                "provider": self.model_signature.provider,
                "model_identifier": self.model_signature.model_identifier,
                "quantization": self.model_signature.quantization,
                "generation_parameters_json": (
                    self.model_signature.generation_parameters_json
                ),
                "context_configuration_json": (
                    self.model_signature.context_configuration_json
                ),
                "signature_hash_hex": self.model_signature.signature_hash_hex,
            },
            "budget": {
                "effective_context_limit": self.budget.effective_context_limit,
                "context_budget": self.budget.context_budget,
                "output_reserve": self.budget.output_reserve,
                "safety_margin": self.budget.safety_margin,
            },
            "sections": [
                {
                    "name": section.name,
                    "role": section.role,
                    "included_ref_ids": list(section.included_ref_ids),
                    "content_sha256": hashlib.sha256(
                        section.content.encode("utf-8")
                    ).hexdigest(),
                }
                for section in self.sections
            ],
            "included_refs": [
                {
                    "ref_id": item.ref_id,
                    "entity_type": item.entity_type,
                    "entity_id": str(item.entity_id),
                    "revision_id": (
                        str(item.revision_id)
                        if item.revision_id is not None
                        else None
                    ),
                }
                for item in self.included_refs
            ],
            "excluded_candidate_summary": {
                "retrieval_candidate_count": (
                    self.excluded_candidate_summary.retrieval_candidate_count
                ),
                "retrieval_included_count": (
                    self.excluded_candidate_summary.retrieval_included_count
                ),
                "retrieval_excluded_count": (
                    self.excluded_candidate_summary.retrieval_excluded_count
                ),
                "memory_candidate_count": (
                    self.excluded_candidate_summary.memory_candidate_count
                ),
                "memory_included_count": (
                    self.excluded_candidate_summary.memory_included_count
                ),
                "memory_excluded_count": (
                    self.excluded_candidate_summary.memory_excluded_count
                ),
                "conversation_candidate_count": (
                    self.excluded_candidate_summary.conversation_candidate_count
                ),
                "conversation_included_count": (
                    self.excluded_candidate_summary.conversation_included_count
                ),
                "conversation_excluded_count": (
                    self.excluded_candidate_summary.conversation_excluded_count
                ),
            },
            "token_estimates": {
                "conversation_tokens": self.token_estimates.conversation_tokens,
                "current_user_tokens": self.token_estimates.current_user_tokens,
                "system_tokens": self.token_estimates.system_tokens,
                "context_tokens": self.token_estimates.context_tokens,
                "estimated_input_tokens": self.token_estimates.estimated_input_tokens,
                "estimated_total_tokens": self.token_estimates.estimated_total_tokens,
            },
            "snapshot_commit_seq": self.snapshot_commit_seq,
        }
        if self.structured_schema_id is not None:
            assert self.structured_schema_json is not None
            snapshot["structured_output"] = {
                "schema_id": self.structured_schema_id,
                "schema_sha256": hashlib.sha256(
                    self.structured_schema_json.encode("utf-8")
                ).hexdigest(),
            }
        return snapshot


class ContextPackageService:
    """Build packages and guard the canonical commit-sequence snapshot."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def current_commit_seq(self) -> int:
        row = self.database.connection.execute(
            "SELECT COALESCE(MAX(commit_seq), 0) AS commit_seq FROM commit_records"
        ).fetchone()
        if row is None:
            return 0
        return int(row["commit_seq"])

    def assert_snapshot_current(self, expected_commit_seq: int, *, phase: str) -> None:
        current = self.current_commit_seq()
        if current != expected_commit_seq:
            raise ContextSnapshotDriftError(
                "Canonical state changed during ContextPackage construction "
                f"({phase}): expected commit_seq={expected_commit_seq}, "
                f"current={current}."
            )

    def assert_user_commit_follows(
        self,
        previous_commit_seq: int,
        user_message: ChatMessage,
    ) -> int:
        if user_message.message_type is not MessageType.USER:
            raise ContextPackageError(
                "ContextPackage current message must be a persisted user message."
            )
        row = self.database.connection.execute(
            """
            SELECT c.commit_seq
            FROM revisions AS r
            JOIN commit_records AS c ON c.commit_id = r.commit_id
            WHERE r.revision_id = ?
            """,
            (uuid_to_blob(user_message.revision_id),),
        ).fetchone()
        if row is None:
            raise ContextPackageError(
                "Persisted current user message has no durable commit sequence."
            )
        user_commit_seq = int(row["commit_seq"])
        expected_user_commit_seq = previous_commit_seq + 1
        current = self.current_commit_seq()
        if user_commit_seq != expected_user_commit_seq or current != user_commit_seq:
            raise ContextSnapshotDriftError(
                "Canonical state changed between retrieval and current-user "
                "persistence: expected the user message to be the only new commit "
                f"({expected_user_commit_seq}), user_commit={user_commit_seq}, "
                f"current={current}."
            )
        return user_commit_seq

    @staticmethod
    def build_from_sections(
        *,
        model_signature: ModelSignature,
        budget: ContextPackageBudget,
        sections: tuple[ContextSection, ...],
        included_refs: tuple[ContextIncludedRef, ...],
        excluded_candidate_summary: ExcludedCandidateSummary,
        token_estimates: ContextTokenEstimates,
        snapshot_commit_seq: int,
        structured_schema_id: str | None = None,
        structured_schema: Mapping[str, Any] | None = None,
    ) -> ContextPackage:
        """Build a generic package for chat or structured Primary Model calls."""
        if snapshot_commit_seq < 0:
            raise ContextPackageError("snapshot_commit_seq must not be negative.")
        if not sections:
            raise ContextPackageError("ContextPackage must contain at least one section.")
        if any(not section.content.strip() for section in sections):
            raise ContextPackageError("ContextPackage sections must not be blank.")
        if token_estimates.estimated_total_tokens > budget.effective_context_limit:
            raise ContextPackageError(
                "ContextPackage token estimate exceeds the effective context limit."
            )
        if budget.output_reserve < 1 or budget.safety_margin < 0:
            raise ContextPackageError("ContextPackage budget controls are invalid.")

        ref_ids = tuple(item.ref_id for item in included_refs)
        if len(set(ref_ids)) != len(ref_ids):
            raise ContextPackageError("ContextPackage reference IDs must be unique.")
        known_refs = set(ref_ids)
        for section in sections:
            if any(ref_id not in known_refs for ref_id in section.included_ref_ids):
                raise ContextPackageError(
                    "ContextPackage section references an unknown included ref."
                )

        counters = (
            (
                excluded_candidate_summary.retrieval_candidate_count,
                excluded_candidate_summary.retrieval_included_count,
                excluded_candidate_summary.retrieval_excluded_count,
            ),
            (
                excluded_candidate_summary.memory_candidate_count,
                excluded_candidate_summary.memory_included_count,
                excluded_candidate_summary.memory_excluded_count,
            ),
            (
                excluded_candidate_summary.conversation_candidate_count,
                excluded_candidate_summary.conversation_included_count,
                excluded_candidate_summary.conversation_excluded_count,
            ),
        )
        for candidate_count, included_count, excluded_count in counters:
            if min(candidate_count, included_count, excluded_count) < 0:
                raise ContextPackageError(
                    "ContextPackage candidate counts must not be negative."
                )
            if included_count + excluded_count != candidate_count:
                raise ContextPackageError(
                    "ContextPackage candidate counts are internally inconsistent."
                )

        if (structured_schema_id is None) != (structured_schema is None):
            raise ContextPackageError(
                "Structured ContextPackage requires schema ID and schema together."
            )
        schema_json: str | None = None
        normalized_schema_id: str | None = None
        if structured_schema is not None:
            assert structured_schema_id is not None
            normalized_schema_id = structured_schema_id.strip()
            if not normalized_schema_id:
                raise ContextPackageError(
                    "Structured ContextPackage schema ID must not be blank."
                )
            schema_json = json.dumps(
                dict(structured_schema),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )

        signature = ContextModelSignature(
            model_signature_id=model_signature.model_signature_id,
            provider=model_signature.provider,
            model_identifier=model_signature.model_identifier,
            quantization=model_signature.quantization,
            generation_parameters_json=model_signature.generation_parameters_json,
            context_configuration_json=model_signature.context_configuration_json,
            signature_hash_hex=model_signature.signature_hash.hex(),
        )
        return ContextPackage(
            request_id=new_uuid7(),
            model_signature=signature,
            budget=budget,
            sections=sections,
            included_refs=included_refs,
            excluded_candidate_summary=excluded_candidate_summary,
            token_estimates=token_estimates,
            snapshot_commit_seq=snapshot_commit_seq,
            structured_schema_id=normalized_schema_id,
            structured_schema_json=schema_json,
        )

    @staticmethod
    def build(
        *,
        model_signature: ModelSignature,
        context: ContextBundle,
        system_text: str,
        prior_messages: tuple[ChatMessage, ...],
        current_user_message: ChatMessage,
        budget: ContextPackageBudget,
        token_estimates: ContextTokenEstimates,
        snapshot_commit_seq: int,
        retrieval_candidate_count: int,
        memory_candidate_count: int,
        conversation_candidate_count: int | None = None,
    ) -> ContextPackage:
        if snapshot_commit_seq < 0:
            raise ContextPackageError("snapshot_commit_seq must not be negative.")
        if current_user_message.message_type is not MessageType.USER:
            raise ContextPackageError(
                "ContextPackage current message must have user message type."
            )
        if current_user_message.content is None:
            raise ContextPackageError(
                "ContextPackage current user message content is unavailable."
            )
        if not system_text.strip():
            raise ContextPackageError("ContextPackage system section must not be blank.")
        if retrieval_candidate_count < len(context.items):
            raise ContextPackageError(
                "Retrieval candidate count cannot be smaller than included items."
            )
        if memory_candidate_count < len(context.memory_items):
            raise ContextPackageError(
                "Memory candidate count cannot be smaller than included preferences."
            )
        if conversation_candidate_count is None:
            conversation_candidate_count = len(prior_messages)
        if conversation_candidate_count < len(prior_messages):
            raise ContextPackageError(
                "Conversation candidate count cannot be smaller than included messages."
            )
        if token_estimates.estimated_total_tokens > budget.effective_context_limit:
            raise ContextPackageError(
                "ContextPackage token estimate exceeds the effective context limit."
            )

        included_refs: list[ContextIncludedRef] = []
        system_ref_ids: list[str] = []

        for memory in context.memory_items:
            ref = ContextIncludedRef(
                ref_id=memory.context_id,
                entity_type="personal_memory",
                entity_id=memory.memory_id,
                revision_id=memory.revision_id,
            )
            included_refs.append(ref)
            system_ref_ids.append(ref.ref_id)

        for item in context.items:
            ref = ContextIncludedRef(
                ref_id=item.context_id,
                entity_type=item.entity_type.value,
                entity_id=item.entity_id,
                revision_id=item.revision_id,
            )
            included_refs.append(ref)
            system_ref_ids.append(ref.ref_id)

        sections: list[ContextSection] = [
            ContextSection(
                name="retrieved_context",
                role="system",
                content=system_text,
                included_ref_ids=tuple(system_ref_ids),
            )
        ]

        for index, message in enumerate(prior_messages, start=1):
            message_content, role = _model_message_payload(message)
            ref_id = f"CHAT-HIST-{index:03d}"
            included_refs.append(
                ContextIncludedRef(
                    ref_id=ref_id,
                    entity_type="chat_message",
                    entity_id=message.message_id,
                    revision_id=message.revision_id,
                )
            )
            sections.append(
                ContextSection(
                    name="conversation",
                    role=role,
                    content=message_content,
                    included_ref_ids=(ref_id,),
                )
            )

        included_refs.append(
            ContextIncludedRef(
                ref_id=_CURRENT_USER_REF_ID,
                entity_type="chat_message",
                entity_id=current_user_message.message_id,
                revision_id=current_user_message.revision_id,
            )
        )
        sections.append(
            ContextSection(
                name="current_user",
                role="user",
                content=current_user_message.content,
                included_ref_ids=(_CURRENT_USER_REF_ID,),
            )
        )

        signature = ContextModelSignature(
            model_signature_id=model_signature.model_signature_id,
            provider=model_signature.provider,
            model_identifier=model_signature.model_identifier,
            quantization=model_signature.quantization,
            generation_parameters_json=model_signature.generation_parameters_json,
            context_configuration_json=model_signature.context_configuration_json,
            signature_hash_hex=model_signature.signature_hash.hex(),
        )
        excluded = ExcludedCandidateSummary(
            retrieval_candidate_count=retrieval_candidate_count,
            retrieval_included_count=len(context.items),
            retrieval_excluded_count=retrieval_candidate_count - len(context.items),
            memory_candidate_count=memory_candidate_count,
            memory_included_count=len(context.memory_items),
            memory_excluded_count=memory_candidate_count - len(context.memory_items),
            conversation_candidate_count=conversation_candidate_count,
            conversation_included_count=len(prior_messages),
            conversation_excluded_count=(
                conversation_candidate_count - len(prior_messages)
            ),
        )
        return ContextPackage(
            request_id=new_uuid7(),
            model_signature=signature,
            budget=budget,
            sections=tuple(sections),
            included_refs=tuple(included_refs),
            excluded_candidate_summary=excluded,
            token_estimates=token_estimates,
            snapshot_commit_seq=snapshot_commit_seq,
        )


def _model_message_payload(message: ChatMessage) -> tuple[str, ContextRole]:
    if message.content is None:
        raise ContextPackageError(
            "Protected or unavailable chat content cannot enter this ContextPackage."
        )
    if message.message_type is MessageType.USER:
        return strip_turn_local_grounding_markers(message.content), "user"
    if message.message_type is MessageType.ASSISTANT:
        return strip_model_facing_assistant_trace(message.content), "assistant"
    raise ContextPackageError(
        f"Unsupported conversation message type {message.message_type.value!r}."
    )
