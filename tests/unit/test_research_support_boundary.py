from __future__ import annotations

import ast
import inspect

from athena.research import idempotency, repository, validation

VALIDATION_HELPERS = (
    "_required_text",
    "_canonical_json_value",
    "_canonical_json_object",
    "_validated_synthesis_source_evidence",
    "_validated_synthesis_evidence",
    "_json_string_array",
)

IDEMPOTENCY_HELPERS = (
    "_synthesis_work_idempotency_key",
    "_work_idempotency_key",
)

ALL_HELPERS = VALIDATION_HELPERS + IDEMPOTENCY_HELPERS


def test_repository_reexports_research_support_boundaries() -> None:
    for name in VALIDATION_HELPERS:
        assert getattr(repository, name) is getattr(validation, name)

    for name in IDEMPOTENCY_HELPERS:
        assert getattr(repository, name) is getattr(idempotency, name)


def test_repository_no_longer_defines_research_support_helpers() -> None:
    source = inspect.getsource(repository)

    for name in ALL_HELPERS:
        assert f"def {name}(" not in source


def test_boundary_modules_own_exact_helper_sets() -> None:
    validation_functions = {
        name
        for name, value in vars(validation).items()
        if inspect.isfunction(value)
        and value.__module__ == validation.__name__
    }
    idempotency_functions = {
        name
        for name, value in vars(idempotency).items()
        if inspect.isfunction(value)
        and value.__module__ == idempotency.__name__
    }

    assert validation_functions == set(VALIDATION_HELPERS)
    assert idempotency_functions == set(IDEMPOTENCY_HELPERS)


def test_repository_uses_explicit_static_reexports() -> None:
    source = inspect.getsource(repository)
    tree = ast.parse(source)

    expected = {
        "athena.research.validation": set(VALIDATION_HELPERS),
        "athena.research.idempotency": set(IDEMPOTENCY_HELPERS),
    }

    actual: dict[str, dict[str, str | None]] = {
        module: {}
        for module in expected
    }

    for node in tree.body:
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.module not in expected:
            continue

        aliases = actual[node.module]
        for alias in node.names:
            assert alias.name not in aliases
            aliases[alias.name] = alias.asname

    for module, names in expected.items():
        assert actual[module] == {
            name: name
            for name in names
        }
