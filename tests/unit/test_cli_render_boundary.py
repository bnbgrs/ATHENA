from __future__ import annotations

import inspect

from athena import __main__ as launcher
from athena.cli import render


def test_launcher_reexports_dedicated_render_boundary() -> None:
    render_names = sorted(
        name
        for name, value in vars(render).items()
        if name.startswith("_print_") and callable(value)
    )
    assert render_names

    for name in render_names:
        launcher_value = getattr(launcher, name)
        render_value = getattr(render, name)
        assert launcher_value is render_value
        assert render_value.__module__ == "athena.cli.render"

    launcher_source = inspect.getsource(launcher)
    render_source = inspect.getsource(render)

    assert "def _print_" not in launcher_source
    assert "def _print_" in render_source


def test_render_boundary_contains_only_presentation_helpers() -> None:
    functions = sorted(
        name
        for name, value in vars(render).items()
        if inspect.isfunction(value) and value.__module__ == render.__name__
    )
    assert functions
    assert all(name.startswith("_print_") for name in functions)
