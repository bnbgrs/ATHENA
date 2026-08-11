import logging
import os
from pathlib import Path

import pytest

from athena.config.settings import AthenaSettings, ConfigurationError


def test_settings_default_log_level(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("ATHENA_LOG_LEVEL", raising=False)
    monkeypatch.setenv("ATHENA_LOCAL_ROOT", str(tmp_path))

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


def test_platform_default_root_is_absolute(monkeypatch) -> None:
    monkeypatch.delenv("ATHENA_LOCAL_ROOT", raising=False)

    if os.name == "nt":
        monkeypatch.setenv("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
    else:
        monkeypatch.delenv("LOCALAPPDATA", raising=False)
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)

    settings = AthenaSettings.from_environment()

    assert settings.local_root.is_absolute()


@pytest.mark.skipif(os.name == "nt", reason="POSIX-only XDG behavior")
def test_posix_default_honors_absolute_xdg_data_home(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("ATHENA_LOCAL_ROOT", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    settings = AthenaSettings.from_environment()

    assert settings.local_root == tmp_path / "athena"


def test_lm_studio_defaults_to_loopback(tmp_path) -> None:
    settings = AthenaSettings(local_root=tmp_path)

    assert settings.lm_studio_base_url == "http://127.0.0.1:1234"
    assert settings.model_request_timeout_seconds == 2.0
    assert settings.model_generation_timeout_seconds == 300.0


def test_lm_studio_base_url_normalizes_trailing_slash(tmp_path) -> None:
    settings = AthenaSettings(
        local_root=tmp_path,
        lm_studio_base_url="http://localhost:1234/",
    )

    assert settings.lm_studio_base_url == "http://localhost:1234"


def test_lm_studio_remote_host_is_rejected(tmp_path) -> None:
    with pytest.raises(ConfigurationError, match="local machine"):
        AthenaSettings(
            local_root=tmp_path,
            lm_studio_base_url="http://192.168.1.20:1234",
        )


def test_invalid_model_timeout_environment_is_rejected(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ATHENA_LOCAL_ROOT", str(tmp_path))
    monkeypatch.setenv("ATHENA_MODEL_REQUEST_TIMEOUT_SECONDS", "not-a-number")

    with pytest.raises(ConfigurationError, match="greater than zero"):
        AthenaSettings.from_environment()


def test_model_generation_timeout_environment(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ATHENA_LOCAL_ROOT", str(tmp_path))
    monkeypatch.setenv("ATHENA_MODEL_GENERATION_TIMEOUT_SECONDS", "45")

    settings = AthenaSettings.from_environment()

    assert settings.model_generation_timeout_seconds == 45.0


def test_invalid_model_generation_timeout_is_rejected(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ATHENA_LOCAL_ROOT", str(tmp_path))
    monkeypatch.setenv("ATHENA_MODEL_GENERATION_TIMEOUT_SECONDS", "0")

    with pytest.raises(ConfigurationError, match="greater than zero"):
        AthenaSettings.from_environment()
