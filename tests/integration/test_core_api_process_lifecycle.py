from __future__ import annotations

import threading
import time
from pathlib import Path

from athena.api.client import CoreApiClient
from athena.api.process import CoreApiProcess
from athena.config.settings import AthenaSettings


def test_dedicated_core_process_serves_until_desktop_requests_stop(tmp_path: Path) -> None:
    settings = AthenaSettings(local_root=(tmp_path / "runtime").resolve())
    process = CoreApiProcess(settings=settings)
    stop_event = threading.Event()
    result: list[int] = []

    thread = threading.Thread(
        target=lambda: result.append(process.run(stop_event=stop_event)),
        name="test-athena-core-process",
    )
    thread.start()

    try:
        discovery_path = process.runtime_root / "core-api.json"
        deadline = time.monotonic() + 5.0
        while not discovery_path.exists():
            if time.monotonic() >= deadline:
                raise AssertionError("ATHENA Core API discovery was not published in time.")
            time.sleep(0.01)

        client = CoreApiClient(process.runtime_root, timeout_seconds=2.0)
        health = client.health()
        capabilities = client.capabilities()

        assert health.core_status == "ok"
        assert "chat.read" in capabilities.features
    finally:
        stop_event.set()
        thread.join(timeout=5.0)

    assert thread.is_alive() is False
    assert result == [0]
    assert process.running is False
    assert not (process.runtime_root / "core-api.json").exists()
    assert not (process.runtime_root / "core-api.token").exists()


def test_authenticated_shutdown_stops_the_dedicated_core_process(tmp_path: Path) -> None:
    settings = AthenaSettings(local_root=(tmp_path / "shutdown-runtime").resolve())
    process = CoreApiProcess(settings=settings)
    result: list[int] = []

    thread = threading.Thread(
        target=lambda: result.append(process.run()),
        name="test-athena-core-api-shutdown",
    )
    thread.start()

    try:
        discovery_path = process.runtime_root / "core-api.json"
        deadline = time.monotonic() + 5.0
        while not discovery_path.exists():
            if time.monotonic() >= deadline:
                raise AssertionError("ATHENA Core API discovery was not published in time.")
            time.sleep(0.01)

        client = CoreApiClient(process.runtime_root, timeout_seconds=2.0)
        client.request_shutdown()
        thread.join(timeout=5.0)
    finally:
        if thread.is_alive():
            process.request_shutdown()
            thread.join(timeout=5.0)

    assert thread.is_alive() is False
    assert result == [0]
    assert process.running is False
    assert not (process.runtime_root / "core-api.json").exists()
    assert not (process.runtime_root / "core-api.token").exists()
