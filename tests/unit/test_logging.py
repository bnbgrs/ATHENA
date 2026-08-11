import json
import logging

from athena.observability.logging import JsonFormatter, configure_logging


def test_json_formatter_produces_machine_readable_event() -> None:
    record = logging.LogRecord(
        name="athena.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello",
        args=(),
        exc_info=None,
    )
    record.event = "test.event"

    payload = json.loads(JsonFormatter().format(record))

    assert payload["level"] == "INFO"
    assert payload["logger"] == "athena.test"
    assert payload["message"] == "hello"
    assert payload["event"] == "test.event"
    assert payload["timestamp"].endswith("+00:00")


def test_configure_logging_is_idempotent() -> None:
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    original_level = root.level

    try:
        root.handlers = []
        configure_logging(logging.INFO)
        configure_logging(logging.DEBUG)

        athena_handlers = [
            h for h in root.handlers
            if getattr(h, "_athena_console_handler", False)
        ]

        assert len(athena_handlers) == 1
        assert root.level == logging.DEBUG
    finally:
        for handler in root.handlers:
            if handler not in original_handlers:
                handler.close()
        root.handlers = original_handlers
        root.setLevel(original_level)
