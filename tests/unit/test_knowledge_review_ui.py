from __future__ import annotations

from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from athena.api.contracts import (
    CanonicalMergeReviewResponse,
    ChatThreadResponse,
    DedupDecisionResponse,
    KnowledgeMergeReviewResponse,
    KnowledgeReviewResponse,
    KnowledgeUnitProposalResponse,
    MessageKnowledgeExtractionResponse,
    RememberedChatMessageResponse,
)
from athena.desktop.window import AthenaMainWindow

CHAT_ID = "11111111-1111-1111-1111-111111111111"
MESSAGE_ID = "22222222-2222-2222-2222-222222222222"
REVISION_ID = "33333333-3333-3333-3333-333333333333"
RUN_ID = "44444444-4444-4444-4444-444444444444"
SIGNATURE_ID = "55555555-5555-5555-5555-555555555555"
REVIEW_ID = "66666666-6666-6666-6666-666666666666"
EXISTING_ID = "77777777-7777-7777-7777-777777777777"
EXISTING_REVISION_ID = "88888888-8888-8888-8888-888888888888"


class _Controller:
    def __init__(self) -> None:
        self.remember_calls: list[dict[str, object]] = []
        self.extract_calls: list[dict[str, object]] = []
        self.review_runs: list[str] = []
        self.merge_calls: list[tuple[str, str]] = []

    def remember_message(self, **kwargs: object) -> None:
        self.remember_calls.append(kwargs)

    def extract_message_knowledge(self, **kwargs: object) -> None:
        self.extract_calls.append(kwargs)

    def prepare_knowledge_review(self, processing_run_id: str) -> None:
        self.review_runs.append(processing_run_id)

    def resolve_knowledge_merge_review(
        self,
        review_id: str,
        *,
        decision: str,
    ) -> None:
        self.merge_calls.append((review_id, decision))


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _extraction() -> MessageKnowledgeExtractionResponse:
    return MessageKnowledgeExtractionResponse(
        chat_id=CHAT_ID,
        message_id=MESSAGE_ID,
        message_revision_id=REVISION_ID,
        processing_run_id=RUN_ID,
        model_id="local-model",
        model_signature_id=SIGNATURE_ID,
        knowledge_units=(
            KnowledgeUnitProposalResponse(
                proposal_index=0,
                source_sequence_no=1,
                source_quote="Berlin is Germany's capital.",
                knowledge_kind="fact",
                title="German capital",
                body="Berlin is the capital of Germany.",
                epistemic_status="asserted",
                confidence=0.98,
            ),
        ),
        claims=(),
        relations=(),
        extractor_merge_candidates=(),
    )


def _review(*, merge_candidate: bool) -> KnowledgeReviewResponse:
    candidates = (
        (
            CanonicalMergeReviewResponse(
                candidate_index=0,
                review_id=REVIEW_ID,
                proposal_type="knowledge",
                proposal_index=0,
                existing_entity_id=EXISTING_ID,
                existing_revision_id=EXISTING_REVISION_ID,
                similarity=0.97,
                reason="possible textual near-duplicate of canonical Knowledge",
            ),
        )
        if merge_candidate
        else ()
    )
    return KnowledgeReviewResponse(
        processing_run_id=RUN_ID,
        model_signature_id=SIGNATURE_ID,
        ready_to_accept=not merge_candidate,
        blocked_reason="canonical_merge_candidates" if merge_candidate else None,
        preflight_digest=None if merge_candidate else "a" * 64,
        knowledge_decisions=(
            DedupDecisionResponse(
                proposal_type="knowledge",
                proposal_index=0,
                action="create",
                existing_entity_id=None,
                existing_revision_id=None,
                duplicate_of_proposal_index=None,
            ),
        ),
        claim_decisions=(),
        canonical_merge_candidates=candidates,
    )


def _arm_knowledge_review_request(
    window: AthenaMainWindow,
) -> None:
    window._knowledge_review_request = (
        CHAT_ID,
        MESSAGE_ID,
        REVISION_ID,
    )


