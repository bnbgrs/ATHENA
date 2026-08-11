import pytest

from athena.core.errors import ShutdownError, StartupError
from athena.core.services import ServiceManager


class FakeService:
    def __init__(
        self,
        name: str,
        events: list[str],
        *,
        fail_start: bool = False,
        fail_stop: bool = False,
    ) -> None:
        self._name = name
        self.events = events
        self.fail_start = fail_start
        self.fail_stop = fail_stop

    @property
    def name(self) -> str:
        return self._name

    def start(self) -> None:
        self.events.append(f"start:{self.name}")
        if self.fail_start:
            raise RuntimeError("start failed")

    def stop(self) -> None:
        self.events.append(f"stop:{self.name}")
        if self.fail_stop:
            raise RuntimeError("stop failed")


def test_services_start_in_order_and_stop_in_reverse() -> None:
    events: list[str] = []
    one = FakeService("one", events)
    two = FakeService("two", events)
    manager = ServiceManager((one, two))

    manager.start_all()
    manager.stop_all()

    assert events == [
        "start:one",
        "start:two",
        "stop:two",
        "stop:one",
    ]


def test_failed_start_rolls_back_already_started_services() -> None:
    events: list[str] = []
    one = FakeService("one", events)
    two = FakeService("two", events, fail_start=True)
    manager = ServiceManager((one, two))

    with pytest.raises(StartupError):
        manager.start_all()

    assert events == [
        "start:one",
        "start:two",
        "stop:one",
    ]
    assert manager.started_service_names == ()


def test_stop_attempts_all_services_even_if_one_fails() -> None:
    events: list[str] = []
    one = FakeService("one", events, fail_stop=True)
    two = FakeService("two", events)
    manager = ServiceManager((one, two))
    manager.start_all()

    with pytest.raises(ShutdownError):
        manager.stop_all()

    assert events[-2:] == ["stop:two", "stop:one"]
    assert manager.started_service_names == ()
