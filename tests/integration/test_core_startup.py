import pytest

from athena.core.application import ApplicationState, AthenaApplication
from athena.core.errors import StartupError
from athena.observability.health import HealthStatus


class FailingService:
    @property
    def name(self) -> str:
        return "failing"

    def start(self) -> None:
        raise RuntimeError("boom")

    def stop(self) -> None:
        pass


def test_core_can_start_and_stop() -> None:
    app = AthenaApplication()

    assert app.state is ApplicationState.STOPPED
    assert app.health.snapshot().status is HealthStatus.STOPPED

    app.start()

    assert app.state is ApplicationState.RUNNING
    assert app.health.snapshot().status is HealthStatus.OK

    app.stop()

    assert app.state is ApplicationState.STOPPED
    assert app.health.snapshot().status is HealthStatus.STOPPED


def test_start_and_stop_are_idempotent() -> None:
    app = AthenaApplication()

    app.start()
    app.start()
    assert app.state is ApplicationState.RUNNING

    app.stop()
    app.stop()
    assert app.state is ApplicationState.STOPPED


def test_failed_service_start_marks_core_failed() -> None:
    app = AthenaApplication(services=(FailingService(),))

    with pytest.raises(StartupError):
        app.start()

    assert app.state is ApplicationState.FAILED
    health = app.health.snapshot()
    assert health.status is HealthStatus.FAILED
    assert "failing" in (health.detail or "")

    app.stop()
    assert app.state is ApplicationState.STOPPED
