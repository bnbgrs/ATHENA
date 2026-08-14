from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _method_source(path: str, class_name: str, method_name: str) -> str:
    source = (ROOT / path).read_text(encoding="utf-8")
    tree = ast.parse(source)
    cls = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    method = next(
        node for node in cls.body
        if isinstance(node, ast.FunctionDef) and node.name == method_name
    )
    result = ast.get_source_segment(source, method)
    assert result is not None
    return result


def test_legacy_chat_entrypoint_cannot_call_provider_without_package() -> None:
    send = _method_source(
        "src/athena/chat/generation.py",
        "ChatGenerationService",
        "send_message",
    )
    grounded = _method_source(
        "src/athena/chat/generation.py",
        "ChatGenerationService",
        "_send_grounded_context_package",
    )
    assert "self._generate_and_persist(" not in send
    assert "DirectChatService" in send
    assert "_send_grounded_context_package(" in send
    assert "self.send_context_package(" in grounded
    assert "Retrieved context without durable grounding references" in send


def test_chat_and_source_extraction_calls_are_context_packaged() -> None:
    chat = (ROOT / "src/athena/knowledge/extraction_service.py").read_text(encoding="utf-8")
    source = (ROOT / "src/athena/knowledge/source_extraction.py").read_text(encoding="utf-8")
    for text in (chat, source):
        assert text.count("messages=package.model_messages()") >= 2
        assert text.count("context_package\": package.run_snapshot()") >= 2
        assert "immediately-before" in text
        assert "immediately-after" in text
    assert 'run_type="knowledge_extraction_claim_audit"' in chat
    assert 'run_type="source_knowledge_extraction_claim_audit"' in source
