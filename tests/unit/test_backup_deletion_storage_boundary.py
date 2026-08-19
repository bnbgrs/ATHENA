from __future__ import annotations

import ast
import inspect

from athena.backup import deletion_codec, deletion_storage, service

STORAGE_METHODS = (
    "_read_target_deletion_records",
    "_write_target_deletion_head",
    "_validate_target_deletion_head",
    "_write_target_deletion_record",
)

CODEC_METHODS = (
    "_deletion_record_from_payload",
)


def test_backup_service_inherits_deletion_storage_boundary() -> None:
    assert issubclass(
        service.BackupService,
        deletion_storage.DeletionLedgerStorageMixin,
    )
    assert issubclass(
        deletion_storage.DeletionLedgerStorageMixin,
        deletion_codec.DeletionLedgerCodecMixin,
    )


def test_storage_mixin_owns_exact_target_io_methods() -> None:
    for name in STORAGE_METHODS:
        assert name not in vars(service.BackupService)
        assert name in vars(deletion_storage.DeletionLedgerStorageMixin)
        assert (
            getattr(service.BackupService, name)
            is getattr(deletion_storage.DeletionLedgerStorageMixin, name)
        )


def test_codec_mixin_owns_record_decoder() -> None:
    for name in CODEC_METHODS:
        assert name not in vars(service.BackupService)
        assert name not in vars(deletion_storage.DeletionLedgerStorageMixin)
        assert name in vars(deletion_codec.DeletionLedgerCodecMixin)


def test_service_no_longer_defines_moved_deletion_methods() -> None:
    source = inspect.getsource(service)
    tree = ast.parse(source)

    backup_class = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and node.name == "BackupService"
    )

    method_names = {
        node.name
        for node in backup_class.body
        if isinstance(node, ast.FunctionDef)
    }

    assert not method_names.intersection(
        set(STORAGE_METHODS + CODEC_METHODS)
    )


def test_storage_boundary_has_no_service_import_cycle() -> None:
    storage_source = inspect.getsource(deletion_storage)
    codec_source = inspect.getsource(deletion_codec)

    assert "athena.backup.service" not in storage_source
    assert "athena.backup.service" not in codec_source
