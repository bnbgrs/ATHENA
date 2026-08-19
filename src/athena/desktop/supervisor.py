"""Lifecycle supervision for the dedicated ATHENA desktop Core process."""

from __future__ import annotations

import ntpath
import sys
from dataclasses import dataclass
from typing import Protocol, cast

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Slot

from athena.api.client import CoreApiClient, CoreApiClientError

_GRACEFUL_SHUTDOWN_TIMEOUT_MS = 3_000
_TERMINATE_TIMEOUT_MS = 1_000
_KILL_TIMEOUT_MS = 1_000
_CORE_ARGUMENTS = ("-m", "athena.api.process")
_VENV_LAUNCHER_ENV = "__PYVENV_LAUNCHER__"


@dataclass(frozen=True, slots=True)
class CoreProcessLaunchSpec:
    """Resolved child-process launch that preserves Windows venv semantics."""

    program: str
    arguments: tuple[str, ...]
    venv_launcher: str | None = None


class CoreSupervisorClient(Protocol):
    """Minimal control surface needed to stop only an owned Core."""

    def discovery_process_id(self) -> int: ...

    def request_shutdown(self) -> None: ...


class ManagedProcess(Protocol):
    """QProcess surface used by the supervisor and its deterministic tests."""

    def state(self) -> QProcess.ProcessState: ...

    def setProgram(self, program: str) -> None: ...  # noqa: N802

    def setArguments(self, arguments: list[str]) -> None: ...  # noqa: N802

    def setProcessEnvironment(self, environment: QProcessEnvironment) -> None: ...  # noqa: N802

    def setProcessChannelMode(self, mode: QProcess.ProcessChannelMode) -> None: ...  # noqa: N802

    def start(self) -> None: ...

    def processId(self) -> int: ...  # noqa: N802

    def waitForFinished(self, msecs: int = ...) -> bool: ...  # noqa: N802

    def terminate(self) -> None: ...

    def kill(self) -> None: ...


def core_process_launch_spec(
    *,
    executable: str | None = None,
    base_executable: str | None = None,
    platform: str | None = None,
) -> CoreProcessLaunchSpec:
    """Resolve a direct Core runtime process without the Windows venv redirector."""

    runtime_executable = executable or sys.executable
    runtime_platform = platform or sys.platform
    runtime_base = (
        base_executable
        if base_executable is not None
        else getattr(sys, "_base_executable", runtime_executable)
    )

    if (
        runtime_platform == "win32"
        and runtime_base
        and ntpath.normcase(ntpath.normpath(runtime_base))
        != ntpath.normcase(ntpath.normpath(runtime_executable))
    ):
        return CoreProcessLaunchSpec(
            program=runtime_base,
            arguments=_CORE_ARGUMENTS,
            venv_launcher=runtime_executable,
        )

    return CoreProcessLaunchSpec(
        program=runtime_executable,
        arguments=_CORE_ARGUMENTS,
    )


class DesktopCoreSupervisor(QObject):
    """Start one child Core and stop only the process this desktop owns."""

    def __init__(
        self,
        *,
        client: CoreSupervisorClient | None = None,
        process: ManagedProcess | None = None,
        executable: str | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.client: CoreSupervisorClient = (
            client or CoreApiClient.from_environment(timeout_seconds=0.75)
        )
        self.process = cast(ManagedProcess, process or QProcess(self))

        if executable is None:
            self.launch_spec = core_process_launch_spec()
        else:
            self.launch_spec = core_process_launch_spec(
                executable=executable,
                base_executable=executable,
            )

    @property
    def child_active(self) -> bool:
        return self.process.state() is not QProcess.ProcessState.NotRunning

    @Slot()
    def start(self) -> None:
        """Launch the dedicated Core without invoking uv or shell tooling."""
        if self.child_active:
            return

        environment = QProcessEnvironment.systemEnvironment()
        environment.remove(_VENV_LAUNCHER_ENV)
        if self.launch_spec.venv_launcher is not None:
            environment.insert(_VENV_LAUNCHER_ENV, self.launch_spec.venv_launcher)

        self.process.setProgram(self.launch_spec.program)
        self.process.setArguments(list(self.launch_spec.arguments))
        self.process.setProcessEnvironment(environment)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.ForwardedChannels)
        self.process.start()

    @Slot()
    def stop(self) -> None:
        """Gracefully stop only a Core whose discovery PID matches our child."""
        if not self.child_active:
            return

        process_id = int(self.process.processId())
        requested_graceful_shutdown = False

        if process_id > 0:
            try:
                if self.client.discovery_process_id() == process_id:
                    self.client.request_shutdown()
                    requested_graceful_shutdown = True
            except CoreApiClientError:
                pass

        if requested_graceful_shutdown and self.process.waitForFinished(
            _GRACEFUL_SHUTDOWN_TIMEOUT_MS
        ):
            return

        self.process.terminate()
        if self.process.waitForFinished(_TERMINATE_TIMEOUT_MS):
            return

        self.process.kill()
        self.process.waitForFinished(_KILL_TIMEOUT_MS)


def core_process_command(*, executable: str | None = None) -> tuple[str, ...]:
    """Expose the uv-free runtime command for tests and packaging work."""
    if executable is None:
        launch_spec = core_process_launch_spec()
    else:
        launch_spec = core_process_launch_spec(
            executable=executable,
            base_executable=executable,
        )
    return (launch_spec.program, *launch_spec.arguments)
