"""Backup/restore error hierarchy."""

from __future__ import annotations


class BackupRestoreError(RuntimeError):
    """Raised when backup/restore cannot complete with verified integrity."""


# Preserve historical import/pickle identity through
# athena.backup.service while the implementation lives here.
BackupRestoreError.__module__ = "athena.backup.service"
