"""Presentation helpers for the ATHENA command-line interface."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from athena.chat.models import ChatThread
    from athena.core.application import AthenaApplication
    from athena.jobs.embedding_processing import EmbeddingRebuildStepResult
    from athena.jobs.models import JobRecord
    from athena.jobs.scheduler import SchedulerRunResult, SchedulerTickResult
    from athena.jobs.source_analysis import SourceAnalysisStepResult
    from athena.jobs.source_extraction import SourceHierarchicalExtractionStepResult
    from athena.jobs.source_processing import SourceProcessingStepResult
    from athena.knowledge.extraction_models import ChatExtractionResult
    from athena.knowledge.models import ClaimSnapshot, KnowledgeUnitSnapshot
    from athena.knowledge.source_extraction import SourceAnalysisExtractionResult
    from athena.memory.models import PersonalMemorySnapshot
    from athena.source.models import (
        BlobRecord,
        SourceAnchorRecord,
        SourceRecord,
        SourceRepresentationRecord,
    )


def _print_paths(app: AthenaApplication) -> None:
    print(f"Local root: {app.paths.local_root}")
    print(f"State root: {app.paths.state_root}")
    print(f"Database: {app.paths.database_path}")
    print(f"Spool root: {app.paths.spool_root}")
    print(f"Derived root: {app.paths.derived_root}")
    print(f"Log root: {app.paths.log_root}")
    print(f"Temp root: {app.paths.temp_root}")
    print(
        "Archive root: "
        + (str(app.paths.archive_root) if app.paths.archive_root else "<unset>")
    )
    print(
        "Backup root: "
        + (str(app.paths.backup_root) if app.paths.backup_root else "<unset>")
    )
    print(
        "Projection root: "
        + (str(app.paths.projection_root) if app.paths.projection_root else "<unset>")
    )

def _print_chat(thread: ChatThread) -> None:
    print(f"Chat: {thread.chat_id}")
    print(f"State: {thread.lifecycle_state}")
    print(f"Archive mode: {thread.archive_mode}")
    print(f"Messages: {len(thread.messages)}")
    for message in thread.messages:
        content = message.content if message.content is not None else "<protected>"
        print(f"[{message.sequence_no}] {message.message_type.value}: {content}")

def _print_knowledge(app: AthenaApplication, snapshot: KnowledgeUnitSnapshot) -> None:
    revision = snapshot.revision
    payload = revision.payload
    print(f"Knowledge: {snapshot.knowledge_id}")
    print(f"State: {snapshot.lifecycle_state}")
    print(f"Revision: {revision.revision_no} ({revision.revision_id})")
    print(f"Kind: {payload.knowledge_kind.value}")
    print(f"Status: {payload.epistemic_status.value}")
    print(f"Title: {payload.title if payload.title is not None else '<none>'}")
    print(f"Body: {payload.body}")
    inputs = app.knowledge.provenance_inputs(revision.provenance_id)
    print(f"Provenance inputs: {len(inputs)}")
    for item in inputs:
        revision_text = (
            str(item.input_revision_id)
            if item.input_revision_id is not None
            else "<entity-only>"
        )
        print(
            f"[{item.ordinal}] role={item.input_role} "
            f"entity={item.input_entity_id} revision={revision_text}"
        )

def _print_claim(app: AthenaApplication, snapshot: ClaimSnapshot) -> None:
    revision = snapshot.revision
    payload = revision.payload
    print(f"Claim: {snapshot.claim_id}")
    print(f"State: {snapshot.lifecycle_state}")
    print(f"Revision: {revision.revision_no} ({revision.revision_id})")
    print(f"Kind: {payload.claim_kind.value}")
    print(f"Status: {payload.epistemic_status.value}")
    print(f"Statement: {payload.statement}")
    print(f"Valid from us: {payload.valid_from_us if payload.valid_from_us is not None else '<open>'}")
    print(f"Valid to us: {payload.valid_to_us if payload.valid_to_us is not None else '<open>'}")
    inputs = app.claims.provenance_inputs(revision.provenance_id)
    print(f"Provenance inputs: {len(inputs)}")
    for item in inputs:
        revision_text = (
            str(item.input_revision_id)
            if item.input_revision_id is not None
            else "<entity-only>"
        )
        print(
            f"[{item.ordinal}] role={item.input_role} "
            f"entity={item.input_entity_id} revision={revision_text}"
        )
    evidence = app.claims.evidence(snapshot.claim_id)
    print(f"Evidence links: {len(evidence)}")
    for index, evidence_item in enumerate(evidence):
        print(
            f"[{index}] role={evidence_item.evidence_role.value} "
            f"message={evidence_item.message_id if evidence_item.message_id is not None else '<none>'} "
            f"entity={evidence_item.evidence_entity_id if evidence_item.evidence_entity_id is not None else '<none>'} "
            f"revision={evidence_item.evidence_revision_id if evidence_item.evidence_revision_id is not None else '<none>'}"
        )

def _print_personal_memory(snapshot: PersonalMemorySnapshot) -> None:
    revision = snapshot.revision
    payload = revision.payload
    scope = payload.scope_kind.value
    if payload.scope_entity_id is not None:
        scope = f"{scope}:{payload.scope_entity_id}"
    print(f"Memory: {snapshot.memory_id}")
    print(f"Lifecycle: {snapshot.lifecycle_state}")
    print(f"Revision: {revision.revision_no} ({revision.revision_id})")
    print(f"Kind: {payload.memory_kind.value}")
    print(f"Scope: {scope}")
    print(f"Learning mode: {payload.learning_mode.value}")
    print(f"Sensitivity: {payload.sensitivity.value}")
    print(f"Last confirmed us: {payload.last_confirmed_at_us}")
    print(f"Provenance: {revision.provenance_id}")
    print(f"Content: {payload.content}")

def _print_extraction(result: ChatExtractionResult) -> None:
    proposals = result.proposals
    print(f"Extraction run: {result.processing_run.processing_run_id}")
    print(f"Run status: {result.processing_run.status}")
    print(f"Model: {result.model.backend_model_id}")
    print(f"Model signature: {result.model_signature.model_signature_id}")
    print(f"Knowledge proposals: {len(proposals.knowledge_units)}")
    for index, proposal in enumerate(proposals.knowledge_units):
        title = proposal.title if proposal.title is not None else "<none>"
        print(
            f"[K{index}] source=[{proposal.source_sequence_no}] "
            f"kind={proposal.knowledge_kind.value} "
            f"status={proposal.epistemic_status.value} "
            f"confidence={proposal.confidence:.3f} title={title} "
            f"quote={proposal.source_quote!r} body={proposal.body}"
        )
    print(f"Claim proposals: {len(proposals.claims)}")
    for index, claim_proposal in enumerate(proposals.claims):
        print(
            f"[C{index}] source=[{claim_proposal.source_sequence_no}] "
            f"kind={claim_proposal.claim_kind.value} "
            f"status={claim_proposal.epistemic_status.value} "
            f"confidence={claim_proposal.confidence:.3f} "
            f"quote={claim_proposal.source_quote!r} "
            f"statement={claim_proposal.statement}"
        )
    print(f"Relation proposals: {len(proposals.relations)}")
    for index, relation in enumerate(proposals.relations):
        print(
            f"[R{index}] {relation.left_type.value}[{relation.left_index}] "
            f"--{relation.relation_type}--> "
            f"{relation.right_type.value}[{relation.right_index}] "
            f"confidence={relation.confidence:.3f}"
        )
    print(f"Merge candidates: {len(proposals.merge_candidates)}")
    for index, candidate in enumerate(proposals.merge_candidates):
        print(
            f"[M{index}] {candidate.proposal_type.value}[{candidate.proposal_index}] "
            f"confidence={candidate.confidence:.3f} reason={candidate.reason}"
        )
    print("Canonical writes: 0 (proposal-only)")

def _print_source_extraction(result: SourceAnalysisExtractionResult) -> None:
    proposals = result.proposals
    evidence = {item.sequence_no: item for item in result.evidence}
    print(f"Source extraction run: {result.processing_run.processing_run_id}")
    print(f"Analysis: {result.analysis_id}")
    print(f"Final artifact: {result.final_artifact_id}")
    print(f"Model: {result.model.backend_model_id}")
    print(f"Model signature: {result.model_signature.model_signature_id}")
    print(f"Evidence anchors: {len(result.evidence)}")
    print(f"Knowledge proposals: {len(proposals.knowledge_units)}")
    for index, knowledge_proposal in enumerate(proposals.knowledge_units):
        title = knowledge_proposal.title if knowledge_proposal.title is not None else "<none>"
        anchor_id = evidence[knowledge_proposal.source_sequence_no].anchor_id
        print(
            f"[K{index}] evidence=[{knowledge_proposal.source_sequence_no}] anchor={anchor_id} "
            f"kind={knowledge_proposal.knowledge_kind.value} "
            f"status={knowledge_proposal.epistemic_status.value} "
            f"confidence={knowledge_proposal.confidence:.3f} title={title} "
            f"quote={knowledge_proposal.source_quote!r} body={knowledge_proposal.body}"
        )
    print(f"Claim proposals: {len(proposals.claims)}")
    for index, claim_proposal in enumerate(proposals.claims):
        anchor_id = evidence[claim_proposal.source_sequence_no].anchor_id
        print(
            f"[C{index}] evidence=[{claim_proposal.source_sequence_no}] anchor={anchor_id} "
            f"kind={claim_proposal.claim_kind.value} "
            f"status={claim_proposal.epistemic_status.value} "
            f"confidence={claim_proposal.confidence:.3f} quote={claim_proposal.source_quote!r} "
            f"statement={claim_proposal.statement}"
        )
    print(f"Relation proposals: {len(proposals.relations)}")
    for index, relation in enumerate(proposals.relations):
        print(
            f"[R{index}] {relation.left_type.value}[{relation.left_index}] "
            f"--{relation.relation_type}--> "
            f"{relation.right_type.value}[{relation.right_index}] "
            f"confidence={relation.confidence:.3f}"
        )
    print("Canonical writes: 0 (proposal-only)")

def _print_review_item(item: object) -> None:
    from athena.knowledge.review_service import ReviewItem

    if not isinstance(item, ReviewItem):
        raise TypeError("Expected ReviewItem.")
    print(f"Review: {item.review_id}")
    print(f"Type: {item.review_type}")
    print(f"Status: {item.status.value}")
    print(f"Confidence: {item.confidence:.3f}")
    print(f"Reason: {item.reason}")
    print(f"ProcessingRun: {item.processing_run_id}")
    print(f"ModelSignature: {item.model_signature_id}")
    print(f"Left: {item.left_entity_id} revision={item.left_revision_id}")
    print(f"Right: {item.right_entity_id} revision={item.right_revision_id}")
    if item.decision_actor_id is not None:
        print(f"Decision actor: {item.decision_actor_id}")
    if item.decision_reason is not None:
        print(f"Decision reason: {item.decision_reason}")

def _print_source_anchor(anchor: SourceAnchorRecord) -> None:
    print(f"SourceAnchor: {anchor.anchor_id}")
    print(f"Source: {anchor.source_id}")
    print(f"Representation: {anchor.representation_id}")
    print(f"Type: {anchor.anchor_type.value}")
    print(f"Range: {anchor.start_offset}:{anchor.end_offset}")
    page_value = (
        "<none>"
        if anchor.page_start is None or anchor.page_end is None
        else (str(anchor.page_start) if anchor.page_start == anchor.page_end else f"{anchor.page_start}:{anchor.page_end}")
    )
    print(f"Page: {page_value}")
    print(f"Quoted SHA-256: {anchor.quoted_hash.hex() if anchor.quoted_hash else '<none>'}")

def _print_source_record(source: SourceRecord, blob: BlobRecord) -> None:
    print(f"Source: {source.source_id}")
    print(f"State: {source.lifecycle_state.value}")
    print(f"Type: {source.source_type.value}")
    print(f"Original name: {source.original_name or '<unknown>'}")
    print(f"MIME: {source.mime_type or '<unknown>'}")
    print(f"Bytes: {blob.byte_length}")
    print(f"SHA-256: {source.content_sha256.hex()}")
    print(f"Blob: {blob.blob_id}")
    print(f"Storage: {blob.storage_area.value}:{blob.storage_locator}")
    print(f"Source URI: {source.source_uri or '<unknown>'}")
    print(f"Provenance: {source.provenance_id}")

def _print_source_representation_record(
    representation: SourceRepresentationRecord,
    blob: BlobRecord,
) -> None:
    print(f"Representation: {representation.representation_id}")
    print(f"Source: {representation.source_id}")
    print(f"Type: {representation.representation_type.value}")
    print(f"Retention: {representation.retention_state.value}")
    print(f"MIME: {representation.media_type}")
    print(f"Bytes: {blob.byte_length}")
    print(f"SHA-256: {representation.content_hash.hex()}")
    print(f"Blob: {blob.blob_id}")
    print(f"Storage: {blob.storage_area.value}:{blob.storage_locator}")
    print(
        f"Parser: {representation.parser_id}@{representation.parser_version}"
    )
    print(f"Options: {representation.options_json}")
    print(f"ProcessingRun: {representation.processing_run_id}")
    print(f"Provenance: {representation.provenance_id}")

def _print_job(job: JobRecord) -> None:
    print(f"Job: {job.job_id}")
    print(f"URI: {job.uri}")
    print(f"Type: {job.job_type}")
    print(f"State: {job.state.value}")
    print(f"Priority: {int(job.priority)}")
    print(f"Stage: {job.current_stage or '<none>'}")
    print(f"Checkpoint: {job.last_checkpoint_id or '<none>'}")
    print(f"Retry count: {job.retry_count}")
    print(f"Blocked reason: {job.blocked_reason or '<none>'}")
    print(f"Worker: {job.worker_id or '<none>'}")
    print(f"Lease expires us: {job.lease_expires_at_us or '<none>'}")
    print(f"Fencing sequence: {job.fencing_sequence}")
    print(f"Scope: {job.requested_scope_json or '<none>'}")
    print(f"Pinned config: {job.pinned_configuration_json or '<none>'}")

def _print_source_processing_result(result: SourceProcessingStepResult) -> None:
    print(f"Source processing job: {result.job.job_id}")
    print(f"State: {result.job.state.value}")
    print(f"Completed stage: {result.completed_stage or '<none>'}")
    print(f"Checkpoint: {result.checkpoint.checkpoint_id if result.checkpoint else '<none>'}")
    print(f"Representation: {result.representation_id or '<none>'}")
    print(f"Chunks: {result.chunk_count if result.chunk_count is not None else '<none>'}")
    print(f"Done: {result.done}")

def _print_source_analysis_result(result: SourceAnalysisStepResult) -> None:
    print(f"Source analysis job: {result.job.job_id}")
    print(f"State: {result.job.state.value}")
    print(f"Completed stage: {result.completed_stage or '<none>'}")
    print(f"Checkpoint: {result.checkpoint.checkpoint_id if result.checkpoint else '<none>'}")
    print(f"Analysis: {result.analysis.analysis_id if result.analysis else '<none>'}")
    if result.analysis is not None:
        print(f"Coverage: {result.analysis.coverage:.6f}")
        print(
            "Map units: "
            f"{result.analysis.completed_map_units}/{result.analysis.total_map_units} "
            f"failed={result.analysis.failed_map_units}"
        )
        print(f"Final artifact: {result.analysis.final_artifact_id or '<none>'}")
    print(f"Artifact: {result.artifact_id or '<none>'}")
    print(f"Waiting: {result.waiting}")
    print(f"Done: {result.done}")

def _print_source_extraction_job_result(
    result: SourceHierarchicalExtractionStepResult,
) -> None:
    print(f"Source extraction job: {result.job.job_id}")
    print(f"State: {result.job.state.value}")
    print(f"Completed stage: {result.completed_stage or '<none>'}")
    print(f"Checkpoint: {result.checkpoint.checkpoint_id if result.checkpoint else '<none>'}")
    print(f"Extraction: {result.extraction.extraction_id if result.extraction else '<none>'}")
    if result.extraction is not None:
        print(
            "Batches: "
            f"{result.extraction.completed_batches}/{result.extraction.total_batches} "
            f"failed={result.extraction.failed_batches}"
        )
        print(f"Final artifact: {result.extraction.final_work_artifact_id or '<none>'}")
    print(f"Artifact: {result.artifact_id or '<none>'}")
    print(f"Waiting: {result.waiting}")
    print(f"Done: {result.done}")

def _print_embedding_rebuild_result(result: EmbeddingRebuildStepResult) -> None:
    print(f"Embedding rebuild job: {result.job.job_id}")
    print(f"State: {result.job.state.value}")
    print(f"Completed stage: {result.completed_stage or '<none>'}")
    print(f"Checkpoint: {result.checkpoint.checkpoint_id if result.checkpoint else '<none>'}")
    print(f"Model: {result.model_id}")
    print(f"Target chunk generation: {result.target_chunk_generation}")
    print(
        "Documents: "
        f"{result.indexed_document_count}/{result.total_document_count}"
    )
    print(f"Dimensions: {result.dimensions if result.dimensions is not None else '<none>'}")
    print(f"Waiting: {result.waiting}")
    print(f"Done: {result.done}")

def _print_scheduler_tick(result: SchedulerTickResult) -> None:
    print(f"Scheduler action: {result.action}")
    print(f"Recovered jobs: {result.recovered_jobs}")
    print(f"Scheduled retries: {result.scheduled_retries}")
    print(f"Woken jobs: {result.woken_jobs}")
    print(f"Job: {result.selected_job_id or '<none>'}")
    print(f"Type: {result.selected_job_type or '<none>'}")
    print(f"State: {result.final_state.value if result.final_state else '<none>'}")
    print(f"Fencing sequence: {result.fencing_sequence or '<none>'}")
    print(f"Retry at us: {result.retry_at_us or '<none>'}")

def _print_scheduler_run(result: SchedulerRunResult) -> None:
    print(f"Scheduler ticks: {result.ticks}")
    print(f"Dispatched jobs: {result.dispatched_jobs}")
    print(f"Completed jobs: {result.completed_jobs}")
    print(f"Waiting jobs: {result.waiting_jobs}")
    print(f"Failed jobs: {result.failed_jobs}")
    print(f"Yielded jobs: {result.yielded_jobs}")
    print(f"Idle: {result.idle}")
