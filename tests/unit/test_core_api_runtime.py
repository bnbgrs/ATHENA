from __future__ import annotations

import json
import os
import stat

import pytest

from athena.api.runtime import ApiRuntimeError, LocalApiRuntime


def test_local_api_runtime_publishes_private_ephemeral_bootstrap(tmp_path) -> None:
    runtime = LocalApiRuntime(tmp_path / "api")

    discovery = runtime.publish(port=32123)

    assert discovery.api_version == "v1"
    assert discovery.host == "127.0.0.1"
    assert discovery.port == 32123
    assert discovery.process_id == os.getpid()
    assert runtime.discovery_path.is_file()
    assert runtime.token_path.is_file()

    payload = json.loads(runtime.discovery_path.read_text(encoding="utf-8"))
    token = runtime.token_path.read_text(encoding="utf-8").strip()

    assert payload == discovery.to_dict()
    assert payload["token_path"] == str(runtime.token_path)
    assert token
    assert token not in runtime.discovery_path.read_text(encoding="utf-8")
    assert runtime.authenticate(token) is True
    assert runtime.authenticate(token + "x") is False

    if os.name != "nt":
        assert stat.S_IMODE(runtime.token_path.stat().st_mode) == 0o600
        assert stat.S_IMODE(runtime.discovery_path.stat().st_mode) == 0o600

    runtime.clear()

    assert not runtime.discovery_path.exists()
    assert not runtime.token_path.exists()
    assert runtime.authenticate(token) is False


def test_local_api_runtime_rotates_token_on_republish(tmp_path) -> None:
    runtime = LocalApiRuntime(tmp_path / "api")

    runtime.publish(port=32123)
    first = runtime.token_path.read_text(encoding="utf-8").strip()

    runtime.publish(port=32124)
    second = runtime.token_path.read_text(encoding="utf-8").strip()

    assert first != second
    assert runtime.authenticate(first) is False
    assert runtime.authenticate(second) is True


def test_local_api_runtime_rejects_invalid_ports(tmp_path) -> None:
    runtime = LocalApiRuntime(tmp_path / "api")

    with pytest.raises(ValueError, match="between 1 and 65535"):
        runtime.publish(port=0)

    with pytest.raises(ValueError, match="between 1 and 65535"):
        runtime.publish(port=65536)


def test_local_api_runtime_rejects_symlink_root(tmp_path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"

    try:
        linked.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Directory symlinks unavailable in this environment.")

    runtime = LocalApiRuntime(linked)

    with pytest.raises(ApiRuntimeError, match="must not be a symlink"):
        runtime.publish(port=32123)
