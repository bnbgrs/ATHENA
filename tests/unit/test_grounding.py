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
from athena.retrieval.evidence import EvidenceClass


def _ref(
    context_id: str,
    evidence_class: EvidenceClass = EvidenceClass.CANONICAL,
) -> GroundingEvidenceRef:
    return GroundingEvidenceRef(
        context_id=context_id,
        entity_type="knowledge" if evidence_class is EvidenceClass.CANONICAL else "chat_message",
        entity_id=uuid.uuid4(),
        revision_id=uuid.uuid4(),
        evidence_class=evidence_class,
    )


def test_grounding_accepts_canonical_context_and_inference_markers() -> None:
    contract = GroundingContract(
        evidence_refs=(_ref("CTX-001"), _ref("CTX-002")),
    )

    report = validate_grounded_answer(
        "Berlin appears in one item. [CTX-001]\n"
        "The retrieved items conflict. [INFERENCE:CTX-001,CTX-002]",
        contract=contract,
    )

    assert report.cited_context_ids == ("CTX-001", "CTX-002")
    assert report.canonical_context_ids == ("CTX-001", "CTX-002")
    assert report.uses_inference is True
    assert report.uses_model_prior is False
    assert report.uses_unknown is False


def test_grounding_accepts_typed_user_statement_marker() -> None:
    contract = GroundingContract(
        evidence_refs=(_ref("CTX-001", EvidenceClass.USER_STATEMENT),)
    )

    report = validate_grounded_answer(
        "The user previously said their car is a Volvo. "
        "[USER-STATEMENT:CTX-001]",
        contract=contract,
    )

    assert report.user_statement_context_ids == ("CTX-001",)
    assert report.canonical_context_ids == ()


def test_grounding_accepts_typed_conversation_marker() -> None:
    contract = GroundingContract(
        evidence_refs=(_ref("CTX-004", EvidenceClass.CONVERSATION_RECORD),)
    )

    report = validate_grounded_answer(
        "A prior assistant message said Berlin is the capital. "
        "[CONVERSATION:CTX-004]",
        contract=contract,
    )

    assert report.conversation_context_ids == ("CTX-004",)
    assert report.canonical_context_ids == ()


def test_grounding_rejects_conversation_record_as_canonical_evidence() -> None:
    contract = GroundingContract(
        evidence_refs=(_ref("CTX-004", EvidenceClass.CONVERSATION_RECORD),)
    )

    with pytest.raises(GroundingViolation, match="cannot use the canonical"):
        validate_grounded_answer(
            "Berlin is officially the capital. [CTX-004]",
            contract=contract,
        )


def test_grounding_rejects_user_statement_as_canonical_evidence() -> None:
    contract = GroundingContract(
        evidence_refs=(_ref("CTX-001", EvidenceClass.USER_STATEMENT),)
    )

    with pytest.raises(GroundingViolation, match="cannot use the canonical"):
        validate_grounded_answer(
            "The Earth is flat. [CTX-001]",
            contract=contract,
        )


def test_grounding_rejects_wrong_typed_marker() -> None:
    contract = GroundingContract(evidence_refs=(_ref("CTX-001"),))

    with pytest.raises(GroundingViolation, match="not user_statement"):
        validate_grounded_answer(
            "The user said this. [USER-STATEMENT:CTX-001]",
            contract=contract,
        )


def test_grounding_rejects_context_id_not_supplied_by_athena() -> None:
    contract = GroundingContract(evidence_refs=(_ref("CTX-001"),))

    with pytest.raises(GroundingViolation, match="not supplied"):
        validate_grounded_answer(
            "Unsupported citation. [CTX-999]",
            contract=contract,
        )


def test_grounding_allows_model_prior_by_default() -> None:
    contract = GroundingContract(evidence_refs=(_ref("CTX-001"),))

    report = validate_grounded_answer(
        "General model knowledge says Berlin. [MODEL-PRIOR]",
        contract=contract,
    )

    assert report.uses_model_prior is True
    assert report.cited_context_ids == ()


