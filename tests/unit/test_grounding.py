from __future__ import annotations

import uuid

import pytest

from athena.chat.grounding import (
    GroundingContract,
    GroundingEvidenceRef,
    GroundingViolation,
    render_durable_provenance_manifest,
    render_grounding_instructions,
    validate_grounded_answer,
)


def _ref(context_id: str) -> GroundingEvidenceRef:
    return GroundingEvidenceRef(
        context_id=context_id,
        entity_type="knowledge",
        entity_id=uuid.uuid4(),
        revision_id=uuid.uuid4(),
    )


def test_grounding_accepts_context_and_inference_markers() -> None:
    contract = GroundingContract(
        evidence_refs=(_ref("CTX-001"), _ref("CTX-002")),
    )

    report = validate_grounded_answer(
        "Berlin appears in one item. [CTX-001]\n"
        "The retrieved items conflict. [INFERENCE:CTX-001,CTX-002]",
        contract=contract,
    )

    assert report.cited_context_ids == ("CTX-001", "CTX-002")
    assert report.uses_inference is True
    assert report.uses_model_prior is False
    assert report.uses_unknown is False


def test_grounding_rejects_context_id_not_supplied_by_athena() -> None:
    contract = GroundingContract(evidence_refs=(_ref("CTX-001"),))

    with pytest.raises(GroundingViolation, match="not supplied"):
        validate_grounded_answer(
            "Unsupported citation. [CTX-999]",
            contract=contract,
        )


def test_grounding_rejects_model_prior_by_default() -> None:
    contract = GroundingContract(evidence_refs=(_ref("CTX-001"),))

    with pytest.raises(GroundingViolation, match="model prior knowledge is disabled"):
        validate_grounded_answer(
            "Berlin is the official capital. [MODEL-PRIOR]",
            contract=contract,
        )


def test_grounding_can_explicitly_allow_model_prior() -> None:
    contract = GroundingContract(
        evidence_refs=(_ref("CTX-001"),),
        allow_model_prior=True,
    )

    report = validate_grounded_answer(
        "General model knowledge says Berlin. [MODEL-PRIOR]",
        contract=contract,
    )

    assert report.uses_model_prior is True
    assert report.cited_context_ids == ()


def test_grounding_requires_a_provenance_marker() -> None:
    contract = GroundingContract(evidence_refs=(_ref("CTX-001"),))

    with pytest.raises(GroundingViolation, match="no ATHENA provenance marker"):
        validate_grounded_answer(
            "Berlin is the capital of Germany.",
            contract=contract,
        )


def test_grounding_instructions_name_only_allowed_context_ids() -> None:
    contract = GroundingContract(
        evidence_refs=(_ref("CTX-001"), _ref("CTX-002")),
        allow_model_prior=False,
    )

    rendered = render_grounding_instructions(contract)

    assert "Allowed context IDs: CTX-001, CTX-002." in rendered
    assert "[MODEL-PRIOR] is forbidden" in rendered
    assert "Every factual sentence, bullet, or table row" in rendered


def test_durable_manifest_maps_ctx_to_stable_entity_and_revision() -> None:
    evidence = _ref("CTX-001")
    contract = GroundingContract(evidence_refs=(evidence,))
    report = validate_grounded_answer(
        "Stored fact. [CTX-001]",
        contract=contract,
    )

    manifest = render_durable_provenance_manifest(
        contract=contract,
        report=report,
    )

    assert manifest.startswith("\n\nATHENA_PROVENANCE ")
    assert '"context_id":"CTX-001"' in manifest
    assert f'"entity_id":"{evidence.entity_id}"' in manifest
    assert f'"revision_id":"{evidence.revision_id}"' in manifest


def test_unknown_is_valid_when_no_evidence_exists() -> None:
    contract = GroundingContract(evidence_refs=())

    report = validate_grounded_answer(
        "ATHENA has no retrieved evidence for this question. [UNKNOWN]",
        contract=contract,
    )

    assert report.uses_unknown is True
    assert report.cited_context_ids == ()


def test_malformed_inference_marker_is_rejected() -> None:
    contract = GroundingContract(evidence_refs=(_ref("CTX-001"),))

    with pytest.raises(GroundingViolation, match="comma-separated"):
        validate_grounded_answer(
            "Inference. [INFERENCE:CTX-001,external]",
            contract=contract,
        )
