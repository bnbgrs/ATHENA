from athena.knowledge.deduplication import normalize_semantic_text


def test_normalize_semantic_text_ignores_case_whitespace_and_punctuation() -> None:
    assert normalize_semantic_text("  Berlin IST Hauptstadt. ") == "berlin ist hauptstadt"
