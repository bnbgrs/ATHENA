"""Durable, context-budgeted hierarchical extraction for completed source analyses."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations
from typing import Any, cast

from athena.jobs.lease_guard import blocking_operation_lease_seconds
from athena.jobs.models import JobPriority, JobRecord
from athena.jobs.service import DurableJobService
from athena.knowledge.extraction_models import (
    ClaimPairRelationship,
    ExtractionProposalSet,
    ExtractionValidationError,
    ProposalEntityType,
    ProposedClaim,
    ProposedKnowledgeUnit,
    ProposedRelation,
    extraction_json_schema,
    parse_extraction_proposals,
)
from athena.knowledge.source_extraction import (
    HIERARCHICAL_PIPELINE_VERSION,
    HIERARCHICAL_PROMPT_TEMPLATE_ID,
    HIERARCHICAL_PROMPT_TEMPLATE_VERSION,
    SOURCE_EXTRACTION_SCHEMA_ID,
    TOKEN_ESTIMATOR,
    SourceAnalysisExtractionResult,
    SourceAnalysisKnowledgeExtractionService,
    SourceExtractionEvidence,
    SourceExtractionSnapshotRepository,
    _estimate_request_tokens,
    _proposal_payload,
    _proposals_from_payload,
)
from athena.knowledge.source_hierarchical_models import (
    SourceExtractionInputKind,
    SourceExtractionStage,
    SourceExtractionWorkState,
    SourceHierarchicalExtractionArtifact,
    SourceHierarchicalExtractionRecord,
    SourceHierarchicalExtractionWorkItem,
)
from athena.knowledge.source_hierarchical_repository import (
    SourceHierarchicalExtractionRepository,
)
from athena.model.domain import ModelChatMessage, ModelInfo
from athena.model.ports import (
    CONTROLLED_STRUCTURED_CONTRACT_VERSION,
    ControlledStructuredModelProvider,
    controlled_structured_contract_prefix,
)
from athena.model.provenance import ModelRunRepository, ModelSignature
from athena.retrieval.context_package import (
    ContextIncludedRef,
    ContextPackage,
    ContextPackageBudget,
    ContextPackageService,
    ContextRole,
    ContextSection,
    ContextTokenEstimates,
    ExcludedCandidateSummary,
)
from athena.source.analysis_models import (
    AnalysisStage,
    SourceAnalysisArtifact,
    SourceAnalysisRecord,
)
from athena.source.analysis_repository import SourceAnalysisRepository
from athena.source.anchor_service import SourceAnchorService

MERGE_SCHEMA_ID = "athena_source_extraction_semantic_dedup_v3"
PAIR_AUDIT_SCHEMA_ID = "athena_source_extraction_pair_batch_audit_v1"
DEFAULT_MAX_HIERARCHY_DEPTH = 16
HIERARCHICAL_REASONING_MODE = "off"
HIERARCHICAL_TEMPERATURE = 0.0
HIERARCHICAL_TOP_P = 0.95
HIERARCHICAL_TOP_K = 40
HIERARCHICAL_MIN_P = 0.05
HIERARCHICAL_REPEAT_PENALTY = 1.1
HIERARCHICAL_STORE = False
HIERARCHICAL_STRUCTURED_VALIDATION = "athena_stage_parser_v1"
HIERARCHICAL_PROVIDER_INSTANCE_POLICY = "initial_context_then_runtime_instance_reuse_v1"


class SourceHierarchicalExtractionConfigurationError(ValueError):
    """Raised when a hierarchical extraction cannot be pinned safely."""


class SourceHierarchicalExtractionInputTooLargeError(RuntimeError):
    """Raised before a provider call when a durable extraction unit exceeds budget."""


class SourceHierarchicalExtractionOutputError(RuntimeError):
    """Raised when model output violates the hierarchical extraction contract."""


class SourceHierarchicalExtractionModelDriftError(RuntimeError):
    """Raised when the active Primary Model no longer matches the pinned signature."""


@dataclass(frozen=True, slots=True)
class HierarchicalExtractionPinnedConfiguration:
    model: ModelInfo
    model_signature_id: uuid.UUID
    model_signature_hash: bytes
    effective_context_limit: int
    output_reserve: int
    safety_margin: int
    token_estimator: str
    max_hierarchy_depth: int
    provider_transport: str
    reasoning_mode: str
    temperature: float
    top_p: float
    top_k: int
    min_p: float
    repeat_penalty: float
    store: bool
    structured_validation: str
    provider_instance_policy: str

    @property
    def input_budget(self) -> int:
        return self.effective_context_limit - self.output_reserve - self.safety_margin


@dataclass(frozen=True, slots=True)
class PreparedHierarchicalExtractionCall:
    work_item: SourceHierarchicalExtractionWorkItem
    messages: tuple[ModelChatMessage, ...]
    schema_id: str
    schema: Mapping[str, Any]
    estimated_input_tokens: int
    input_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MergeDecision:
    proposal_type: ProposalEntityType
    keep_index: int
    duplicate_indexes: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class PairAuditAssessment:
    pair_no: int
    left_claim_index: int
    right_claim_index: int
    relationship: ClaimPairRelationship
    confidence: float
    reason: str


class SourceHierarchicalExtractionService:
    """Own pinning, planning, semantic calls, and resumable final snapshot assembly."""

    def __init__(
        self,
        *,
        jobs: DurableJobService,
        repository: SourceHierarchicalExtractionRepository,
        analyses: SourceAnalysisRepository,
        anchors: SourceAnchorService,
        base_extraction: SourceAnalysisKnowledgeExtractionService,
        provider: ControlledStructuredModelProvider,
        runs: ModelRunRepository,
        snapshots: SourceExtractionSnapshotRepository,
        context_packages: ContextPackageService | None = None,
    ) -> None:
        self.jobs = jobs
        self.repository = repository
        self.analyses = analyses
        self.anchors = anchors
        self.base_extraction = base_extraction
        self.provider = provider
        self.runs = runs
        self.snapshots = snapshots
        self.context_packages = context_packages or ContextPackageService(runs.database)

    def enqueue(
        self,
        analysis_id: uuid.UUID,
        *,
        requested_model_id: str | None = None,
        priority: JobPriority = JobPriority.NORMAL,
        context_limit: int | None = None,
        output_reserve: int | None = None,
        safety_margin: int | None = None,
        max_hierarchy_depth: int = DEFAULT_MAX_HIERARCHY_DEPTH,
    ) -> JobRecord:
        analysis, final = self._require_completed_analysis(analysis_id)
        model = self.base_extraction.chat_generation.select_model(requested_model_id)
        config, _signature = self._pin_configuration(
            model,
            context_limit=context_limit,
            output_reserve=output_reserve,
            safety_margin=safety_margin,
            max_hierarchy_depth=max_hierarchy_depth,
        )
        return self.jobs.create(
            job_type="source.extract",
            priority=priority,
            requested_scope={
                "analysis_id": str(analysis.analysis_id),
                "final_artifact_id": str(final.artifact_id),
            },
            pinned_configuration={
                "pipeline_version": HIERARCHICAL_PIPELINE_VERSION,
                "model_id": config.model.backend_model_id,
                "model_signature_id": str(config.model_signature_id),
                "model_signature_sha256": config.model_signature_hash.hex(),
                "model": _model_payload(config.model),
                "effective_context_limit": config.effective_context_limit,
                "provider_context_length": config.effective_context_limit,
                "output_reserve": config.output_reserve,
                "safety_margin": config.safety_margin,
                "token_estimator": config.token_estimator,
                "max_hierarchy_depth": config.max_hierarchy_depth,
                "prompt_template_id": HIERARCHICAL_PROMPT_TEMPLATE_ID,
                "prompt_template_version": HIERARCHICAL_PROMPT_TEMPLATE_VERSION,
                "source_extraction_schema_id": SOURCE_EXTRACTION_SCHEMA_ID,
                "merge_schema_id": MERGE_SCHEMA_ID,
                "pair_audit_schema_id": PAIR_AUDIT_SCHEMA_ID,
                "provider_transport": config.provider_transport,
                "reasoning_mode": config.reasoning_mode,
                "temperature": config.temperature,
                "top_p": config.top_p,
                "top_k": config.top_k,
                "min_p": config.min_p,
                "repeat_penalty": config.repeat_penalty,
                "store": config.store,
                "structured_contract_version": CONTROLLED_STRUCTURED_CONTRACT_VERSION,
                "structured_validation": config.structured_validation,
                "provider_instance_policy": config.provider_instance_policy,
            },
        )

    def initialize_extraction(self, job: JobRecord) -> SourceHierarchicalExtractionRecord:
        self._validate_job(job)
        scope = _require_object(job.requested_scope_json, "requested_scope")
        config = self.pinned_configuration(job)
        analysis_id = _require_uuid(scope, "analysis_id")
        final_artifact_id = _require_uuid(scope, "final_artifact_id")
        analysis, final = self._require_completed_analysis(analysis_id)
        if final.artifact_id != final_artifact_id:
            raise SourceHierarchicalExtractionConfigurationError(
                "Pinned analysis Final Artifact changed before hierarchical extraction started."
            )
        evidence, _messages = self.base_extraction._load_evidence(analysis, final)
        return self.repository.get_or_create_extraction(
            job_id=job.job_id,
            analysis_id=analysis.analysis_id,
            final_artifact_id=final.artifact_id,
            model_signature_id=config.model_signature_id,
            pipeline_version=HIERARCHICAL_PIPELINE_VERSION,
            effective_context_limit=config.effective_context_limit,
            output_reserve=config.output_reserve,
            safety_margin=config.safety_margin,
            token_estimator=config.token_estimator,
            prompt_template_id=HIERARCHICAL_PROMPT_TEMPLATE_ID,
            prompt_template_version=HIERARCHICAL_PROMPT_TEMPLATE_VERSION,
            max_hierarchy_depth=config.max_hierarchy_depth,
            evidence=tuple(
                (item.sequence_no, item.anchor_id, item.quoted_hash) for item in evidence
            ),
        )

    def pinned_configuration(self, job: JobRecord) -> HierarchicalExtractionPinnedConfiguration:
        config = _require_object(job.pinned_configuration_json, "pinned_configuration")
        if config.get("pipeline_version") != HIERARCHICAL_PIPELINE_VERSION:
            raise SourceHierarchicalExtractionConfigurationError(
                "Pinned hierarchical extraction pipeline version changed."
            )
        if config.get("prompt_template_id") != HIERARCHICAL_PROMPT_TEMPLATE_ID or config.get(
            "prompt_template_version"
        ) != HIERARCHICAL_PROMPT_TEMPLATE_VERSION:
            raise SourceHierarchicalExtractionConfigurationError(
                "Pinned hierarchical extraction prompt identity changed."
            )
        if config.get("source_extraction_schema_id") != SOURCE_EXTRACTION_SCHEMA_ID:
            raise SourceHierarchicalExtractionConfigurationError(
                "Pinned source extraction schema identity changed."
            )
        if config.get("merge_schema_id") != MERGE_SCHEMA_ID or config.get(
            "pair_audit_schema_id"
        ) != PAIR_AUDIT_SCHEMA_ID:
            raise SourceHierarchicalExtractionConfigurationError(
                "Pinned hierarchical merge/audit schema identity changed."
            )
        model_data = config.get("model")
        if not isinstance(model_data, dict):
            raise SourceHierarchicalExtractionConfigurationError(
                "Pinned hierarchical extraction model snapshot is invalid."
            )
        signature_hash_text = config.get("model_signature_sha256")
        if not isinstance(signature_hash_text, str):
            raise SourceHierarchicalExtractionConfigurationError(
                "Pinned hierarchical extraction ModelSignature hash is invalid."
            )
        try:
            signature_hash = bytes.fromhex(signature_hash_text)
        except ValueError as exc:
            raise SourceHierarchicalExtractionConfigurationError(
                "Pinned hierarchical extraction ModelSignature hash is invalid."
            ) from exc
        if len(signature_hash) != 32:
            raise SourceHierarchicalExtractionConfigurationError(
                "Pinned hierarchical extraction ModelSignature hash is invalid."
            )
        model = _model_from_payload(model_data)
        if config.get("model_id") != model.backend_model_id:
            raise SourceHierarchicalExtractionConfigurationError(
                "Pinned hierarchical extraction model identity is inconsistent."
            )
        pinned = HierarchicalExtractionPinnedConfiguration(
            model=model,
            model_signature_id=_require_uuid(config, "model_signature_id"),
            model_signature_hash=signature_hash,
            effective_context_limit=_require_positive_int(config, "effective_context_limit"),
            output_reserve=_require_positive_int(config, "output_reserve"),
            safety_margin=_require_nonnegative_int(config, "safety_margin"),
            token_estimator=_require_text(config, "token_estimator"),
            max_hierarchy_depth=_require_positive_int(config, "max_hierarchy_depth"),
            provider_transport=_require_text(config, "provider_transport"),
            reasoning_mode=_require_text(config, "reasoning_mode"),
            temperature=_require_number(config, "temperature"),
            top_p=_require_number(config, "top_p"),
            top_k=_require_nonnegative_int(config, "top_k"),
            min_p=_require_number(config, "min_p"),
            repeat_penalty=_require_number(config, "repeat_penalty"),
            store=_require_bool(config, "store"),
            structured_validation=_require_text(config, "structured_validation"),
            provider_instance_policy=_require_text(config, "provider_instance_policy"),
        )
        if pinned.token_estimator != TOKEN_ESTIMATOR:
            raise SourceHierarchicalExtractionConfigurationError(
                "Pinned hierarchical extraction token estimator changed."
            )
        expected_controls = (
            HIERARCHICAL_REASONING_MODE,
            HIERARCHICAL_TEMPERATURE,
            HIERARCHICAL_TOP_P,
            HIERARCHICAL_TOP_K,
            HIERARCHICAL_MIN_P,
            HIERARCHICAL_REPEAT_PENALTY,
            HIERARCHICAL_STORE,
            HIERARCHICAL_STRUCTURED_VALIDATION,
            HIERARCHICAL_PROVIDER_INSTANCE_POLICY,
        )
        actual_controls = (
            pinned.reasoning_mode,
            pinned.temperature,
            pinned.top_p,
            pinned.top_k,
            pinned.min_p,
            pinned.repeat_penalty,
            pinned.store,
            pinned.structured_validation,
            pinned.provider_instance_policy,
        )
        if actual_controls != expected_controls:
            raise SourceHierarchicalExtractionModelDriftError(
                "Pinned hierarchical extraction inference controls changed."
            )
        if config.get("structured_contract_version") != CONTROLLED_STRUCTURED_CONTRACT_VERSION:
            raise SourceHierarchicalExtractionConfigurationError(
                "Pinned hierarchical extraction structured contract changed."
            )
        if _require_positive_int(config, "provider_context_length") != pinned.effective_context_limit:
            raise SourceHierarchicalExtractionConfigurationError(
                "Pinned provider context length differs from the ATHENA context budget."
            )
        if pinned.output_reserve + pinned.safety_margin >= pinned.effective_context_limit:
            raise SourceHierarchicalExtractionConfigurationError(
                "Pinned hierarchical extraction context budget is invalid."
            )
        signature = self.runs.load_signature(pinned.model_signature_id)
        if signature.signature_hash != pinned.model_signature_hash:
            raise SourceHierarchicalExtractionConfigurationError(
                "Pinned hierarchical extraction ModelSignature hash changed."
            )
        return pinned

    def assert_model_unchanged(
        self,
        job: JobRecord,
        extraction: SourceHierarchicalExtractionRecord,
    ) -> ModelInfo:
        config = self.pinned_configuration(job)
        if extraction.model_signature_id != config.model_signature_id:
            raise SourceHierarchicalExtractionModelDriftError(
                "Persisted extraction ModelSignature no longer matches its durable job."
            )
        if self.provider.controlled_structured_transport_id != config.provider_transport:
            raise SourceHierarchicalExtractionModelDriftError(
                "Active structured provider transport differs from the pinned extraction transport."
            )
        model = self.base_extraction.chat_generation.select_model(config.model.backend_model_id)
        signature = self._signature_for_model(model, config)
        if (
            signature.model_signature_id != config.model_signature_id
            or signature.signature_hash != config.model_signature_hash
        ):
            raise SourceHierarchicalExtractionModelDriftError(
                "Active Primary Model/configuration differs from the pinned extraction signature."
            )
        return model

    def ensure_planned(
        self, extraction: SourceHierarchicalExtractionRecord
    ) -> str | None:
        """Ensure the next deterministic durable work frontier exists before execution."""
        batch_items = self.repository.list_work_items(
            extraction.extraction_id, stage=SourceExtractionStage.BATCH
        )
        expected_batches = self._batch_groups(extraction)
        if len(batch_items) < len(expected_batches):
            self.plan_batches(extraction)
            return "batch_plan"
        if any(item.state is SourceExtractionWorkState.PENDING for item in batch_items):
            return None
        if any(item.state is not SourceExtractionWorkState.COMPLETED for item in batch_items):
            raise SourceHierarchicalExtractionConfigurationError(
                "Evidence batch frontier contains non-completed terminal work."
            )

        pending_merges = tuple(
            item
            for item in self.repository.list_work_items(
                extraction.extraction_id, stage=SourceExtractionStage.MERGE
            )
            if item.state is SourceExtractionWorkState.PENDING
        )
        if pending_merges:
            return None
        leaves = self.repository.leaf_proposal_artifacts(extraction.extraction_id)
        if not leaves:
            raise SourceHierarchicalExtractionConfigurationError(
                "Completed extraction batches produced no durable proposal artifacts."
            )
        if len(leaves) > 1:
            self.plan_next_merge(extraction, leaves)
            return "merge_plan"

        proposal_artifact = leaves[0]
        proposals = self.proposals_from_artifact(proposal_artifact)
        audit_groups = self._audit_pair_groups(extraction, proposals)
        audit_items = self.repository.list_work_items(
            extraction.extraction_id, stage=SourceExtractionStage.AUDIT
        )
        if len(audit_items) < len(audit_groups):
            self.plan_audits(extraction, proposal_artifact, audit_groups)
            return "audit_plan"
        if any(item.state is SourceExtractionWorkState.PENDING for item in audit_items):
            return None
        if any(item.state is not SourceExtractionWorkState.COMPLETED for item in audit_items):
            raise SourceHierarchicalExtractionConfigurationError(
                "Claim audit frontier contains non-completed terminal work."
            )

        final_items = self.repository.list_work_items(
            extraction.extraction_id, stage=SourceExtractionStage.FINAL
        )
        if not final_items:
            self.plan_final(extraction, proposal_artifact)
            return "final_plan"
        return None

    def plan_batches(
        self, extraction: SourceHierarchicalExtractionRecord
    ) -> tuple[SourceHierarchicalExtractionWorkItem, ...]:
        groups = self._batch_groups(extraction)
        created: list[SourceHierarchicalExtractionWorkItem] = []
        for ordinal, group in enumerate(groups):
            descriptor = {
                "extraction_id": str(extraction.extraction_id),
                "stage": SourceExtractionStage.BATCH.value,
                "level": 0,
                "ordinal": ordinal,
                "anchor_ids": [str(item[1]) for item in group],
                "sequence_nos": [item[0] for item in group],
                "pipeline_version": HIERARCHICAL_PIPELINE_VERSION,
            }
            created.append(
                self.repository.create_work_item(
                    extraction_id=extraction.extraction_id,
                    stage=SourceExtractionStage.BATCH,
                    level=0,
                    ordinal=ordinal,
                    inputs=tuple(
                        (SourceExtractionInputKind.SOURCE_ANCHOR, anchor_id)
                        for _sequence_no, anchor_id in group
                    ),
                    descriptor=descriptor,
                )
            )
        return tuple(created)

    def plan_next_merge(
        self,
        extraction: SourceHierarchicalExtractionRecord,
        leaves: Sequence[SourceHierarchicalExtractionArtifact] | None = None,
    ) -> SourceHierarchicalExtractionWorkItem:
        current = tuple(leaves) if leaves is not None else self.repository.leaf_proposal_artifacts(
            extraction.extraction_id
        )
        if len(current) < 2:
            raise SourceHierarchicalExtractionConfigurationError(
                "At least two proposal artifacts are required for semantic merge."
            )
        group: list[SourceHierarchicalExtractionArtifact] = []
        for artifact in current:
            candidate = (*group, artifact)
            if len(candidate) == 1 or self._merge_group_fits(extraction, candidate):
                group.append(artifact)
                continue
            break
        if len(group) < 2:
            if not self._merge_group_fits(extraction, current[:2]):
                raise SourceHierarchicalExtractionInputTooLargeError(
                    "Two proposal artifacts cannot fit one pinned semantic merge context."
                )
            group = list(current[:2])
        level = max(item.level for item in group) + 1
        if level > extraction.max_hierarchy_depth:
            raise SourceHierarchicalExtractionConfigurationError(
                "Hierarchical extraction exceeded the pinned merge depth."
            )
        existing = self.repository.list_work_items(
            extraction.extraction_id, stage=SourceExtractionStage.MERGE
        )
        same_level = [item.ordinal for item in existing if item.level == level]
        ordinal = max(same_level, default=-1) + 1
        descriptor = {
            "extraction_id": str(extraction.extraction_id),
            "stage": SourceExtractionStage.MERGE.value,
            "level": level,
            "ordinal": ordinal,
            "artifact_ids": [str(item.artifact_id) for item in group],
            "pipeline_version": HIERARCHICAL_PIPELINE_VERSION,
        }
        return self.repository.create_work_item(
            extraction_id=extraction.extraction_id,
            stage=SourceExtractionStage.MERGE,
            level=level,
            ordinal=ordinal,
            inputs=tuple(
                (SourceExtractionInputKind.ARTIFACT, item.artifact_id) for item in group
            ),
            descriptor=descriptor,
        )

    def plan_audits(
        self,
        extraction: SourceHierarchicalExtractionRecord,
        proposal_artifact: SourceHierarchicalExtractionArtifact,
        groups: Sequence[tuple[tuple[int, int], ...]] | None = None,
    ) -> tuple[SourceHierarchicalExtractionWorkItem, ...]:
        proposals = self.proposals_from_artifact(proposal_artifact)
        pair_groups = tuple(groups) if groups is not None else self._audit_pair_groups(
            extraction, proposals
        )
        created: list[SourceHierarchicalExtractionWorkItem] = []
        for ordinal, pair_group in enumerate(pair_groups):
            descriptor = {
                "extraction_id": str(extraction.extraction_id),
                "stage": SourceExtractionStage.AUDIT.value,
                "level": proposal_artifact.level + 1,
                "ordinal": ordinal,
                "proposal_artifact_id": str(proposal_artifact.artifact_id),
                "pairs": [list(pair) for pair in pair_group],
                "pipeline_version": HIERARCHICAL_PIPELINE_VERSION,
            }
            created.append(
                self.repository.create_work_item(
                    extraction_id=extraction.extraction_id,
                    stage=SourceExtractionStage.AUDIT,
                    level=proposal_artifact.level + 1,
                    ordinal=ordinal,
                    inputs=((SourceExtractionInputKind.ARTIFACT, proposal_artifact.artifact_id),),
                    descriptor=descriptor,
                )
            )
        return tuple(created)

    def plan_final(
        self,
        extraction: SourceHierarchicalExtractionRecord,
        proposal_artifact: SourceHierarchicalExtractionArtifact,
    ) -> SourceHierarchicalExtractionWorkItem:
        audit_artifacts = self.repository.list_artifacts(
            extraction.extraction_id, artifact_kind=SourceExtractionStage.AUDIT
        )
        level = max(
            [proposal_artifact.level, *(item.level for item in audit_artifacts)],
            default=proposal_artifact.level,
        ) + 1
        if level > extraction.max_hierarchy_depth + 2:
            raise SourceHierarchicalExtractionConfigurationError(
                "Hierarchical extraction finalization exceeded the bounded depth."
            )
        inputs = (
            (SourceExtractionInputKind.ARTIFACT, proposal_artifact.artifact_id),
            *tuple(
                (SourceExtractionInputKind.ARTIFACT, item.artifact_id)
                for item in audit_artifacts
            ),
        )
        descriptor = {
            "extraction_id": str(extraction.extraction_id),
            "stage": SourceExtractionStage.FINAL.value,
            "level": level,
            "ordinal": 0,
            "proposal_artifact_id": str(proposal_artifact.artifact_id),
            "audit_artifact_ids": [str(item.artifact_id) for item in audit_artifacts],
            "pipeline_version": HIERARCHICAL_PIPELINE_VERSION,
        }
        return self.repository.create_work_item(
            extraction_id=extraction.extraction_id,
            stage=SourceExtractionStage.FINAL,
            level=level,
            ordinal=0,
            inputs=inputs,
            descriptor=descriptor,
        )

    def prepare_call(
        self,
        extraction: SourceHierarchicalExtractionRecord,
        work_item: SourceHierarchicalExtractionWorkItem,
    ) -> PreparedHierarchicalExtractionCall:
        if work_item.extraction_id != extraction.extraction_id:
            raise SourceHierarchicalExtractionConfigurationError(
                "Extraction work item belongs to another extraction."
            )
        if work_item.state is not SourceExtractionWorkState.PENDING:
            raise SourceHierarchicalExtractionConfigurationError(
                "Only pending hierarchical extraction work can prepare a model call."
            )
        if work_item.stage is SourceExtractionStage.BATCH:
            messages, refs = self._prepare_batch_messages(extraction, work_item)
            schema_id = SOURCE_EXTRACTION_SCHEMA_ID
            schema = extraction_json_schema()
        elif work_item.stage is SourceExtractionStage.MERGE:
            proposals, refs = self._merge_input_proposals(work_item)
            messages = _merge_messages(proposals)
            schema_id = MERGE_SCHEMA_ID
            schema = _merge_schema(
                knowledge_count=len(proposals.knowledge_units),
                claim_count=len(proposals.claims),
            )
        elif work_item.stage is SourceExtractionStage.AUDIT:
            proposal_artifact = self._single_artifact_input(work_item)
            proposals = self.proposals_from_artifact(proposal_artifact)
            groups = self._audit_pair_groups(extraction, proposals)
            try:
                pair_group = groups[work_item.ordinal]
            except IndexError as exc:
                raise SourceHierarchicalExtractionConfigurationError(
                    "Persisted audit ordinal no longer maps to the deterministic pair plan."
                ) from exc
            messages = _pair_audit_messages(proposals, pair_group)
            schema_id = PAIR_AUDIT_SCHEMA_ID
            schema = _pair_audit_schema(pair_count=len(pair_group))
            refs = (str(proposal_artifact.artifact_id),)
        else:
            raise SourceHierarchicalExtractionConfigurationError(
                "Final extraction work is deterministic and must not call the Primary Model."
            )
        estimated = self._estimate_controlled_request_tokens(messages, schema_id, schema)
        if estimated > extraction.input_budget:
            raise SourceHierarchicalExtractionInputTooLargeError(
                f"{work_item.stage.value} work exceeds the pinned extraction input budget."
            )
        return PreparedHierarchicalExtractionCall(
            work_item=work_item,
            messages=messages,
            schema_id=schema_id,
            schema=schema,
            estimated_input_tokens=estimated,
            input_refs=refs,
        )

    def _context_package_for_prepared(
        self,
        *,
        extraction: SourceHierarchicalExtractionRecord,
        prepared: PreparedHierarchicalExtractionCall,
    ) -> ContextPackage:
        snapshot_commit_seq = self.context_packages.current_commit_seq()

        # prepared.input_refs are operation-level logical labels. In BATCH they
        # intentionally look like "evidence:1", not UUIDs. Durable ContextPackage
        # identity must therefore come from the persisted WorkItem inputs.
        work_inputs = self.repository.inputs_for_work_item(
            prepared.work_item.work_item_id
        )
        refs_list: list[ContextIncludedRef] = []
        for index, item in enumerate(work_inputs, start=1):
            if (
                item.input_kind is SourceExtractionInputKind.SOURCE_ANCHOR
                and item.source_anchor_id is not None
            ):
                entity_type = "source_anchor"
                entity_id = item.source_anchor_id
            elif (
                item.input_kind is SourceExtractionInputKind.ARTIFACT
                and item.artifact_id is not None
            ):
                entity_type = "source_extraction_artifact"
                entity_id = item.artifact_id
            else:
                raise SourceHierarchicalExtractionConfigurationError(
                    "Hierarchical ContextPackage input lacks durable identity."
                )
            refs_list.append(
                ContextIncludedRef(
                    ref_id=f"INPUT-{index:03d}",
                    entity_type=entity_type,
                    entity_id=entity_id,
                    revision_id=None,
                )
            )
        refs = tuple(refs_list)
        if not refs:
            raise SourceHierarchicalExtractionConfigurationError(
                "Hierarchical ContextPackage has no durable WorkItem inputs."
            )

        sections = tuple(
            ContextSection(
                name=(
                    "hierarchical_extraction_policy"
                    if index == 0
                    else "hierarchical_extraction_task"
                ),
                role=cast(ContextRole, message.role),
                content=message.content,
                included_ref_ids=(
                    tuple(item.ref_id for item in refs)
                    if index == len(prepared.messages) - 1
                    else ()
                ),
            )
            for index, message in enumerate(prepared.messages)
        )
        signature = self.runs.load_signature(extraction.model_signature_id)
        return self.context_packages.build_from_sections(
            model_signature=signature,
            budget=ContextPackageBudget(
                effective_context_limit=extraction.effective_context_limit,
                context_budget=extraction.input_budget,
                output_reserve=extraction.output_reserve,
                safety_margin=extraction.safety_margin,
            ),
            sections=sections,
            included_refs=refs,
            excluded_candidate_summary=ExcludedCandidateSummary(
                retrieval_candidate_count=len(refs),
                retrieval_included_count=len(refs),
                retrieval_excluded_count=0,
                memory_candidate_count=0,
                memory_included_count=0,
                memory_excluded_count=0,
                conversation_candidate_count=0,
                conversation_included_count=0,
                conversation_excluded_count=0,
            ),
            token_estimates=ContextTokenEstimates(
                conversation_tokens=0,
                current_user_tokens=0,
                system_tokens=0,
                context_tokens=prepared.estimated_input_tokens,
                estimated_input_tokens=prepared.estimated_input_tokens,
                estimated_total_tokens=(
                    prepared.estimated_input_tokens
                    + extraction.output_reserve
                    + extraction.safety_margin
                ),
            ),
            snapshot_commit_seq=snapshot_commit_seq,
            structured_schema_id=prepared.schema_id,
            structured_schema=prepared.schema,
        )

    def execute_call(
        self,
        *,
        job: JobRecord,
        lease_token: bytes,
        extraction: SourceHierarchicalExtractionRecord,
        model: ModelInfo,
        prepared: PreparedHierarchicalExtractionCall,
        extend_seconds: int = 120,
    ) -> SourceHierarchicalExtractionArtifact:
        package = self._context_package_for_prepared(
            extraction=extraction,
            prepared=prepared,
        )
        self.context_packages.assert_snapshot_current(
            package.snapshot_commit_seq,
            phase="hierarchical-extraction-pre-attempt",
        )
        attempted = self.repository.begin_attempt(
            prepared.work_item.work_item_id,
            job_id=job.job_id,
            lease_token=lease_token,
        )
        actor_id = self.base_extraction.chat.ensure_local_user()
        config = self.pinned_configuration(job)
        run = self.runs.start_run(
            run_type=f"source_knowledge_extraction_{attempted.stage.value}",
            trigger_actor_id=actor_id,
            pipeline_version=HIERARCHICAL_PIPELINE_VERSION,
            input_snapshot={
                # Keep the established 4C-B ProcessingRun fields stable and
                # attach the formal model-call contract under context_package.
                "context_package": package.run_snapshot(),
                "context_package_request_id": str(package.request_id),
                "snapshot_commit_seq": package.snapshot_commit_seq,
                "extraction_id": str(extraction.extraction_id),
                "analysis_id": str(extraction.analysis_id),
                "final_artifact_id": str(extraction.final_artifact_id),
                "work_item_id": str(attempted.work_item_id),
                "stage": attempted.stage.value,
                "level": attempted.level,
                "ordinal": attempted.ordinal,
                "input_refs": list(prepared.input_refs),
                "estimated_input_tokens": prepared.estimated_input_tokens,
                "effective_context_limit": extraction.effective_context_limit,
                "output_reserve": extraction.output_reserve,
                "safety_margin": extraction.safety_margin,
                "token_estimator": extraction.token_estimator,
            },
            configuration={
                "pipeline_version": HIERARCHICAL_PIPELINE_VERSION,
                "schema_id": prepared.schema_id,
                "prompt_template_id": HIERARCHICAL_PROMPT_TEMPLATE_ID,
                "prompt_template_version": HIERARCHICAL_PROMPT_TEMPLATE_VERSION,
                "provider_transport": config.provider_transport,
                "reasoning_mode": config.reasoning_mode,
                "temperature": config.temperature,
                "top_p": config.top_p,
                "top_k": config.top_k,
                "min_p": config.min_p,
                "repeat_penalty": config.repeat_penalty,
                "store": config.store,
                "context_length": extraction.effective_context_limit,
                "max_output_tokens": extraction.output_reserve,
                "structured_contract_version": CONTROLLED_STRUCTURED_CONTRACT_VERSION,
                "structured_validation": config.structured_validation,
                "provider_instance_policy": config.provider_instance_policy,
            },
            model_signature_id=extraction.model_signature_id,
            prompt_template_id=HIERARCHICAL_PROMPT_TEMPLATE_ID,
            prompt_template_version=HIERARCHICAL_PROMPT_TEMPLATE_VERSION,
        )
        try:
            self.context_packages.assert_snapshot_current(
                package.snapshot_commit_seq,
                phase="immediately-before-hierarchical-extraction-model-call",
            )
            structured_schema = package.structured_schema()
            assert structured_schema is not None

            provider_lease_seconds = blocking_operation_lease_seconds(
                timeout_seconds=getattr(
                    self.provider,
                    "generation_timeout_seconds",
                    None,
                ),
                base_extend_seconds=extend_seconds,
            )
            self.jobs.heartbeat(
                job.job_id,
                lease_token=lease_token,
                extend_seconds=provider_lease_seconds,
            )

            raw = self.provider.generate_controlled_structured(
                model_id=model.backend_model_id,
                messages=package.model_messages(),
                schema_id=package.structured_schema_id or prepared.schema_id,
                json_schema=structured_schema,
                reasoning_mode=config.reasoning_mode,
                context_length=extraction.effective_context_limit,
                max_output_tokens=extraction.output_reserve,
                temperature=config.temperature,
                top_p=config.top_p,
                top_k=config.top_k,
                min_p=config.min_p,
                repeat_penalty=config.repeat_penalty,
            )
            content = self._validate_semantic_output(extraction, attempted, raw)
        except KeyboardInterrupt:
            self.runs.finish_run(run.processing_run_id, status="cancelled")
            raise
        except Exception as exc:
            self.runs.finish_run(
                run.processing_run_id,
                status="failed",
                error_detail=type(exc).__name__,
            )
            raise
        return self.repository.commit_artifact(
            work_item_id=attempted.work_item_id,
            job_id=job.job_id,
            lease_token=lease_token,
            content=content,
            processing_run_id=run.processing_run_id,
        )

    def finalize(
        self,
        *,
        job: JobRecord,
        lease_token: bytes,
        extraction: SourceHierarchicalExtractionRecord,
        work_item: SourceHierarchicalExtractionWorkItem,
    ) -> SourceAnalysisExtractionResult:
        if work_item.stage is not SourceExtractionStage.FINAL:
            raise SourceHierarchicalExtractionConfigurationError(
                "Only Final hierarchical extraction work can freeze a proposal snapshot."
            )
        existing_artifact = self.repository.artifact_for_work_item(work_item.work_item_id)
        if existing_artifact is None:
            inputs = self.repository.inputs_for_work_item(work_item.work_item_id)
            artifact_inputs = [
                self.repository.get_artifact(item.artifact_id)
                for item in inputs
                if item.input_kind is SourceExtractionInputKind.ARTIFACT
                and item.artifact_id is not None
            ]
            proposal_artifacts = [
                item
                for item in artifact_inputs
                if item.artifact_kind in {SourceExtractionStage.BATCH, SourceExtractionStage.MERGE}
            ]
            if len(proposal_artifacts) != 1:
                raise SourceHierarchicalExtractionConfigurationError(
                    "Final extraction work requires exactly one deduplicated proposal artifact."
                )
            proposals = self.proposals_from_artifact(proposal_artifacts[0])
            audit_artifacts = [
                item for item in artifact_inputs if item.artifact_kind is SourceExtractionStage.AUDIT
            ]
            proposals = self._apply_audit_artifacts(proposals, audit_artifacts)
            actor_id = self.base_extraction.chat.ensure_local_user()
            evidence = self._snapshot_evidence(extraction)
            analysis = self.analyses.get_analysis(extraction.analysis_id)
            config = self.pinned_configuration(job)
            run = self.runs.start_run(
                run_type="source_knowledge_extraction",
                trigger_actor_id=actor_id,
                pipeline_version=HIERARCHICAL_PIPELINE_VERSION,
                input_snapshot={
                    "analysis_id": str(analysis.analysis_id),
                    "final_artifact_id": str(extraction.final_artifact_id),
                    "source_id": str(analysis.source_id),
                    "representation_id": str(analysis.representation_id),
                    "evidence": [
                        {
                            "sequence_no": item.sequence_no,
                            "anchor_id": str(item.anchor_id),
                            "quoted_hash": item.quoted_hash.hex(),
                        }
                        for item in evidence
                    ],
                    "hierarchical_extraction_id": str(extraction.extraction_id),
                    "proposal_artifact_id": str(proposal_artifacts[0].artifact_id),
                    "audit_artifact_ids": [str(item.artifact_id) for item in audit_artifacts],
                    "effective_context_limit": extraction.effective_context_limit,
                    "output_reserve": extraction.output_reserve,
                    "provider_max_output_tokens": extraction.output_reserve,
                    "safety_margin": extraction.safety_margin,
                    "token_estimator": extraction.token_estimator,
                },
                configuration={
                    "pipeline_version": HIERARCHICAL_PIPELINE_VERSION,
                    "schema_id": SOURCE_EXTRACTION_SCHEMA_ID,
                    "merge_schema_id": MERGE_SCHEMA_ID,
                    "pair_audit_schema_id": PAIR_AUDIT_SCHEMA_ID,
                    "prompt_template_id": HIERARCHICAL_PROMPT_TEMPLATE_ID,
                    "prompt_template_version": HIERARCHICAL_PROMPT_TEMPLATE_VERSION,
                    "provider_transport": config.provider_transport,
                    "reasoning_mode": config.reasoning_mode,
                    "temperature": config.temperature,
                    "top_p": config.top_p,
                    "top_k": config.top_k,
                    "min_p": config.min_p,
                    "repeat_penalty": config.repeat_penalty,
                    "store": config.store,
                    "context_length": extraction.effective_context_limit,
                    "max_output_tokens": extraction.output_reserve,
                    "structured_contract_version": CONTROLLED_STRUCTURED_CONTRACT_VERSION,
                    "structured_validation": config.structured_validation,
                    "provider_instance_policy": config.provider_instance_policy,
                },
                model_signature_id=extraction.model_signature_id,
                prompt_template_id=HIERARCHICAL_PROMPT_TEMPLATE_ID,
                prompt_template_version=HIERARCHICAL_PROMPT_TEMPLATE_VERSION,
            )
            existing_artifact = self.repository.commit_artifact(
                work_item_id=work_item.work_item_id,
                job_id=job.job_id,
                lease_token=lease_token,
                content={"proposals": _proposal_payload(proposals)},
                processing_run_id=run.processing_run_id,
            )
        proposals = self.proposals_from_artifact(existing_artifact)
        evidence = self._snapshot_evidence(extraction)
        analysis = self.analyses.get_analysis(extraction.analysis_id)
        run = self.runs.load_run(existing_artifact.processing_run_id)
        signature = self.runs.load_signature(extraction.model_signature_id)
        config = self.pinned_configuration(job)
        result = SourceAnalysisExtractionResult(
            analysis_id=analysis.analysis_id,
            final_artifact_id=extraction.final_artifact_id,
            source_id=analysis.source_id,
            representation_id=analysis.representation_id,
            model=config.model,
            model_signature=signature,
            processing_run=run,
            proposals=proposals,
            evidence=evidence,
        )
        self.snapshots.save(result)
        self.repository.mark_completed(
            extraction.extraction_id,
            final_work_artifact_id=existing_artifact.artifact_id,
            job_id=job.job_id,
            lease_token=lease_token,
        )
        return result

    def proposals_from_artifact(
        self, artifact: SourceHierarchicalExtractionArtifact
    ) -> ExtractionProposalSet:
        try:
            payload = json.loads(artifact.content_json)
        except json.JSONDecodeError as exc:
            raise SourceHierarchicalExtractionOutputError(
                "Durable extraction artifact is invalid JSON."
            ) from exc
        if not isinstance(payload, dict) or set(payload) != {"proposals"}:
            raise SourceHierarchicalExtractionOutputError(
                "Durable proposal artifact has an invalid envelope."
            )
        proposals_payload = payload["proposals"]
        if not isinstance(proposals_payload, Mapping):
            raise SourceHierarchicalExtractionOutputError(
                "Durable proposal artifact payload is invalid."
            )
        proposals = _proposals_from_payload(proposals_payload)
        if proposals.merge_candidates:
            raise SourceHierarchicalExtractionOutputError(
                "Hierarchical source proposal artifacts cannot carry canonical merge candidates."
            )
        return proposals

    def _validate_semantic_output(
        self,
        extraction: SourceHierarchicalExtractionRecord,
        work_item: SourceHierarchicalExtractionWorkItem,
        raw: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        if work_item.stage is SourceExtractionStage.BATCH:
            source_messages = self._source_messages_for_work(extraction, work_item)
            try:
                proposals = parse_extraction_proposals(raw, source_messages=source_messages)
            except ExtractionValidationError as exc:
                raise SourceHierarchicalExtractionOutputError(
                    f"Evidence batch output failed grounded extraction validation: {exc}"
                ) from exc
            if proposals.relations or proposals.merge_candidates:
                raise SourceHierarchicalExtractionOutputError(
                    "Evidence batch extraction must leave relations and merge_candidates empty."
                )
            return {"proposals": _proposal_payload(proposals)}
        if work_item.stage is SourceExtractionStage.MERGE:
            proposals, _refs = self._merge_input_proposals(work_item)
            decisions = _parse_merge_decisions(
                raw,
                knowledge_count=len(proposals.knowledge_units),
                claim_count=len(proposals.claims),
            )
            merged = _apply_merge_decisions(proposals, decisions)
            return {"proposals": _proposal_payload(merged)}
        if work_item.stage is SourceExtractionStage.AUDIT:
            proposal_artifact = self._single_artifact_input(work_item)
            proposals = self.proposals_from_artifact(proposal_artifact)
            groups = self._audit_pair_groups(extraction, proposals)
            try:
                pair_group = groups[work_item.ordinal]
            except IndexError as exc:
                raise SourceHierarchicalExtractionOutputError(
                    "Audit output no longer maps to its deterministic pair group."
                ) from exc
            assessments = _parse_pair_audit(raw, pairs=pair_group)
            return {
                "assessments": [
                    {
                        "pair_no": item.pair_no,
                        "left_claim_index": item.left_claim_index,
                        "right_claim_index": item.right_claim_index,
                        "relationship": item.relationship.value,
                        "confidence": item.confidence,
                        "reason": item.reason,
                    }
                    for item in assessments
                ]
            }
        raise SourceHierarchicalExtractionOutputError(
            "Final extraction work cannot accept Primary Model output."
        )

    @staticmethod
    def _estimate_controlled_request_tokens(
        messages: Sequence[ModelChatMessage],
        schema_id: str,
        schema: Mapping[str, Any],
    ) -> int:
        if len(messages) != 2 or messages[0].role != "system" or messages[1].role != "user":
            raise SourceHierarchicalExtractionConfigurationError(
                "Controlled structured calls require exactly one system and one user message."
            )
        estimated_messages = (
            ModelChatMessage(
                role="system",
                content=(
                    f"{messages[0].content}"
                    f"{controlled_structured_contract_prefix(schema_id)}"
                ),
            ),
            messages[1],
        )
        return _estimate_request_tokens(estimated_messages, schema)

    def _batch_groups(
        self, extraction: SourceHierarchicalExtractionRecord
    ) -> tuple[tuple[tuple[int, uuid.UUID], ...], ...]:
        analysis = self.analyses.get_analysis(extraction.analysis_id)
        final = self.analyses.get_artifact(extraction.final_artifact_id)
        evidence = self.repository.evidence(extraction.extraction_id)
        source_text = self._verified_source_messages(extraction)
        groups: list[tuple[tuple[int, uuid.UUID], ...]] = []
        current: list[tuple[int, uuid.UUID]] = []
        for item in evidence:
            candidate = (*current, (item.sequence_no, item.source_anchor_id))
            candidate_messages = {
                sequence_no: source_text[sequence_no] for sequence_no, _anchor_id in candidate
            }
            messages = self._batch_messages(analysis, final, candidate_messages)
            estimated = self._estimate_controlled_request_tokens(
                messages, SOURCE_EXTRACTION_SCHEMA_ID, extraction_json_schema()
            )
            if estimated <= extraction.input_budget:
                current.append((item.sequence_no, item.source_anchor_id))
                continue
            if not current:
                raise SourceHierarchicalExtractionInputTooLargeError(
                    f"Evidence slot {item.sequence_no} cannot fit one pinned extraction context."
                )
            groups.append(tuple(current))
            current = [(item.sequence_no, item.source_anchor_id)]
            messages = self._batch_messages(
                analysis,
                final,
                {item.sequence_no: source_text[item.sequence_no]},
            )
            if (
                self._estimate_controlled_request_tokens(
                    messages, SOURCE_EXTRACTION_SCHEMA_ID, extraction_json_schema()
                )
                > extraction.input_budget
            ):
                raise SourceHierarchicalExtractionInputTooLargeError(
                    f"Evidence slot {item.sequence_no} cannot fit one pinned extraction context."
                )
        if current:
            groups.append(tuple(current))
        if not groups:
            raise SourceHierarchicalExtractionConfigurationError(
                "Hierarchical extraction planned no evidence batches."
            )
        return tuple(groups)

    def _prepare_batch_messages(
        self,
        extraction: SourceHierarchicalExtractionRecord,
        work_item: SourceHierarchicalExtractionWorkItem,
    ) -> tuple[tuple[ModelChatMessage, ...], tuple[str, ...]]:
        analysis = self.analyses.get_analysis(extraction.analysis_id)
        final = self.analyses.get_artifact(extraction.final_artifact_id)
        source_messages = self._source_messages_for_work(extraction, work_item)
        return self._batch_messages(analysis, final, source_messages), tuple(
            f"evidence:{sequence_no}" for sequence_no in source_messages
        )

    def _batch_messages(
        self,
        analysis: SourceAnalysisRecord,
        final: SourceAnalysisArtifact,
        source_messages: Mapping[int, str],
    ) -> tuple[ModelChatMessage, ...]:
        system, user = self.base_extraction._build_prompt(
            analysis=analysis,
            final=final,
            source_messages=source_messages,
        )
        controlled_user = (
            f"{user}\n\n"
            "ATHENA_GROUNDING_CHECK: For every KnowledgeUnit and Claim, first choose exactly "
            "one source_sequence_no N from the SOURCE_EVIDENCE slots in this request. Then copy "
            "source_quote character-for-character from inside that SAME [N] ... [/EVIDENCE_N] "
            "block. Never pair a quote from one evidence slot with another sequence number. "
            "Before returning, verify that each source_quote occurs verbatim in the selected "
            "evidence block. If you cannot verify a proposal, omit it rather than guessing.\n"
            "ATHENA_CONTROL: Produce the final structured output directly. /no_think"
        )
        return (
            ModelChatMessage(role="system", content=system),
            ModelChatMessage(role="user", content=controlled_user),
        )

    def _source_messages_for_work(
        self,
        extraction: SourceHierarchicalExtractionRecord,
        work_item: SourceHierarchicalExtractionWorkItem,
    ) -> dict[int, str]:
        inputs = self.repository.inputs_for_work_item(work_item.work_item_id)
        sequence_by_anchor = {
            item.source_anchor_id: item.sequence_no
            for item in self.repository.evidence(extraction.extraction_id)
        }
        all_text = self._verified_source_messages(extraction)
        result: dict[int, str] = {}
        for item in inputs:
            if item.input_kind is not SourceExtractionInputKind.SOURCE_ANCHOR or item.source_anchor_id is None:
                raise SourceHierarchicalExtractionConfigurationError(
                    "Evidence batch work contains a non-SourceAnchor input."
                )
            sequence_no = sequence_by_anchor.get(item.source_anchor_id)
            if sequence_no is None:
                raise SourceHierarchicalExtractionConfigurationError(
                    "Evidence batch references no frozen global evidence slot."
                )
            result[sequence_no] = all_text[sequence_no]
        if not result:
            raise SourceHierarchicalExtractionConfigurationError(
                "Evidence batch has no frozen source evidence."
            )
        return dict(sorted(result.items()))

    def _verified_source_messages(
        self, extraction: SourceHierarchicalExtractionRecord
    ) -> dict[int, str]:
        analysis = self.analyses.get_analysis(extraction.analysis_id)
        expected_anchor_ids = set(
            self.analyses.source_anchor_ids_for_artifact(extraction.final_artifact_id)
        )
        evidence = self.repository.evidence(extraction.extraction_id)
        if {item.source_anchor_id for item in evidence} != expected_anchor_ids:
            raise SourceHierarchicalExtractionConfigurationError(
                "Frozen hierarchical extraction evidence no longer matches Final provenance."
            )
        messages: dict[int, str] = {}
        for item in evidence:
            anchor = self.anchors.verify(item.source_anchor_id)
            if anchor.source_id != analysis.source_id or anchor.representation_id != analysis.representation_id:
                raise SourceHierarchicalExtractionConfigurationError(
                    "Frozen extraction evidence crossed the pinned source/representation scope."
                )
            if anchor.quoted_hash != item.quoted_hash:
                raise SourceHierarchicalExtractionConfigurationError(
                    "Frozen hierarchical extraction SourceAnchor hash changed."
                )
            text = self.anchors.read_text(item.source_anchor_id)
            if hashlib.sha256(text.encode("utf-8")).digest() != item.quoted_hash:
                raise SourceHierarchicalExtractionConfigurationError(
                    "Frozen hierarchical extraction evidence failed text hash verification."
                )
            messages[item.sequence_no] = text
        if set(messages) != set(range(1, len(evidence) + 1)):
            raise SourceHierarchicalExtractionConfigurationError(
                "Frozen hierarchical extraction evidence slots are not contiguous."
            )
        return messages

    def _merge_input_proposals(
        self, work_item: SourceHierarchicalExtractionWorkItem
    ) -> tuple[ExtractionProposalSet, tuple[str, ...]]:
        inputs = self.repository.inputs_for_work_item(work_item.work_item_id)
        artifacts: list[SourceHierarchicalExtractionArtifact] = []
        for item in inputs:
            if item.input_kind is not SourceExtractionInputKind.ARTIFACT or item.artifact_id is None:
                raise SourceHierarchicalExtractionConfigurationError(
                    "Merge work contains a non-artifact input."
                )
            artifact = self.repository.get_artifact(item.artifact_id)
            if artifact.artifact_kind not in {SourceExtractionStage.BATCH, SourceExtractionStage.MERGE}:
                raise SourceHierarchicalExtractionConfigurationError(
                    "Merge work can consume only batch/merge proposal artifacts."
                )
            artifacts.append(artifact)
        if len(artifacts) < 2:
            raise SourceHierarchicalExtractionConfigurationError(
                "Semantic merge work requires at least two proposal artifacts."
            )
        proposals = _combine_proposal_sets(tuple(self.proposals_from_artifact(item) for item in artifacts))
        return proposals, tuple(str(item.artifact_id) for item in artifacts)

    def _merge_group_fits(
        self,
        extraction: SourceHierarchicalExtractionRecord,
        artifacts: Sequence[SourceHierarchicalExtractionArtifact],
    ) -> bool:
        proposals = _combine_proposal_sets(tuple(self.proposals_from_artifact(item) for item in artifacts))
        messages = _merge_messages(proposals)
        schema = _merge_schema(
            knowledge_count=len(proposals.knowledge_units),
            claim_count=len(proposals.claims),
        )
        return (
            self._estimate_controlled_request_tokens(messages, MERGE_SCHEMA_ID, schema)
            <= extraction.input_budget
        )

    def _audit_pair_groups(
        self,
        extraction: SourceHierarchicalExtractionRecord,
        proposals: ExtractionProposalSet,
    ) -> tuple[tuple[tuple[int, int], ...], ...]:
        pairs = tuple(combinations(range(len(proposals.claims)), 2))
        if not pairs:
            return ()
        groups: list[tuple[tuple[int, int], ...]] = []
        current: list[tuple[int, int]] = []
        for pair in pairs:
            candidate = (*current, pair)
            messages = _pair_audit_messages(proposals, candidate)
            schema = _pair_audit_schema(pair_count=len(candidate))
            if (
                self._estimate_controlled_request_tokens(messages, PAIR_AUDIT_SCHEMA_ID, schema)
                <= extraction.input_budget
            ):
                current.append(pair)
                continue
            if not current:
                raise SourceHierarchicalExtractionInputTooLargeError(
                    f"Claim pair {pair} cannot fit one pinned contradiction-audit context."
                )
            groups.append(tuple(current))
            current = [pair]
            messages = _pair_audit_messages(proposals, current)
            if (
                self._estimate_controlled_request_tokens(
                    messages,
                    PAIR_AUDIT_SCHEMA_ID,
                    _pair_audit_schema(pair_count=1),
                )
                > extraction.input_budget
            ):
                raise SourceHierarchicalExtractionInputTooLargeError(
                    f"Claim pair {pair} cannot fit one pinned contradiction-audit context."
                )
        if current:
            groups.append(tuple(current))
        return tuple(groups)

    def _single_artifact_input(
        self, work_item: SourceHierarchicalExtractionWorkItem
    ) -> SourceHierarchicalExtractionArtifact:
        inputs = self.repository.inputs_for_work_item(work_item.work_item_id)
        if (
            len(inputs) != 1
            or inputs[0].input_kind is not SourceExtractionInputKind.ARTIFACT
            or inputs[0].artifact_id is None
        ):
            raise SourceHierarchicalExtractionConfigurationError(
                "Audit work requires exactly one proposal artifact input."
            )
        return self.repository.get_artifact(inputs[0].artifact_id)

    def _apply_audit_artifacts(
        self,
        proposals: ExtractionProposalSet,
        audit_artifacts: Sequence[SourceHierarchicalExtractionArtifact],
    ) -> ExtractionProposalSet:
        expected_pairs = set(combinations(range(len(proposals.claims)), 2))
        seen: set[tuple[int, int]] = set()
        relations = list(proposals.relations)
        for artifact in sorted(audit_artifacts, key=lambda item: (item.ordinal, item.artifact_id.bytes)):
            try:
                payload = json.loads(artifact.content_json)
            except json.JSONDecodeError as exc:
                raise SourceHierarchicalExtractionOutputError(
                    "Durable audit artifact is invalid JSON."
                ) from exc
            if not isinstance(payload, dict) or set(payload) != {"assessments"}:
                raise SourceHierarchicalExtractionOutputError(
                    "Durable audit artifact has an invalid envelope."
                )
            raw_items = payload["assessments"]
            if not isinstance(raw_items, list):
                raise SourceHierarchicalExtractionOutputError(
                    "Durable audit assessments are invalid."
                )
            for raw in raw_items:
                if not isinstance(raw, dict):
                    raise SourceHierarchicalExtractionOutputError(
                        "Durable audit assessment is invalid."
                    )
                try:
                    left = int(raw["left_claim_index"])
                    right = int(raw["right_claim_index"])
                    relationship = ClaimPairRelationship(str(raw["relationship"]))
                    confidence = float(raw["confidence"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise SourceHierarchicalExtractionOutputError(
                        "Durable audit assessment is invalid."
                    ) from exc
                pair = (left, right)
                if pair in seen or pair not in expected_pairs:
                    raise SourceHierarchicalExtractionOutputError(
                        "Durable claim audit contains a duplicate or unexpected pair."
                    )
                seen.add(pair)
                if relationship is ClaimPairRelationship.CONTRADICTS:
                    relations.append(
                        ProposedRelation(
                            left_type=ProposalEntityType.CLAIM,
                            left_index=left,
                            relation_type="contradicts",
                            right_type=ProposalEntityType.CLAIM,
                            right_index=right,
                            confidence=confidence,
                        )
                    )
        if seen != expected_pairs:
            raise SourceHierarchicalExtractionOutputError(
                "Final claim audit does not cover every unordered claim pair exactly once."
            )
        return ExtractionProposalSet(
            knowledge_units=proposals.knowledge_units,
            claims=proposals.claims,
            relations=tuple(relations),
            merge_candidates=(),
        )

    def _snapshot_evidence(
        self, extraction: SourceHierarchicalExtractionRecord
    ) -> tuple[SourceExtractionEvidence, ...]:
        self._verified_source_messages(extraction)
        return tuple(
            SourceExtractionEvidence(
                sequence_no=item.sequence_no,
                anchor_id=item.source_anchor_id,
                quoted_hash=item.quoted_hash,
            )
            for item in self.repository.evidence(extraction.extraction_id)
        )

    def _require_completed_analysis(
        self, analysis_id: uuid.UUID
    ) -> tuple[SourceAnalysisRecord, SourceAnalysisArtifact]:
        analysis = self.analyses.get_analysis(analysis_id)
        if analysis.state.value != "completed" or analysis.final_artifact_id is None:
            raise SourceHierarchicalExtractionConfigurationError(
                "Hierarchical extraction requires a completed source analysis."
            )
        final = self.analyses.get_artifact(analysis.final_artifact_id)
        if final.analysis_id != analysis.analysis_id or final.artifact_kind is not AnalysisStage.FINAL:
            raise SourceHierarchicalExtractionConfigurationError(
                "Hierarchical extraction analysis Final Artifact identity is invalid."
            )
        return analysis, final

    def _pin_configuration(
        self,
        model: ModelInfo,
        *,
        context_limit: int | None,
        output_reserve: int | None,
        safety_margin: int | None,
        max_hierarchy_depth: int,
    ) -> tuple[HierarchicalExtractionPinnedConfiguration, ModelSignature]:
        if model.context_capacity is None and context_limit is None:
            raise SourceHierarchicalExtractionConfigurationError(
                "Model provider did not report context capacity; specify --context-limit."
            )
        capacity = model.context_capacity if model.context_capacity is not None else context_limit
        assert capacity is not None
        effective = capacity if context_limit is None else min(context_limit, capacity)
        if effective < 256:
            raise SourceHierarchicalExtractionConfigurationError(
                "Effective hierarchical extraction context limit is too small."
            )
        reserve = min(8192, max(512, effective // 4)) if output_reserve is None else output_reserve
        margin = min(1024, max(128, effective // 20)) if safety_margin is None else safety_margin
        if reserve <= 0 or margin < 0 or reserve + margin >= effective:
            raise SourceHierarchicalExtractionConfigurationError(
                "Invalid hierarchical extraction context budget."
            )
        if max_hierarchy_depth < 1:
            raise SourceHierarchicalExtractionConfigurationError(
                "Hierarchical extraction depth must be positive."
            )
        provisional = HierarchicalExtractionPinnedConfiguration(
            model=model,
            model_signature_id=uuid.UUID(int=0),
            model_signature_hash=b"\x00" * 32,
            effective_context_limit=effective,
            output_reserve=reserve,
            safety_margin=margin,
            token_estimator=TOKEN_ESTIMATOR,
            max_hierarchy_depth=max_hierarchy_depth,
            provider_transport=self.provider.controlled_structured_transport_id,
            reasoning_mode=HIERARCHICAL_REASONING_MODE,
            temperature=HIERARCHICAL_TEMPERATURE,
            top_p=HIERARCHICAL_TOP_P,
            top_k=HIERARCHICAL_TOP_K,
            min_p=HIERARCHICAL_MIN_P,
            repeat_penalty=HIERARCHICAL_REPEAT_PENALTY,
            store=HIERARCHICAL_STORE,
            structured_validation=HIERARCHICAL_STRUCTURED_VALIDATION,
            provider_instance_policy=HIERARCHICAL_PROVIDER_INSTANCE_POLICY,
        )
        signature = self._signature_for_model(model, provisional)
        return (
            HierarchicalExtractionPinnedConfiguration(
                model=model,
                model_signature_id=signature.model_signature_id,
                model_signature_hash=signature.signature_hash,
                effective_context_limit=effective,
                output_reserve=reserve,
                safety_margin=margin,
                token_estimator=TOKEN_ESTIMATOR,
                max_hierarchy_depth=max_hierarchy_depth,
                provider_transport=self.provider.controlled_structured_transport_id,
                reasoning_mode=HIERARCHICAL_REASONING_MODE,
                temperature=HIERARCHICAL_TEMPERATURE,
                top_p=HIERARCHICAL_TOP_P,
                top_k=HIERARCHICAL_TOP_K,
                min_p=HIERARCHICAL_MIN_P,
                repeat_penalty=HIERARCHICAL_REPEAT_PENALTY,
                store=HIERARCHICAL_STORE,
                structured_validation=HIERARCHICAL_STRUCTURED_VALIDATION,
                provider_instance_policy=HIERARCHICAL_PROVIDER_INSTANCE_POLICY,
            ),
            signature,
        )

    def _signature_for_model(
        self,
        model: ModelInfo,
        config: HierarchicalExtractionPinnedConfiguration,
    ) -> ModelSignature:
        return self.runs.get_or_create_signature(
            model=model,
            generation_parameters={
                "provider_transport": config.provider_transport,
                "reasoning_mode": config.reasoning_mode,
                "temperature": config.temperature,
                "top_p": config.top_p,
                "top_k": config.top_k,
                "min_p": config.min_p,
                "repeat_penalty": config.repeat_penalty,
                "stream": False,
                "store": config.store,
                "schema_delivery": "system_prompt_json_schema",
                "structured_contract_version": CONTROLLED_STRUCTURED_CONTRACT_VERSION,
                "structured_validation": config.structured_validation,
                "provider_instance_policy": config.provider_instance_policy,
                "source_extraction_schema_id": SOURCE_EXTRACTION_SCHEMA_ID,
                "merge_schema_id": MERGE_SCHEMA_ID,
                "pair_audit_schema_id": PAIR_AUDIT_SCHEMA_ID,
                "max_output_tokens": config.output_reserve,
            },
            context_configuration={
                "effective_context_limit": config.effective_context_limit,
                "provider_context_length": config.effective_context_limit,
                "output_reserve": config.output_reserve,
                "safety_margin": config.safety_margin,
                "token_estimator": config.token_estimator,
                "grounding": "hierarchical_verified_source_anchor_exact_quote",
                "prompt_template_id": HIERARCHICAL_PROMPT_TEMPLATE_ID,
                "prompt_template_version": HIERARCHICAL_PROMPT_TEMPLATE_VERSION,
            },
        )

    @staticmethod
    def _validate_job(job: JobRecord) -> None:
        if job.job_type != "source.extract":
            raise SourceHierarchicalExtractionConfigurationError(
                f"Expected source.extract job, got {job.job_type!r}."
            )


def _combine_proposal_sets(values: Sequence[ExtractionProposalSet]) -> ExtractionProposalSet:
    knowledge: list[ProposedKnowledgeUnit] = []
    claims: list[ProposedClaim] = []
    for value in values:
        if value.relations or value.merge_candidates:
            raise SourceHierarchicalExtractionOutputError(
                "Pre-audit proposal artifacts must not contain relations or merge candidates."
            )
        knowledge.extend(value.knowledge_units)
        claims.extend(value.claims)
    return ExtractionProposalSet(
        knowledge_units=tuple(knowledge),
        claims=tuple(claims),
        relations=(),
        merge_candidates=(),
    )


def _merge_messages(proposals: ExtractionProposalSet) -> tuple[ModelChatMessage, ...]:
    system = (
        "You are ATHENA's active Primary Model performing cross-batch semantic deduplication. "
        "The listed proposals are already source-grounded. Decide only whether proposals of the SAME "
        "type express the same semantic fact/claim closely enough that one can be removed without "
        "losing meaning, scope, qualification, uncertainty, time, or attribution. Do not merge merely "
        "because wording is similar. When uncertain, keep both by OMITTING that duplicate group. "
        "For every true duplicate group, member_indexes MUST contain every member exactly once, "
        "INCLUDING keep_index, and keep_index MUST be one of member_indexes. For example, "
        "keep_index=2 with member_indexes=[0,2] is valid. Return only final duplicate groups from "
        "the supplied JSON schema. Do not explain, deliberate, restate, reconsider, self-correct, "
        "or emit prose before or after the JSON object. You may only identify duplicates by proposal "
        "index; never rewrite or synthesize proposal text."
    )
    lines = ["KNOWLEDGE PROPOSALS"]
    for index, knowledge_item in enumerate(proposals.knowledge_units):
        lines.append(
            f"[K{index}] source=[{knowledge_item.source_sequence_no}] "
            f"kind={knowledge_item.knowledge_kind.value} "
            f"status={knowledge_item.epistemic_status.value} "
            f"title={knowledge_item.title!r} body={knowledge_item.body}"
        )
    lines.append("CLAIM PROPOSALS")
    for index, claim_item in enumerate(proposals.claims):
        lines.append(
            f"[C{index}] source=[{claim_item.source_sequence_no}] "
            f"kind={claim_item.claim_kind.value} "
            f"status={claim_item.epistemic_status.value} statement={claim_item.statement}"
        )
    lines.append("ATHENA_CONTROL: Produce the final structured output directly. /no_think")
    return (
        ModelChatMessage(role="system", content=system),
        ModelChatMessage(role="user", content="\n".join(lines)),
    )


def _merge_schema(*, knowledge_count: int, claim_count: int) -> dict[str, Any]:
    def decisions(maximum: int) -> dict[str, Any]:
        if maximum < 1:
            return {"type": "array", "maxItems": 0, "items": {"type": "object"}}
        return {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "keep_index": {"type": "integer", "minimum": 0, "maximum": maximum - 1},
                    "member_indexes": {
                        "type": "array",
                        "minItems": 2,
                        "uniqueItems": True,
                        "items": {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": maximum - 1,
                        },
                    },
                },
                "required": ["keep_index", "member_indexes"],
            },
        }

    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "knowledge_duplicates": decisions(knowledge_count),
            "claim_duplicates": decisions(claim_count),
        },
        "required": ["knowledge_duplicates", "claim_duplicates"],
    }


def _parse_merge_decisions(
    payload: Mapping[str, Any],
    *,
    knowledge_count: int,
    claim_count: int,
) -> tuple[MergeDecision, ...]:
    if set(payload) != {"knowledge_duplicates", "claim_duplicates"}:
        raise SourceHierarchicalExtractionOutputError(
            "Semantic merge output has unexpected root keys."
        )
    result: list[MergeDecision] = []
    result.extend(
        _parse_merge_decision_list(
            payload["knowledge_duplicates"],
            proposal_type=ProposalEntityType.KNOWLEDGE,
            proposal_count=knowledge_count,
        )
    )
    result.extend(
        _parse_merge_decision_list(
            payload["claim_duplicates"],
            proposal_type=ProposalEntityType.CLAIM,
            proposal_count=claim_count,
        )
    )
    return tuple(result)


def _parse_merge_decision_list(
    value: object,
    *,
    proposal_type: ProposalEntityType,
    proposal_count: int,
) -> tuple[MergeDecision, ...]:
    if not isinstance(value, list):
        raise SourceHierarchicalExtractionOutputError("Semantic merge decisions must be arrays.")
    result: list[MergeDecision] = []
    touched: set[int] = set()
    for raw in value:
        if not isinstance(raw, dict) or set(raw) != {
            "keep_index",
            "member_indexes",
        }:
            raise SourceHierarchicalExtractionOutputError("Semantic merge decision is invalid.")
        keep = _plain_nonnegative_int(raw["keep_index"], "keep_index")
        members_raw = raw["member_indexes"]
        if not isinstance(members_raw, list) or len(members_raw) < 2:
            raise SourceHierarchicalExtractionOutputError(
                "Semantic merge decision requires at least two member indexes."
            )
        members = tuple(
            _plain_nonnegative_int(item, "member_index") for item in members_raw
        )
        if keep >= proposal_count or any(item >= proposal_count for item in members):
            raise SourceHierarchicalExtractionOutputError(
                "Semantic merge decision references no proposal."
            )
        if len(set(members)) != len(members):
            raise SourceHierarchicalExtractionOutputError(
                "Semantic merge decision member indexes must be unique."
            )
        if keep not in members:
            raise SourceHierarchicalExtractionOutputError(
                "Semantic merge decision keep_index must be a member of member_indexes."
            )
        duplicates = tuple(item for item in members if item != keep)
        group = set(members)
        if touched.intersection(group):
            raise SourceHierarchicalExtractionOutputError(
                "Semantic merge decisions overlap; transitive ambiguity is not accepted."
            )
        touched.update(group)
        result.append(
            MergeDecision(
                proposal_type=proposal_type,
                keep_index=keep,
                duplicate_indexes=duplicates,
            )
        )
    return tuple(result)


def _apply_merge_decisions(
    proposals: ExtractionProposalSet,
    decisions: Sequence[MergeDecision],
) -> ExtractionProposalSet:
    remove_knowledge: set[int] = set()
    remove_claims: set[int] = set()
    for decision in decisions:
        target = (
            remove_knowledge
            if decision.proposal_type is ProposalEntityType.KNOWLEDGE
            else remove_claims
        )
        target.update(decision.duplicate_indexes)
    return ExtractionProposalSet(
        knowledge_units=tuple(
            item for index, item in enumerate(proposals.knowledge_units) if index not in remove_knowledge
        ),
        claims=tuple(item for index, item in enumerate(proposals.claims) if index not in remove_claims),
        relations=(),
        merge_candidates=(),
    )


def _pair_audit_messages(
    proposals: ExtractionProposalSet,
    pairs: Sequence[tuple[int, int]],
) -> tuple[ModelChatMessage, ...]:
    system = (
        "You are ATHENA's claim consistency auditor. Classify every numbered PAIR exactly once. "
        "Use relationship='contradicts' only when both statements cannot be true under the same "
        "subject, scope and time; otherwise use 'compatible_or_unknown'. Do not add outside knowledge. "
        "PAIR numbers are temporary slots controlled by ATHENA; return only the supplied JSON schema."
    )
    lines = ["CLAIM PAIRS"]
    for pair_no, (left, right) in enumerate(pairs, start=1):
        lines.append(
            f"[P{pair_no}] C{left}={proposals.claims[left].statement} || "
            f"C{right}={proposals.claims[right].statement}"
        )
    lines.append("ATHENA_CONTROL: Produce the final structured output directly. /no_think")
    return (
        ModelChatMessage(role="system", content=system),
        ModelChatMessage(role="user", content="\n".join(lines)),
    )


def _pair_audit_schema(*, pair_count: int) -> dict[str, Any]:
    if pair_count < 1:
        raise ValueError("pair_count must be positive.")
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "assessments": {
                "type": "array",
                "minItems": pair_count,
                "maxItems": pair_count,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "pair_no": {"type": "integer", "minimum": 1, "maximum": pair_count},
                        "relationship": {
                            "type": "string",
                            "enum": [item.value for item in ClaimPairRelationship],
                        },
                        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                        "reason": {"type": "string", "minLength": 1},
                    },
                    "required": ["pair_no", "relationship", "confidence", "reason"],
                },
            }
        },
        "required": ["assessments"],
    }


def _parse_pair_audit(
    payload: Mapping[str, Any],
    *,
    pairs: Sequence[tuple[int, int]],
) -> tuple[PairAuditAssessment, ...]:
    if set(payload) != {"assessments"} or not isinstance(payload["assessments"], list):
        raise SourceHierarchicalExtractionOutputError("Pair audit output is invalid.")
    raw_items = payload["assessments"]
    seen: set[int] = set()
    result: list[PairAuditAssessment] = []
    for raw in raw_items:
        if not isinstance(raw, dict) or set(raw) != {
            "pair_no",
            "relationship",
            "confidence",
            "reason",
        }:
            raise SourceHierarchicalExtractionOutputError("Pair audit assessment is invalid.")
        pair_no = _plain_nonnegative_int(raw["pair_no"], "pair_no")
        if pair_no < 1 or pair_no > len(pairs) or pair_no in seen:
            raise SourceHierarchicalExtractionOutputError(
                "Pair audit contains an invalid or duplicate pair slot."
            )
        seen.add(pair_no)
        relationship_raw = raw["relationship"]
        try:
            relationship = ClaimPairRelationship(str(relationship_raw))
        except ValueError as exc:
            raise SourceHierarchicalExtractionOutputError(
                "Pair audit relationship is invalid."
            ) from exc
        left, right = pairs[pair_no - 1]
        result.append(
            PairAuditAssessment(
                pair_no=pair_no,
                left_claim_index=left,
                right_claim_index=right,
                relationship=relationship,
                confidence=_plain_confidence(raw["confidence"]),
                reason=_plain_text(raw["reason"], "pair audit reason"),
            )
        )
    if seen != set(range(1, len(pairs) + 1)):
        raise SourceHierarchicalExtractionOutputError(
            "Pair audit must classify every supplied pair slot exactly once."
        )
    return tuple(sorted(result, key=lambda item: item.pair_no))


def _model_payload(model: ModelInfo) -> dict[str, Any]:
    return {
        "provider": model.provider,
        "backend_model_id": model.backend_model_id,
        "display_name": model.display_name,
        "model_type": model.model_type,
        "context_capacity": model.context_capacity,
        "quantization": model.quantization,
        "loaded": model.loaded,
        "vision": model.vision,
        "trained_for_tool_use": model.trained_for_tool_use,
    }


def _model_from_payload(value: Mapping[str, Any]) -> ModelInfo:
    try:
        return ModelInfo(
            provider=_plain_text(value["provider"], "model provider"),
            backend_model_id=_plain_text(value["backend_model_id"], "model id"),
            display_name=_plain_text(value["display_name"], "model display name"),
            model_type=_plain_text(value["model_type"], "model type"),
            context_capacity=_optional_int(value.get("context_capacity")),
            quantization=_optional_text(value.get("quantization")),
            loaded=bool(value["loaded"]),
            vision=_optional_bool(value.get("vision")),
            trained_for_tool_use=_optional_bool(value.get("trained_for_tool_use")),
        )
    except KeyError as exc:
        raise SourceHierarchicalExtractionConfigurationError(
            "Pinned hierarchical extraction model snapshot is incomplete."
        ) from exc


def _require_object(raw_json: str | None, field_name: str) -> dict[str, Any]:
    if raw_json is None:
        raise SourceHierarchicalExtractionConfigurationError(f"{field_name} is missing.")
    try:
        value = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise SourceHierarchicalExtractionConfigurationError(
            f"{field_name} is invalid JSON."
        ) from exc
    if not isinstance(value, dict):
        raise SourceHierarchicalExtractionConfigurationError(f"{field_name} must be an object.")
    return value


def _require_uuid(value: Mapping[str, Any], field_name: str) -> uuid.UUID:
    raw = value.get(field_name)
    if not isinstance(raw, str):
        raise SourceHierarchicalExtractionConfigurationError(f"{field_name} must be a UUID string.")
    try:
        return uuid.UUID(raw)
    except ValueError as exc:
        raise SourceHierarchicalExtractionConfigurationError(
            f"{field_name} must be a UUID string."
        ) from exc


def _require_text(value: Mapping[str, Any], field_name: str) -> str:
    raw = value.get(field_name)
    if not isinstance(raw, str) or not raw.strip():
        raise SourceHierarchicalExtractionConfigurationError(f"{field_name} must be text.")
    return raw.strip()


def _require_positive_int(value: Mapping[str, Any], field_name: str) -> int:
    raw = value.get(field_name)
    if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
        raise SourceHierarchicalExtractionConfigurationError(
            f"{field_name} must be a positive integer."
        )
    return raw


def _require_nonnegative_int(value: Mapping[str, Any], field_name: str) -> int:
    raw = value.get(field_name)
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        raise SourceHierarchicalExtractionConfigurationError(
            f"{field_name} must be a non-negative integer."
        )
    return raw


def _require_number(value: Mapping[str, Any], field_name: str) -> float:
    raw = value.get(field_name)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise SourceHierarchicalExtractionConfigurationError(f"{field_name} must be numeric.")
    return float(raw)


def _require_bool(value: Mapping[str, Any], field_name: str) -> bool:
    raw = value.get(field_name)
    if not isinstance(raw, bool):
        raise SourceHierarchicalExtractionConfigurationError(f"{field_name} must be boolean.")
    return raw


def _plain_nonnegative_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SourceHierarchicalExtractionOutputError(
            f"{field_name} must be a non-negative integer."
        )
    return value


def _plain_confidence(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SourceHierarchicalExtractionOutputError("confidence must be numeric.")
    result = float(value)
    if not 0.0 <= result <= 1.0:
        raise SourceHierarchicalExtractionOutputError("confidence must be between 0 and 1.")
    return result


def _plain_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SourceHierarchicalExtractionOutputError(f"{field_name} must be non-empty text.")
    return value.strip()


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise SourceHierarchicalExtractionConfigurationError("Optional model text field is invalid.")
    return value


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise SourceHierarchicalExtractionConfigurationError("Optional model integer field is invalid.")
    return value


def _optional_bool(value: object) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise SourceHierarchicalExtractionConfigurationError("Optional model boolean field is invalid.")
    return value