def test_message_actions_are_stable_and_dispatch_exact_revision() -> None:
    app = _app()
    window = AthenaMainWindow(api_controller=None)
    controller = _Controller()
    try:
        window.api_controller = controller  # type: ignore[assignment]
        window.current_chat_id = CHAT_ID
        window._core_ready = True
        widget = window._message_widget(
            role="user",
            content="Berlin is Germany's capital.",
            created_at_us=1,
            sequence_no=1,
            message_id=MESSAGE_ID,
            revision_id=REVISION_ID,
        )
        window.chat_messages_layout.insertWidget(0, widget)
        window._sync_composer_enabled()

        remember = widget.findChild(QPushButton, "rememberMessageButton")
        knowledge = widget.findChild(QPushButton, "addKnowledgeButton")
        assert remember is not None
        assert knowledge is not None
        assert remember.property("messageId") == MESSAGE_ID
        assert remember.property("messageRevisionId") == REVISION_ID
        assert knowledge.property("messageId") == MESSAGE_ID
        assert knowledge.property("messageRevisionId") == REVISION_ID

        remember.click()
        knowledge.click()

        assert controller.remember_calls == [
            {
                "chat_id": CHAT_ID,
                "message_id": MESSAGE_ID,
                "revision_id": REVISION_ID,
            }
        ]
        assert controller.extract_calls == [
            {
                "chat_id": CHAT_ID,
                "message_id": MESSAGE_ID,
                "revision_id": REVISION_ID,
                "model_id": None,
                "effective_context_limit": None,
                "max_output_tokens": None,
            }
        ]
    finally:
        window.close()
        app.processEvents()


def test_remember_result_marks_exact_message_revision() -> None:
    app = _app()
    window = AthenaMainWindow(api_controller=None)
    controller = _Controller()
    try:
        window.api_controller = controller  # type: ignore[assignment]
        window.current_chat_id = CHAT_ID
        widget = window._message_widget(
            role="assistant",
            content="Persisted answer",
            created_at_us=1,
            sequence_no=1,
            message_id=MESSAGE_ID,
            revision_id=REVISION_ID,
        )
        window.chat_messages_layout.insertWidget(0, widget)

        window.apply_message_remembered(
            RememberedChatMessageResponse(
                chat_id=CHAT_ID,
                message_id=MESSAGE_ID,
                message_revision_id=REVISION_ID,
                memory_id="99999999-9999-9999-9999-999999999999",
                memory_revision_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                content="Persisted answer",
            )
        )

        remember = widget.findChild(QPushButton, "rememberMessageButton")
        assert remember is not None
        assert remember.text() == "REMEMBERED"
        assert remember.isEnabled() is False
    finally:
        window.close()
        app.processEvents()


def test_extraction_opens_review_panel_and_queues_preflight() -> None:
    app = _app()
    window = AthenaMainWindow(api_controller=None)
    controller = _Controller()
    try:
        window.api_controller = controller  # type: ignore[assignment]
        window.current_chat_id = CHAT_ID
        _arm_knowledge_review_request(window)
        window.apply_knowledge_extraction_ready(_extraction())

        assert window.knowledge_review_panel.isHidden() is False
        app.processEvents()
        labels = window.knowledge_review_panel.findChildren(QLabel)
        assert any("Berlin is the capital of Germany." in label.text() for label in labels)
        assert controller.review_runs == [RUN_ID]
    finally:
        window.close()
        app.processEvents()


def test_canonical_merge_buttons_dispatch_explicit_decision() -> None:
    app = _app()
    window = AthenaMainWindow(api_controller=None)
    controller = _Controller()
    try:
        window.api_controller = controller  # type: ignore[assignment]
        window.current_chat_id = CHAT_ID
        _arm_knowledge_review_request(window)
        window._knowledge_extraction = _extraction()
        window.apply_knowledge_review_ready(_review(merge_candidate=True))

        buttons = window.knowledge_review_panel.findChildren(
            QPushButton,
            "knowledgeMergeButton",
        )
        assert len(buttons) == 2
        merge = next(button for button in buttons if button.property("decision") == "merge")
        separate = next(
            button
            for button in buttons
            if button.property("decision") == "keep_separate"
        )
        assert merge.property("reviewId") == REVIEW_ID
        assert separate.property("reviewId") == REVIEW_ID

        merge.click()
        assert controller.merge_calls == [(REVIEW_ID, "merge")]
    finally:
        window.close()
        app.processEvents()