def test_grounding_can_explicitly_disable_model_prior() -> None:
    contract = GroundingContract(
        evidence_refs=(_ref("CTX-001"),),
        allow_model_prior=False,
    )

    with pytest.raises(GroundingViolation, match="model prior knowledge is disabled"):
        validate_grounded_answer(
            "Berlin is the official capital. [MODEL-PRIOR]",
            contract=contract,
        )


def test_grounding_requires_a_provenance_marker() -> None:
    contract = GroundingContract(evidence_refs=(_ref("CTX-001"),))

    with pytest.raises(GroundingViolation, match="no ATHENA provenance marker"):
        validate_grounded_answer(
            "Berlin is the capital of Germany.",
            contract=contract,
        )


def test_grounding_instructions_explain_typed_roles_and_model_prior() -> None:
    contract = GroundingContract(
        evidence_refs=(
            _ref("CTX-001"),
            _ref("CTX-002", EvidenceClass.USER_STATEMENT),
            _ref("CTX-003", EvidenceClass.CONVERSATION_RECORD),
        ),
    )

    rendered = render_grounding_instructions(contract)

    assert "Allowed context IDs: CTX-001, CTX-002, CTX-003." in rendered
    assert "CTX-001=canonical" in rendered
    assert "CTX-002=user_statement" in rendered
    assert "CTX-003=conversation_record" in rendered
    assert "[MODEL-PRIOR]" in rendered
    assert "self-confirm an earlier model answer" in rendered


def test_durable_manifest_maps_ctx_to_stable_entity_revision_and_class() -> None:
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
    assert '"athena_provenance_version":2' in manifest
    assert '"context_id":"CTX-001"' in manifest
    assert '"evidence_class":"canonical"' in manifest
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


def test_grounding_rejects_uncited_substantive_followup_line() -> None:
    contract = GroundingContract(
        evidence_refs=(_ref("CTX-001"), _ref("CTX-002")),
    )

    with pytest.raises(GroundingViolation, match="without provenance markers"):
        validate_grounded_answer(
            "The retrieved items conflict. [INFERENCE:CTX-001,CTX-002]\n\n"
            "The conflict could reflect historical periods or alternative perspectives.",
            contract=contract,
        )


def test_grounding_accepts_heading_without_marker_but_requires_body_marker() -> None:
    contract = GroundingContract(evidence_refs=(_ref("CTX-001"),))

    report = validate_grounded_answer(
        "### Summary\n\nBerlin is one retrieved answer. [CTX-001]",
        contract=contract,
    )

    assert report.canonical_context_ids == ("CTX-001",)


def test_grounding_requires_provenance_on_each_bullet() -> None:
    contract = GroundingContract(
        evidence_refs=(_ref("CTX-001"), _ref("CTX-002")),
    )

    with pytest.raises(GroundingViolation, match="without provenance markers"):
        validate_grounded_answer(
            "- Berlin is one claim. [CTX-001]\n"
            "- Munich is another claim.",
            contract=contract,
        )


def test_grounding_requires_bracketed_marker_in_each_table_data_row() -> None:
    contract = GroundingContract(
        evidence_refs=(_ref("CTX-001"), _ref("CTX-002")),
    )

    with pytest.raises(GroundingViolation, match="without provenance markers"):
        validate_grounded_answer(
            "| Source | Claim |\n"
            "| --- | --- |\n"
            "| [CTX-001] | Berlin |\n"
            "| CTX-002 | Munich |",
            contract=contract,
        )


def test_grounding_accepts_table_rows_with_full_markers() -> None:
    contract = GroundingContract(
        evidence_refs=(_ref("CTX-001"), _ref("CTX-002")),
    )

    report = validate_grounded_answer(
        "| Source | Claim |\n"
        "| --- | --- |\n"
        "| [CTX-001] | Berlin |\n"
        "| [CTX-002] | Munich |",
        contract=contract,
    )

    assert report.canonical_context_ids == ("CTX-001", "CTX-002")


def test_grounding_rejects_bare_ctx_even_when_line_has_another_marker() -> None:
    contract = GroundingContract(
        evidence_refs=(_ref("CTX-001"), _ref("CTX-002")),
    )

    with pytest.raises(GroundingViolation, match="bare CTX identifiers"):
        validate_grounded_answer(
            "Source CTX-002 conflicts with Berlin. [CTX-001]",
            contract=contract,
        )
