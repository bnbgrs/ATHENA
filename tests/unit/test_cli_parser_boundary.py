from __future__ import annotations

import argparse
import inspect
import uuid

from athena import __main__ as launcher
from athena.cli import parser as parser_module


def test_launcher_reexports_dedicated_parser_boundary() -> None:
    assert launcher.build_parser is parser_module.build_parser
    assert launcher.build_parser.__module__ == "athena.cli.parser"

    launcher_source = inspect.getsource(launcher)
    parser_source = inspect.getsource(parser_module)

    assert "def build_parser(" not in launcher_source
    assert "def build_parser(" in parser_source
    assert "AthenaApplication" not in parser_source


def test_extracted_parser_preserves_typed_core_commands() -> None:
    parser = launcher.build_parser()
    assert isinstance(parser, argparse.ArgumentParser)
    assert parser.prog == "athena"

    chat = parser.parse_args(["chat", "new"])
    assert chat.command == "chat"
    assert chat.chat_command == "new"

    job_id = uuid.UUID("12345678-1234-5678-1234-567812345678")
    job = parser.parse_args(["job", "show", str(job_id)])
    assert job.command == "job"
    assert job.job_command == "show"
    assert job.job_id == job_id