def test_merge_result_refreshes_same_frozen_preflight() -> None:
    app = _app()
    window = AthenaMainWindow(api_controller=None)
    controller = _Controller()
    try:
        window.api_controller = controller  # type: ignore[assignment]
        window.current_chat_id = CHAT_ID
        _arm_knowledge_review_request(window)
        window._knowledge_extraction = _extraction()
        window.apply_knowledge_merge_review_ready(
            KnowledgeMergeReviewResponse(
                review_id=REVIEW_ID,
                status="accepted",
                proposal_type="knowledge",
                proposal_index=0,
                source_entity_id=MESSAGE_ID,
                source_revision_id=REVISION_ID,
                proposal_text="Berlin is the capital of Germany.",
                proposal_kind="fact",
                proposal_epistemic_status="asserted",
                similarity=0.97,
                decision="merge",
                existing_entity_id=EXISTING_ID,
                existing_revision_id=EXISTING_REVISION_ID,
            )
        )
        app.processEvents()
        assert controller.review_runs == [RUN_ID]
    finally:
        window.close()
        app.processEvents()


def test_review_ready_does_not_expose_canonical_accept_write() -> None:
    app = _app()
    window = AthenaMainWindow(api_controller=None)
    try:
        window.current_chat_id = CHAT_ID
        _arm_knowledge_review_request(window)
        window._knowledge_extraction = _extraction()
        window.apply_knowledge_review_ready(_review(merge_candidate=False))
        assert window.knowledge_review_state.text() == "REVIEW COMPLETE / READY"
        buttons = window.knowledge_review_panel.findChildren(QPushButton)
        assert all(button.text() != "ACCEPT" for button in buttons)
    finally:
        window.close()
        app.processEvents()



def _knowledge_rerender_thread(chat_id: str) -> ChatThreadResponse:
    return ChatThreadResponse(
        chat_id=chat_id,
        started_at_us=1,
        ended_at_us=None,
        archive_mode="standard",
        lifecycle_state="active",
        messages=(),
    )


def test_same_chat_rerender_preserves_extracting_knowledge_review() -> None:
    app = _app()
    window = AthenaMainWindow(api_controller=None)
    controller = _Controller()

    try:
        window.api_controller = controller  # type: ignore[assignment]
        window.current_chat_id = CHAT_ID
        window._core_ready = True

        widget = window._message_widget(
            role="user",
            content="Berlin is Germany's capital.",
            created_at_us=1,
            sequence_no=1,
            message_id=MESSAGE_ID,
            revision_id=REVISION_ID,
        )
        window.chat_messages_layout.insertWidget(0, widget)
        window._sync_composer_enabled()

        window.show()
        app.processEvents()

        knowledge = widget.findChild(
            QPushButton,
            "addKnowledgeButton",
        )
        assert knowledge is not None
        assert knowledge.isEnabled() is True

        knowledge.click()
        app.processEvents()

        assert controller.extract_calls == [
            {
                "chat_id": CHAT_ID,
                "message_id": MESSAGE_ID,
                "revision_id": REVISION_ID,
                "model_id": None,
                "effective_context_limit": None,
                "max_output_tokens": None,
            }
        ]
        assert window._knowledge_review_chat_id == CHAT_ID
        assert window.knowledge_review_panel.isHidden() is False
        assert window.knowledge_review_panel.isVisible() is True
        assert (
            window.knowledge_review_state.text()
            == "EXTRACTING / SELECTED MESSAGE"
        )

        window.apply_chat_loaded(
            _knowledge_rerender_thread(CHAT_ID)
        )
        app.processEvents()

        assert window.current_chat_id == CHAT_ID
        assert window._knowledge_review_chat_id == CHAT_ID
        assert window.knowledge_review_panel.isHidden() is False
        assert window.knowledge_review_panel.isVisible() is True
        assert (
            window.knowledge_review_state.text()
            == "EXTRACTING / SELECTED MESSAGE"
        )
    finally:
        window.close()
        app.processEvents()


def test_same_chat_rerender_preserves_ready_knowledge_review() -> None:
    app = _app()
    window = AthenaMainWindow(api_controller=None)
    controller = _Controller()

    try:
        window.api_controller = controller  # type: ignore[assignment]
        window.current_chat_id = CHAT_ID
        _arm_knowledge_review_request(window)

        window.apply_knowledge_extraction_ready(
            _extraction()
        )
        app.processEvents()

        assert window._knowledge_review_chat_id == CHAT_ID
        assert window.knowledge_review_panel.isHidden() is False

        window.apply_knowledge_review_ready(
            _review(merge_candidate=False)
        )
        app.processEvents()

        assert (
            window.knowledge_review_state.text()
            == "REVIEW COMPLETE / READY"
        )
        assert window.knowledge_review_panel.isHidden() is False

        window.apply_chat_loaded(
            _knowledge_rerender_thread(CHAT_ID)
        )
        app.processEvents()

        assert window.current_chat_id == CHAT_ID
        assert window._knowledge_review_chat_id == CHAT_ID
        assert window._knowledge_extraction is not None
        assert window._knowledge_review is not None
        assert window.knowledge_review_panel.isHidden() is False
        assert (
            window.knowledge_review_state.text()
            == "REVIEW COMPLETE / READY"
        )
    finally:
        window.close()
        app.processEvents()


