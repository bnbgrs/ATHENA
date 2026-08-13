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


def test_job_source_extract_parser_accepts_hierarchical_budget_options() -> None:
    args = build_parser().parse_args(
        [
            "job",
            "source-extract",
            "11111111-1111-1111-1111-111111111111",
            "--model",
            "local-primary",
            "--context-limit",
            "4096",
            "--output-reserve",
            "768",
            "--safety-margin",
            "256",
            "--max-depth",
            "9",
        ]
    )
    assert args.job_command == "source-extract"
    assert str(args.analysis_id) == "11111111-1111-1111-1111-111111111111"
    assert args.model_id == "local-primary"
    assert args.context_limit == 4096
    assert args.output_reserve == 768
    assert args.safety_margin == 256
    assert args.max_depth == 9


def test_job_run_extraction_parser_defaults_worker() -> None:
    args = build_parser().parse_args(
        ["job", "run-extraction", "22222222-2222-2222-2222-222222222222"]
    )
    assert args.job_command == "run-extraction"
    assert args.worker == "athena-cli-extraction-worker"
    assert args.lease_seconds == 120


def test_memory_remember_parser_defaults_to_explicit_global_other() -> None:
    args = build_parser().parse_args(["memory", "remember", "Prefer German answers."])

    assert args.command == "memory"
    assert args.memory_command == "remember"
    assert args.content == "Prefer German answers."
    assert args.kind.value == "other"
    assert args.scope_kind.value == "global"
    assert args.scope_id is None
    assert args.sensitivity.value == "normal"


def test_memory_scoped_remember_parser() -> None:
    args = build_parser().parse_args(
        [
            "memory",
            "remember",
            "Use detailed technical answers.",
            "--kind",
            "detail_preference",
            "--scope-kind",
            "project",
            "--scope-id",
            "11111111-1111-1111-1111-111111111111",
        ]
    )

    assert args.memory_command == "remember"
    assert args.kind.value == "detail_preference"
    assert args.scope_kind.value == "project"
    assert str(args.scope_id) == "11111111-1111-1111-1111-111111111111"
