from __future__ import annotations

from PySide6.QtCore import QProcess, QProcessEnvironment

from athena.api.client import CoreApiClientError
from athena.desktop.supervisor import (
    DesktopCoreSupervisor,
    core_process_command,
    core_process_launch_spec,
)


class _Client:
    def __init__(self, *, process_id: int | None = 4242, fail_discovery: bool = False) -> None:
        self.process_id = process_id
        self.fail_discovery = fail_discovery
        self.shutdown_calls = 0

    def discovery_process_id(self) -> int:
        if self.fail_discovery:
            raise CoreApiClientError("Discovery unavailable.")
        assert self.process_id is not None
        return self.process_id

    def request_shutdown(self) -> None:
        self.shutdown_calls += 1


class _Process:
    def __init__(self, *, process_id: int = 4242, waits: tuple[bool, ...] = ()) -> None:
        self.program = ""
        self.arguments: list[str] = []
        self.environment: QProcessEnvironment | None = None
        self.channel_mode: QProcess.ProcessChannelMode | None = None
        self.process_id = process_id
        self.process_state = QProcess.ProcessState.NotRunning
        self.waits = list(waits)
        self.wait_timeouts: list[int] = []
        self.terminate_calls = 0
        self.kill_calls = 0

    def state(self) -> QProcess.ProcessState:
        return self.process_state

    def setProgram(self, program: str) -> None:  # noqa: N802
        self.program = program

    def setArguments(self, arguments: list[str]) -> None:  # noqa: N802
        self.arguments = arguments

    def setProcessEnvironment(self, environment: QProcessEnvironment) -> None:  # noqa: N802
        self.environment = environment

    def setProcessChannelMode(self, mode: QProcess.ProcessChannelMode) -> None:  # noqa: N802
        self.channel_mode = mode

    def start(self) -> None:
        self.process_state = QProcess.ProcessState.Running

    def processId(self) -> int:  # noqa: N802
        return self.process_id

    def waitForFinished(self, msecs: int = 30_000) -> bool:  # noqa: N802
        self.wait_timeouts.append(msecs)
        result = self.waits.pop(0) if self.waits else False
        if result:
            self.process_state = QProcess.ProcessState.NotRunning
        return result

    def terminate(self) -> None:
        self.terminate_calls += 1

    def kill(self) -> None:
        self.kill_calls += 1


def test_windows_venv_launch_bypasses_redirector_but_preserves_venv() -> None:
    launch = core_process_launch_spec(
        executable=r"C:\workspace\.venv\Scripts\python.exe",
        base_executable=r"C:\Python312\python.exe",
        platform="win32",
    )

    assert launch.program == r"C:\Python312\python.exe"
    assert launch.arguments == ("-m", "athena.api.process")
    assert launch.venv_launcher == r"C:\workspace\.venv\Scripts\python.exe"


def test_non_windows_launch_uses_runtime_executable_directly() -> None:
    launch = core_process_launch_spec(
        executable="/workspace/.venv/bin/python",
        base_executable="/usr/bin/python3",
        platform="linux",
    )

    assert launch.program == "/workspace/.venv/bin/python"
    assert launch.arguments == ("-m", "athena.api.process")
    assert launch.venv_launcher is None


def test_supervisor_launches_direct_runtime_without_uv() -> None:
    process = _Process()
    supervisor = DesktopCoreSupervisor(client=_Client(), process=process)
    launch = core_process_launch_spec()

    supervisor.start()

    assert process.program == launch.program
    assert process.arguments == ["-m", "athena.api.process"]
    assert process.environment is not None
    assert process.environment.value("__PYVENV_LAUNCHER__") == (
        launch.venv_launcher or ""
    )
    assert "uv" not in " ".join(core_process_command()).casefold()
    assert process.channel_mode is QProcess.ProcessChannelMode.ForwardedChannels
    assert supervisor.child_active is True


def test_explicit_supervisor_executable_is_not_rewritten() -> None:
    process = _Process()
    supervisor = DesktopCoreSupervisor(
        client=_Client(),
        process=process,
        executable="custom-python",
    )

    supervisor.start()

    assert process.program == "custom-python"
    assert process.environment is not None
    assert process.environment.value("__PYVENV_LAUNCHER__") == ""


def test_supervisor_gracefully_stops_matching_child() -> None:
    client = _Client(process_id=4242)
    process = _Process(process_id=4242, waits=(True,))
    process.start()
    supervisor = DesktopCoreSupervisor(client=client, process=process)

    supervisor.stop()

    assert client.shutdown_calls == 1
    assert process.terminate_calls == 0
    assert process.kill_calls == 0
    assert supervisor.child_active is False


def test_supervisor_never_shutdowns_discovery_owned_by_another_process() -> None:
    client = _Client(process_id=9999)
    process = _Process(process_id=4242, waits=(True,))
    process.start()
    supervisor = DesktopCoreSupervisor(client=client, process=process)

    supervisor.stop()

    assert client.shutdown_calls == 0
    assert process.terminate_calls == 1
    assert process.kill_calls == 0


def test_supervisor_falls_back_to_kill_after_owned_core_timeouts() -> None:
    client = _Client(process_id=4242)
    process = _Process(process_id=4242, waits=(False, False, True))
    process.start()
    supervisor = DesktopCoreSupervisor(client=client, process=process)

    supervisor.stop()

    assert client.shutdown_calls == 1
    assert process.terminate_calls == 1
    assert process.kill_calls == 1
    assert process.wait_timeouts == [3_000, 1_000, 1_000]
    assert supervisor.child_active is False


def test_supervisor_does_not_control_unknown_discovery_owner() -> None:
    client = _Client(fail_discovery=True)
    process = _Process(process_id=4242, waits=(True,))
    process.start()
    supervisor = DesktopCoreSupervisor(client=client, process=process)

    supervisor.stop()

    assert client.shutdown_calls == 0
    assert process.terminate_calls == 1
