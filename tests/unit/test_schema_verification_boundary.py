from __future__ import annotations

import ast
import inspect
import pickle

from athena.storage import schema, schema_verification

_EXPECTED_VERIFIERS = ('_verify_schema_v15', '_verify_schema_v16', '_verify_schema_v17', '_verify_schema_v18', '_verify_schema_v19', '_verify_schema_v20', '_verify_schema_v21', '_verify_schema_v22', '_verify_schema_v23', '_verify_schema_v24', '_verify_schema_v24_compatible', '_verify_schema_v25', '_verify_schema_v26', '_verify_schema_v27', '_verify_schema_v28', '_verify_schema_v29', '_verify_schema_v30', '_verify_schema_v31', '_verify_schema_v31_compatible', '_verify_schema_v32', '_verify_schema_v33', '_verify_schema_v34', '_verify_schema_v35', '_verify_schema_v36', '_verify_schema_v37', '_verify_schema_v38', '_verify_schema_v39', '_verify_schema_v40')


def test_schema_reexports_all_verifiers() -> None:
    assert _EXPECTED_VERIFIERS

    for name in _EXPECTED_VERIFIERS:
        assert getattr(schema, name) is getattr(
            schema_verification,
            name,
        )


def test_verifiers_preserve_historical_module_identity() -> None:
    for name in _EXPECTED_VERIFIERS:
        verifier = getattr(schema, name)

        assert verifier.__module__ == "athena.storage.schema"
        assert pickle.loads(
            pickle.dumps(verifier, protocol=5)
        ) is verifier


def test_schema_no_longer_defines_verifier_implementation() -> None:
    source = inspect.getsource(schema)
    tree = ast.parse(source)

    defined = {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name.startswith("_verify_schema_")
    }

    assert not defined


def test_verification_boundary_has_no_schema_import_cycle() -> None:
    source = inspect.getsource(schema_verification)
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


def test_verification_boundary_has_exact_expected_verifier_set() -> None:
    actual = tuple(
        sorted(
            name
            for name, value in vars(
                schema_verification
            ).items()
            if (
                name.startswith("_verify_schema_")
                and inspect.isfunction(value)
            )
        )
    )

    assert actual == _EXPECTED_VERIFIERS
