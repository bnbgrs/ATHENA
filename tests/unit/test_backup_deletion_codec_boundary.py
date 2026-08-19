from __future__ import annotations

import ast
import inspect
import uuid

from athena.backup.deletion_codec import DeletionLedgerCodecMixin
from athena.backup.service import BackupService
from athena.lifecycle.deletion import DeletionLedgerRecord


def _record() -> DeletionLedgerRecord:
    return DeletionLedgerRecord(
        ledger_seq=1,
        deletion_id=uuid.UUID(
            "00000000-0000-7000-8000-000000000001"
        ),
        entity_id=uuid.UUID(
            "00000000-0000-7000-8000-000000000101"
        ),
        entity_type="personal_memory",
        deleted_at_us=123456789,
        deletion_commit_seq=11,
        deleted_by_actor_id=uuid.UUID(
            "00000000-0000-7000-8000-000000000201"
        ),
    )


def test_backup_service_inherits_deletion_codec_boundary() -> None:
    assert issubclass(BackupService, DeletionLedgerCodecMixin)
    assert DeletionLedgerCodecMixin in BackupService.__mro__[1:]

    for name in (
        "_deletion_records_digest",
        "_deletion_head_payload",
        "_deletion_record_name",
        "_deletion_record_payload",
    ):
        assert name not in BackupService.__dict__
        assert name in DeletionLedgerCodecMixin.__dict__


def test_codec_methods_remain_classmethods() -> None:
    for name in (
        "_deletion_records_digest",
        "_deletion_head_payload",
        "_deletion_record_name",
        "_deletion_record_payload",
    ):
        descriptor = inspect.getattr_static(
            DeletionLedgerCodecMixin,
            name,
        )
        assert isinstance(descriptor, classmethod)


def test_codec_output_contract_is_stable() -> None:
    record = _record()
    payload = BackupService._deletion_record_payload(record)

    assert payload == {
        "deleted_at_us": 123456789,
        "deleted_by_actor_id": (
            "00000000-0000-7000-8000-000000000201"
        ),
        "deletion_commit_seq": 11,
        "deletion_id": "00000000-0000-7000-8000-000000000001",
        "entity_id": "00000000-0000-7000-8000-000000000101",
        "entity_type": "personal_memory",
        "format_version": 1,
        "ledger_seq": 1,
    }

    assert BackupService._deletion_record_name(record).endswith(
        ".json"
    )


def test_service_no_longer_defines_codec_implementation() -> None:
    import athena.backup.service as service_module

    source = inspect.getsource(service_module)
    tree = ast.parse(source)

    backup_class = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and node.name == "BackupService"
    )

    service_methods = {
        node.name
        for node in backup_class.body
        if isinstance(node, ast.FunctionDef)
    }

    for name in (
        "_deletion_records_digest",
        "_deletion_head_payload",
        "_deletion_record_name",
        "_deletion_record_payload",
    ):
        assert name not in service_methods

    assert "def _canonical_json(" not in source
