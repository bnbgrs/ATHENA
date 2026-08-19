from __future__ import annotations

import ast
import inspect
import pickle

from athena.storage import schema, schema_error_sanitization

_MOVED_NAMES = (
    "_PERSISTED_ERROR_CODE_RE",
    "_PERSISTED_ERROR_SCALAR_FIELDS",
    "_PERSISTED_ERROR_CHECKPOINT_JOB_TYPES",
    "_sanitize_persisted_error_value",
    "_sanitize_checkpoint_error_payload",
    "_canonical_migration_json",
)

_MOVED_FUNCTIONS = (
    "_sanitize_persisted_error_value",
    "_sanitize_checkpoint_error_payload",
    "_canonical_migration_json",
)


def test_schema_reexports_error_sanitization_support() -> None:
    for name in _MOVED_NAMES:
        assert getattr(schema, name) is getattr(
            schema_error_sanitization,
            name,
        )


def test_moved_functions_preserve_historical_module_identity() -> None:
    for name in _MOVED_FUNCTIONS:
        function = getattr(schema, name)

        assert function.__module__ == "athena.storage.schema"
        assert pickle.loads(
            pickle.dumps(function, protocol=5)
        ) is function


def test_schema_no_longer_defines_error_sanitization_support() -> None:
    source = inspect.getsource(schema)
    tree = ast.parse(source)

    assignments = {
        target.id
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    functions = {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }

    assert "_PERSISTED_ERROR_CODE_RE" not in assignments
    assert "_PERSISTED_ERROR_SCALAR_FIELDS" not in assignments
    assert (
        "_PERSISTED_ERROR_CHECKPOINT_JOB_TYPES"
        not in assignments
    )

    for name in _MOVED_FUNCTIONS:
        assert name not in functions


def test_error_sanitization_boundary_has_no_schema_import_cycle() -> None:
    source = inspect.getsource(schema_error_sanitization)
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "athena.storage.schema"
                assert not alias.name.startswith(
                    "athena.storage.schema."
                )

        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert module != "athena.storage.schema"
            assert not module.startswith(
                "athena.storage.schema."
            )


def test_error_sanitization_contract_is_stable() -> None:
    assert schema._sanitize_persisted_error_value("") is None
    assert schema._sanitize_persisted_error_value("   ") is None
    assert (
        schema._sanitize_persisted_error_value(
            "ProviderTimeout"
        )
        == "ProviderTimeout"
    )
    assert (
        schema._sanitize_persisted_error_value(
            "ProviderTimeout: secret detail"
        )
        == "ProviderTimeout"
    )
    assert (
        schema._sanitize_persisted_error_value(
            "free text containing secret"
        )
        == "OperationalError"
    )
