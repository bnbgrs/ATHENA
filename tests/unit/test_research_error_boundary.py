from __future__ import annotations

import inspect
import pickle

from athena.research import errors, repository

ERROR_NAMES = (
    "ResearchNotFoundError",
    "ResearchStateError",
    "ResearchScopeUnsupportedError",
    "ResearchSnapshotError",
    "ResearchFenceError",
)


def test_repository_reexports_research_error_boundary() -> None:
    for name in ERROR_NAMES:
        repository_type = getattr(repository, name)
        boundary_type = getattr(errors, name)

        assert repository_type is boundary_type
        assert repository_type.__module__ == (
            "athena.research.repository"
        )


def test_error_boundary_preserves_pickle_identity() -> None:
    for name in ERROR_NAMES:
        error_type = getattr(repository, name)

        assert pickle.loads(
            pickle.dumps(error_type, protocol=5)
        ) is error_type

        instance = error_type("probe")
        restored = pickle.loads(
            pickle.dumps(instance, protocol=5)
        )

        assert type(restored) is error_type
        assert restored.args == ("probe",)


def test_repository_uses_explicit_static_reexports() -> None:
    import ast

    source = inspect.getsource(repository)
    tree = ast.parse(source)

    imports = [
        node
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
        and node.module == "athena.research.errors"
    ]

    assert imports

    aliases: dict[str, str | None] = {}
    for import_node in imports:
        for alias in import_node.names:
            assert alias.name not in aliases
            aliases[alias.name] = alias.asname

    assert aliases == {
        name: name
        for name in ERROR_NAMES
    }


def test_repository_no_longer_defines_error_classes() -> None:
    source = inspect.getsource(repository)

    for name in ERROR_NAMES:
        assert f"class {name}" not in source


def test_errors_module_owns_exact_research_error_classes() -> None:
    actual = {
        name
        for name, value in vars(errors).items()
        if inspect.isclass(value)
        and name.startswith("Research")
    }

    assert actual == set(ERROR_NAMES)
