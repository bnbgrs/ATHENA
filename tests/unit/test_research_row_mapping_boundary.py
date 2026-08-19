from __future__ import annotations

import inspect

from athena.research import repository, row_mapping

MAPPER_NAMES = (
    "_scope_from_row",
    "_candidate_set_from_row",
    "_candidate_from_row",
    "_work_item_from_row",
    "_synthesis_work_item_from_row",
    "_synthesis_work_input_from_row",
    "_synthesis_artifact_from_row",
    "_synthesis_evidence_from_row",
    "_research_result_from_row",
)


def test_repository_reexports_dedicated_row_mappers() -> None:
    for name in MAPPER_NAMES:
        repository_value = getattr(repository, name)
        mapping_value = getattr(row_mapping, name)

        assert repository_value is mapping_value
        assert mapping_value.__module__ == "athena.research.row_mapping"


def test_repository_no_longer_defines_row_mappers() -> None:
    source = inspect.getsource(repository)

    for name in MAPPER_NAMES:
        assert f"def {name}(" not in source


def test_row_mapping_boundary_contains_exact_mapper_set() -> None:
    actual = {
        name
        for name, value in vars(row_mapping).items()
        if inspect.isfunction(value)
        and value.__module__ == row_mapping.__name__
    }

    assert actual == set(MAPPER_NAMES)
