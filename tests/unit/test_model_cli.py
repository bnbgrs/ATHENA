from athena.__main__ import build_parser


def test_model_status_parser() -> None:
    args = build_parser().parse_args(["model", "status"])

    assert args.command == "model"
    assert args.model_command == "status"


def test_model_list_parser() -> None:
    args = build_parser().parse_args(["model", "list"])

    assert args.command == "model"
    assert args.model_command == "list"


def test_chat_send_parser() -> None:
    args = build_parser().parse_args(
        [
            "chat",
            "send",
            "019ff2e2-061e-7c60-905f-49aaa5fd74e8",
            "Hello",
            "--model",
            "example/model",
        ]
    )

    assert args.command == "chat"
    assert args.chat_command == "send"
    assert args.content == "Hello"
    assert args.model_id == "example/model"
