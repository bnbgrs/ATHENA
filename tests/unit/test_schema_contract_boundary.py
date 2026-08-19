from __future__ import annotations

import ast
import inspect
import pickle
import sqlite3

from athena.storage import schema, schema_contract


def _contract_constant_names() -> tuple[str, ...]:
    return tuple(
        name
        for name, value in vars(schema_contract).items()
        if name.isupper()
        and not inspect.ismodule(value)
    )


def test_schema_reexports_contract_constants() -> None:
    names = _contract_constant_names()

    assert names
    assert names[0] == "ATHENA_APPLICATION_ID"
    assert "SCHEMA_VERSION" in names
    assert "PROTECTED_SOURCE_SEMANTIC_MIGRATION_ID" in names

    for name in names:
        assert getattr(schema, name) == getattr(
            schema_contract,
            name,
        )


def test_schema_reexports_compatibility_error_with_pickle_identity() -> None:
    assert (
        schema.DatabaseCompatibilityError
        is schema_contract.DatabaseCompatibilityError
    )
    assert (
        schema.DatabaseCompatibilityError.__module__
        == "athena.storage.schema"
    )

    error_type = schema.DatabaseCompatibilityError

    assert pickle.loads(
        pickle.dumps(error_type, protocol=5)
    ) is error_type

    instance = error_type("probe")
    restored = pickle.loads(
        pickle.dumps(instance, protocol=5)
    )

    assert type(restored) is error_type
    assert restored.args == ("probe",)


def test_schema_reexports_user_tables_helper() -> None:
    assert schema._user_tables is schema_contract._user_tables

    connection = sqlite3.connect(":memory:")
    try:
        connection.execute(
            "CREATE TABLE zeta(id INTEGER PRIMARY KEY AUTOINCREMENT)"
        )
        connection.execute(
            "CREATE TABLE alpha(id INTEGER PRIMARY KEY)"
        )

        assert schema._user_tables(connection) == (
            "alpha",
            "zeta",
        )
    finally:
        connection.close()


def test_schema_no_longer_defines_contract_implementation() -> None:
    source = inspect.getsource(schema)
    tree = ast.parse(source)

    assignments = {
        target.id
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }

    assert "ATHENA_APPLICATION_ID" not in assignments
    assert "SCHEMA_VERSION" not in assignments
    assert (
        "PROTECTED_SOURCE_SEMANTIC_MIGRATION_ID"
        not in assignments
    )

    class_names = {
        node.name
        for node in tree.body
        if isinstance(node, ast.ClassDef)
    }
    function_names = {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }

    assert "DatabaseCompatibilityError" not in class_names
    assert "_user_tables" not in function_names


def test_schema_contract_has_no_schema_import_cycle() -> None:
    source = inspect.getsource(schema_contract)
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
