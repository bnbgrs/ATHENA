from __future__ import annotations

import ast
import inspect
import pickle

from athena.storage import schema, schema_evolution

_EXPECTED_EVOLUTION_FUNCTIONS = ('_create_schema_v1', '_migrate_schema_v10_to_v11', '_migrate_schema_v11_to_v12', '_migrate_schema_v12_to_v13', '_migrate_schema_v13_to_v14', '_migrate_schema_v14_to_v15', '_migrate_schema_v15_to_v16', '_migrate_schema_v16_to_v17', '_migrate_schema_v17_to_v18', '_migrate_schema_v18_to_v19', '_migrate_schema_v19_to_v20', '_migrate_schema_v1_to_v2', '_migrate_schema_v20_to_v21', '_migrate_schema_v21_to_v22', '_migrate_schema_v22_to_v23', '_migrate_schema_v23_to_v24', '_migrate_schema_v24_to_v25', '_migrate_schema_v28_to_v29', '_migrate_schema_v2_to_v3', '_migrate_schema_v30_to_v31', '_migrate_schema_v31_to_v32', '_migrate_schema_v32_to_v33', '_migrate_schema_v33_to_v34', '_migrate_schema_v34_to_v35', '_migrate_schema_v35_to_v36', '_migrate_schema_v36_to_v37', '_migrate_schema_v38_to_v39', '_migrate_schema_v39_to_v40', '_migrate_schema_v3_to_v4', '_migrate_schema_v4_to_v5', '_migrate_schema_v5_to_v6', '_migrate_schema_v6_to_v7', '_migrate_schema_v7_to_v8', '_migrate_schema_v8_to_v9', '_migrate_schema_v9_to_v10')

_COMPATIBILITY_RETAINED_FUNCTIONS = (
    "_checkpoint_wal_truncate_for_physical_cleanup",
    "_migrate_schema_v37_to_v38",
    "_physical_cleanup_operational_error_remnants",
)


def test_schema_reexports_all_evolution_functions() -> None:
    assert _EXPECTED_EVOLUTION_FUNCTIONS

    for name in _EXPECTED_EVOLUTION_FUNCTIONS:
        assert getattr(schema, name) is getattr(
            schema_evolution,
            name,
        )


def test_evolution_functions_preserve_historical_module_identity() -> None:
    for name in _EXPECTED_EVOLUTION_FUNCTIONS:
        function = getattr(schema, name)

        assert function.__module__ == "athena.storage.schema"
        assert pickle.loads(
            pickle.dumps(function, protocol=5)
        ) is function


def test_schema_retains_physical_cleanup_compatibility_boundary() -> None:
    for name in _COMPATIBILITY_RETAINED_FUNCTIONS:
        function = getattr(schema, name)

        assert inspect.isfunction(function)
        assert function.__module__ == "athena.storage.schema"

    migrate_source = inspect.getsource(
        schema._migrate_schema_v37_to_v38
    )
    migrate_tree = ast.parse(migrate_source)

    migrate_calls = {
        node.func.id
        for node in ast.walk(migrate_tree)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
        )
    }

    assert (
        "_physical_cleanup_operational_error_remnants"
        in migrate_calls
    )

    cleanup_source = inspect.getsource(
        schema._physical_cleanup_operational_error_remnants
    )
    cleanup_tree = ast.parse(cleanup_source)

    cleanup_calls = {
        node.func.id
        for node in ast.walk(cleanup_tree)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
        )
    }

    assert (
        "_checkpoint_wal_truncate_for_physical_cleanup"
        in cleanup_calls
    )


def test_schema_no_longer_owns_extracted_evolution_implementation() -> None:
    source = inspect.getsource(schema)
    tree = ast.parse(source)

    defined = {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }

    for name in _EXPECTED_EVOLUTION_FUNCTIONS:
        assert name not in defined

    assert "initialize_schema" in defined
    assert "_configure_connection" in defined
    assert "_create_schema_v1" not in defined

    local_migrations = {
        name
        for name in defined
        if name.startswith("_migrate_schema_")
    }

    assert local_migrations == {
        "_migrate_schema_v37_to_v38",
    }

    assert set(
        _COMPATIBILITY_RETAINED_FUNCTIONS
    ).issubset(defined)


def test_evolution_boundary_has_no_schema_import_cycle() -> None:
    source = inspect.getsource(schema_evolution)
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


def test_evolution_boundary_has_exact_expected_function_set() -> None:
    source = inspect.getsource(schema_evolution)
    tree = ast.parse(source)

    actual = tuple(
        sorted(
            node.name
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
        )
    )

    assert actual == _EXPECTED_EVOLUTION_FUNCTIONS

    assert not (
        set(_COMPATIBILITY_RETAINED_FUNCTIONS)
        & set(actual)
    )