def test_different_chat_rerender_clears_knowledge_review() -> None:
    app = _app()
    window = AthenaMainWindow(api_controller=None)
    controller = _Controller()

    other_chat_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

    try:
        window.api_controller = controller  # type: ignore[assignment]
        window.current_chat_id = CHAT_ID
        _arm_knowledge_review_request(window)

        window.apply_knowledge_extraction_ready(
            _extraction()
        )
        app.processEvents()

        assert window._knowledge_review_chat_id == CHAT_ID
        assert window.knowledge_review_panel.isHidden() is False

        window.apply_chat_loaded(
            _knowledge_rerender_thread(other_chat_id)
        )
        app.processEvents()

        assert window.current_chat_id == other_chat_id
        assert window._knowledge_review_chat_id is None
        assert window._knowledge_extraction is None
        assert window._knowledge_review is None
        assert window.knowledge_review_panel.isHidden() is True
        assert window.knowledge_review_state.text() == "IDLE"
    finally:
        window.close()
        app.processEvents()



def test_dismissed_inflight_extraction_result_is_ignored() -> None:
    app = _app()
    window = AthenaMainWindow(api_controller=None)
    controller = _Controller()

    try:
        window.api_controller = controller  # type: ignore[assignment]
        window.current_chat_id = CHAT_ID
        window._core_ready = True

        widget = window._message_widget(
            role="user",
            content="Berlin is Germany's capital.",
            created_at_us=1,
            sequence_no=1,
            message_id=MESSAGE_ID,
            revision_id=REVISION_ID,
        )

        window.chat_messages_layout.insertWidget(
            0,
            widget,
        )
        window._sync_composer_enabled()

        knowledge = widget.findChild(
            QPushButton,
            "addKnowledgeButton",
        )

        assert knowledge is not None
        assert knowledge.isEnabled() is True

        knowledge.click()

        assert window._knowledge_review_request == (
            CHAT_ID,
            MESSAGE_ID,
            REVISION_ID,
        )
        assert window.knowledge_review_panel.isHidden() is False

        window._close_knowledge_review()

        assert window._knowledge_review_request is None
        assert window._knowledge_review_chat_id is None
        assert window._knowledge_extraction is None
        assert window._knowledge_review is None
        assert window.knowledge_review_panel.isHidden() is True
        assert window.knowledge_review_state.text() == "IDLE"

        window.apply_knowledge_extraction_ready(
            _extraction()
        )

        app.processEvents()

        assert window._knowledge_review_request is None
        assert window._knowledge_review_chat_id is None
        assert window._knowledge_extraction is None
        assert window._knowledge_review is None
        assert window.knowledge_review_panel.isHidden() is True
        assert window.knowledge_review_state.text() == "IDLE"
        assert controller.review_runs == []
    finally:
        window.close()
        app.processEvents()


def test_close_before_deferred_preflight_cancels_preflight() -> None:
    app = _app()
    window = AthenaMainWindow(api_controller=None)
    controller = _Controller()

    try:
        window.api_controller = controller  # type: ignore[assignment]
        window.current_chat_id = CHAT_ID
        _arm_knowledge_review_request(window)

        window.apply_knowledge_extraction_ready(
            _extraction()
        )

        assert window._knowledge_extraction is not None
        assert controller.review_runs == []

        window._close_knowledge_review()

        app.processEvents()

        assert controller.review_runs == []
        assert window._knowledge_review_request is None
        assert window._knowledge_extraction is None
        assert window._knowledge_review is None
        assert window.knowledge_review_panel.isHidden() is True
    finally:
        window.close()
        app.processEvents()


