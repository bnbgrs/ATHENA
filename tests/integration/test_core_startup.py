from athena.core.application import ApplicationState, AthenaApplication
from athena.observability.health import HealthStatus


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
