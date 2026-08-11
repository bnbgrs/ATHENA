from athena.config.settings import AthenaSettings


def test_settings_default_log_level(monkeypatch) -> None:
    monkeypatch.delenv("ATHENA_LOG_LEVEL", raising=False)

    settings = AthenaSettings.from_environment()

    assert settings.log_level == "INFO"


def test_settings_read_log_level_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("ATHENA_LOG_LEVEL", "debug")

    settings = AthenaSettings.from_environment()

    assert settings.log_level == "DEBUG"
