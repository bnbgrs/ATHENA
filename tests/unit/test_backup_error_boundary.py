from __future__ import annotations

import ast
import inspect
import pickle

from athena.backup import errors, service


def test_service_reexports_backup_restore_error_boundary() -> None:
    assert service.BackupRestoreError is errors.BackupRestoreError
    assert service.BackupRestoreError.__module__ == "athena.backup.service"


def test_backup_restore_error_preserves_pickle_identity() -> None:
    error_type = service.BackupRestoreError

    assert pickle.loads(
        pickle.dumps(error_type, protocol=5)
    ) is error_type

    instance = error_type("probe")
    restored = pickle.loads(
        pickle.dumps(instance, protocol=5)
    )

    assert type(restored) is error_type
    assert restored.args == ("probe",)


def test_service_uses_explicit_static_reexport() -> None:
    source = inspect.getsource(service)
    tree = ast.parse(source)

    imports = [
        node
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
        and node.module == "athena.backup.errors"
    ]

    aliases: dict[str, str | None] = {}
    for import_node in imports:
        for alias in import_node.names:
            assert alias.name not in aliases
            aliases[alias.name] = alias.asname

    assert aliases == {
        "BackupRestoreError": "BackupRestoreError",
    }


def test_service_no_longer_defines_backup_restore_error() -> None:
    source = inspect.getsource(service)
    assert "class BackupRestoreError(" not in source


def test_errors_module_owns_exact_backup_error_classes() -> None:
    actual = {
        name
        for name, value in vars(errors).items()
        if inspect.isclass(value)
        and name.startswith("Backup")
    }

    assert actual == {"BackupRestoreError"}
