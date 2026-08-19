from __future__ import annotations

from pathlib import Path

import pytest

from athena.api.client import CoreApiClient
from athena.api.process import CoreApiProcess, CoreApiProcessOwnershipError
from athena.config.settings import AthenaSettings
from athena.core.application import ApplicationState


def _process(tmp_path: Path, *, name: str = "runtime") -> CoreApiProcess:
    return CoreApiProcess(
        settings=AthenaSettings(local_root=(tmp_path / name).resolve()),
    )


def test_core_api_process_starts_real_core_and_loopback_server(tmp_path: Path) -> None:
    process = _process(tmp_path)

    process.start()
    try:
        assert process.running is True
        assert process.app.state is ApplicationState.RUNNING
        assert process.server.port is not None

        client = CoreApiClient(process.runtime_root, timeout_seconds=2.0)
        health = client.health()

        assert health.core_status == "ok"
    finally:
        process.stop()

    assert process.running is False
    assert process.app.state is ApplicationState.STOPPED
    assert not (process.runtime_root / "core-api.json").exists()
    assert not (process.runtime_root / "core-api.token").exists()


def test_core_api_process_has_single_owner_per_local_root(tmp_path: Path) -> None:
    first = _process(tmp_path, name="shared")
    second = _process(tmp_path, name="shared")

    first.start()
    try:
        with pytest.raises(CoreApiProcessOwnershipError, match="live process owner"):
            second.start()

        assert second.app.state is ApplicationState.STOPPED
        assert second.server.running is False
    finally:
        first.stop()

    second.start()
    second.stop()


def test_core_api_process_stop_is_idempotent(tmp_path: Path) -> None:
    process = _process(tmp_path)

    process.start()
    process.stop()
    process.stop()

    assert process.app.state is ApplicationState.STOPPED
    assert process.server.running is False


def test_core_api_process_rejects_invalid_port(tmp_path: Path) -> None:
    settings = AthenaSettings(local_root=(tmp_path / "runtime").resolve())

    with pytest.raises(ValueError, match="between 0 and 65535"):
        CoreApiProcess(settings=settings, port=65536)


def test_core_api_process_rolls_back_when_server_start_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failed = _process(tmp_path, name="shared-failure")

    def fail_server_start() -> None:
        raise RuntimeError("synthetic server startup failure")

    monkeypatch.setattr(failed.server, "start", fail_server_start)

    with pytest.raises(RuntimeError, match="synthetic server startup failure"):
        failed.start()

    assert failed.app.state is ApplicationState.STOPPED
    assert failed.server.running is False

    replacement = _process(tmp_path, name="shared-failure")
    replacement.start()
    replacement.stop()