def test_dismissed_late_preflight_result_is_ignored() -> None:
    app = _app()
    window = AthenaMainWindow(api_controller=None)
    controller = _Controller()

    try:
        window.api_controller = controller  # type: ignore[assignment]
        window.current_chat_id = CHAT_ID
        _arm_knowledge_review_request(window)

        window.apply_knowledge_extraction_ready(
            _extraction()
        )
        app.processEvents()

        assert controller.review_runs == [RUN_ID]
        assert window._knowledge_extraction is not None

        window._close_knowledge_review()

        window.apply_knowledge_review_ready(
            _review(merge_candidate=False)
        )
        app.processEvents()

        assert window._knowledge_review_request is None
        assert window._knowledge_extraction is None
        assert window._knowledge_review is None
        assert window.knowledge_review_panel.isHidden() is True
        assert window.knowledge_review_state.text() == "IDLE"
    finally:
        window.close()
        app.processEvents()


def test_stale_message_revision_extraction_is_ignored() -> None:
    app = _app()
    window = AthenaMainWindow(api_controller=None)

    newer_message_id = (
        "99999999-1111-2222-3333-444444444444"
    )

    try:
        window.current_chat_id = CHAT_ID
        window._knowledge_review_request = (
            CHAT_ID,
            newer_message_id,
            REVISION_ID,
        )
        window._knowledge_review_chat_id = CHAT_ID
        window.knowledge_review_panel.setVisible(True)
        window.knowledge_review_state.setText(
            "EXTRACTING / SELECTED MESSAGE"
        )

        before_state = window.knowledge_review_state.text()

        window.apply_knowledge_extraction_ready(
            _extraction()
        )
        app.processEvents()

        assert window._knowledge_review_request == (
            CHAT_ID,
            newer_message_id,
            REVISION_ID,
        )
        assert window._knowledge_extraction is None
        assert window._knowledge_review is None
        assert window.knowledge_review_panel.isHidden() is False
        assert window.knowledge_review_state.text() == before_state
    finally:
        window.close()
        app.processEvents()


def test_dismissed_late_knowledge_failure_is_ignored() -> None:
    app = _app()
    window = AthenaMainWindow(api_controller=None)

    try:
        window.current_chat_id = CHAT_ID
        _arm_knowledge_review_request(window)
        window._knowledge_review_chat_id = CHAT_ID
        window.knowledge_review_panel.setVisible(True)
        window.knowledge_review_state.setText(
            "EXTRACTING / SELECTED MESSAGE"
        )

        window._close_knowledge_review()

        before_object = window.inspector_object_id.text()
        before_heading = window.inspector_heading.text()
        before_detail = window.connection_detail.text()

        window.apply_chat_operation_failure(
            "extract_knowledge",
            "late synthetic failure",
        )
        app.processEvents()

        assert window._knowledge_review_request is None
        assert window._knowledge_extraction is None
        assert window.knowledge_review_panel.isHidden() is True
        assert window.knowledge_review_state.text() == "IDLE"

        assert window.inspector_object_id.text() == before_object
        assert window.inspector_heading.text() == before_heading
        assert window.connection_detail.text() == before_detail
    finally:
        window.close()
        app.processEvents()


def test_new_add_to_knowledge_rearms_after_dismissal() -> None:
    app = _app()
    window = AthenaMainWindow(api_controller=None)
    controller = _Controller()

    try:
        window.api_controller = controller  # type: ignore[assignment]
        window.current_chat_id = CHAT_ID
        window._core_ready = True

        widget = window._message_widget(
            role="user",
            content="Berlin is Germany's capital.",
            created_at_us=1,
            sequence_no=1,
            message_id=MESSAGE_ID,
            revision_id=REVISION_ID,
        )

        window.chat_messages_layout.insertWidget(
            0,
            widget,
        )
        window._sync_composer_enabled()

        knowledge = widget.findChild(
            QPushButton,
            "addKnowledgeButton",
        )

        assert knowledge is not None
        assert knowledge.isEnabled() is True

        knowledge.click()

        assert window._knowledge_review_request == (
            CHAT_ID,
            MESSAGE_ID,
            REVISION_ID,
        )
        assert len(controller.extract_calls) == 1

        window._close_knowledge_review()

        assert window._knowledge_review_request is None

        knowledge.click()

        assert window._knowledge_review_request == (
            CHAT_ID,
            MESSAGE_ID,
            REVISION_ID,
        )
        assert window.knowledge_review_panel.isHidden() is False
        assert (
            window.knowledge_review_state.text()
            == "EXTRACTING / SELECTED MESSAGE"
        )
        assert len(controller.extract_calls) == 2
    finally:
        window.close()
        app.processEvents()
