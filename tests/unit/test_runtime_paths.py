from athena.config.settings import AthenaSettings
from athena.storage.paths import RuntimePaths
from athena.storage.runtime import RuntimeLayoutService


def test_runtime_paths_keep_state_and_derived_separate(tmp_path) -> None:
    settings = AthenaSettings(local_root=tmp_path)
    paths = RuntimePaths.from_settings(settings)

    assert paths.state_root == tmp_path / "state"
    assert paths.database_path == tmp_path / "state" / "athena.db"
    assert paths.spool_root == tmp_path / "state" / "spool"
    assert paths.derived_root == tmp_path / "derived"
    assert paths.state_root != paths.derived_root


def test_runtime_layout_creates_required_local_directories(tmp_path) -> None:
    paths = RuntimePaths.from_settings(AthenaSettings(local_root=tmp_path))
    service = RuntimeLayoutService(paths)

    service.start()

    for directory in paths.required_local_directories:
        assert directory.is_dir()


def test_runtime_layout_does_not_create_optional_archive_roots(tmp_path) -> None:
    archive_root = tmp_path / "external" / "archive"
    settings = AthenaSettings(
        local_root=tmp_path / "local",
        archive_root=archive_root,
    )
    paths = RuntimePaths.from_settings(settings)

    RuntimeLayoutService(paths).start()

    assert not archive_root.exists()


def test_runtime_layout_stop_never_deletes_state(tmp_path) -> None:
    paths = RuntimePaths.from_settings(AthenaSettings(local_root=tmp_path))
    service = RuntimeLayoutService(paths)
    service.start()

    sentinel = paths.state_root / "must-survive.txt"
    sentinel.write_text("persistent", encoding="utf-8")

    service.stop()

    assert sentinel.read_text(encoding="utf-8") == "persistent"
