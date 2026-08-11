from athena.version import __version__


def test_version_is_phase_zero_version() -> None:
    assert __version__ == "0.0.1"
