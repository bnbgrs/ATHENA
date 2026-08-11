from athena.__main__ import build_parser


def test_model_status_parser() -> None:
    args = build_parser().parse_args(["model", "status"])

    assert args.command == "model"
    assert args.model_command == "status"


def test_model_list_parser() -> None:
    args = build_parser().parse_args(["model", "list"])

    assert args.command == "model"
    assert args.model_command == "list"
