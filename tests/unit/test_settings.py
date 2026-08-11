import logging

import pytest

from athena.config.settings import AthenaSettings, ConfigurationError


def test_settings_default_log_level(monkeypatch) -> None:
    monkeypatch.delenv("ATHENA_LOG_LEVEL", raising=False)

    settings = AthenaSettings.from_environment()

    assert settings.log_level == "INFO"
    assert settings.numeric_log_level == logging.INFO


def test_settings_normalize_log_level(monkeypatch) -> None:
    monkeypatch.setenv("ATHENA_LOG_LEVEL", " debug ")

    settings = AthenaSettings.from_environment()

    assert settings.log_level == "DEBUG"
    assert settings.numeric_log_level == logging.DEBUG


def test_settings_reject_invalid_log_level(monkeypatch) -> None:
    monkeypatch.setenv("ATHENA_LOG_LEVEL", "verbose")

    with pytest.raises(ConfigurationError):
        AthenaSettings.from_environment()
