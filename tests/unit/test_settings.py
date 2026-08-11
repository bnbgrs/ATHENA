import logging
from pathlib import Path

import pytest

from athena.config.settings import AthenaSettings, ConfigurationError


def test_settings_default_log_level(monkeypatch) -> None:
    monkeypatch.delenv("ATHENA_LOG_LEVEL", raising=False)
    monkeypatch.delenv("ATHENA_LOCAL_ROOT", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(Path("C:/Users/Test/AppData/Local")))

    settings = AthenaSettings.from_environment()

    assert settings.log_level == "INFO"
    assert settings.numeric_log_level == logging.INFO


def test_settings_normalize_log_level(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ATHENA_LOG_LEVEL", " debug ")
    monkeypatch.setenv("ATHENA_LOCAL_ROOT", str(tmp_path))

    settings = AthenaSettings.from_environment()

    assert settings.log_level == "DEBUG"
    assert settings.numeric_log_level == logging.DEBUG


def test_settings_reject_invalid_log_level(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ATHENA_LOG_LEVEL", "verbose")
    monkeypatch.setenv("ATHENA_LOCAL_ROOT", str(tmp_path))

    with pytest.raises(ConfigurationError):
        AthenaSettings.from_environment()


def test_settings_read_explicit_storage_roots(tmp_path, monkeypatch) -> None:
    local_root = tmp_path / "local"
    archive_root = tmp_path / "archive"
    backup_root = tmp_path / "backup"
    projection_root = tmp_path / "projection"

    monkeypatch.setenv("ATHENA_LOCAL_ROOT", str(local_root))
    monkeypatch.setenv("ATHENA_ARCHIVE_ROOT", str(archive_root))
    monkeypatch.setenv("ATHENA_BACKUP_ROOT", str(backup_root))
    monkeypatch.setenv("ATHENA_PROJECTION_ROOT", str(projection_root))

    settings = AthenaSettings.from_environment()

    assert settings.local_root == local_root
    assert settings.archive_root == archive_root
    assert settings.backup_root == backup_root
    assert settings.projection_root == projection_root


def test_optional_long_term_roots_are_unset_by_default(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ATHENA_LOCAL_ROOT", str(tmp_path))
    monkeypatch.delenv("ATHENA_ARCHIVE_ROOT", raising=False)
    monkeypatch.delenv("ATHENA_BACKUP_ROOT", raising=False)
    monkeypatch.delenv("ATHENA_PROJECTION_ROOT", raising=False)

    settings = AthenaSettings.from_environment()

    assert settings.archive_root is None
    assert settings.backup_root is None
    assert settings.projection_root is None


def test_relative_runtime_root_is_rejected(monkeypatch) -> None:
    monkeypatch.setenv("ATHENA_LOCAL_ROOT", "relative/path")

    with pytest.raises(ConfigurationError, match="absolute path"):
        AthenaSettings.from_environment()
