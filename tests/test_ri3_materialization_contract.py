from __future__ import annotations

from pathlib import Path

import pytest

from scripts.materialize_ri3_preflight import (
    REPO_ROOT,
    MaterializationError,
    _chain_ids,
    _resolve_repo_path,
    _select_ids,
)


def test_runtime_paths_resolve_relative_values_inside_repo() -> None:
    relative = Path("data/runtime/ri3/pilot10-members")
    expected = (REPO_ROOT / relative).resolve()

    assert _resolve_repo_path(relative) == expected
    assert _resolve_repo_path(expected) == expected


def test_select_ids_is_deterministic_and_development_bounded() -> None:
    development = ("1ABC", "2DEF", "3GHI")

    assert _select_ids(development, [], limit=2, all_development=False) == ("1abc", "2def")
    assert _select_ids(development, ["3ghi", "3GHI"], limit=12, all_development=False) == ("3ghi",)
    assert _select_ids(development, [], limit=12, all_development=True) == ("1abc", "2def", "3ghi")


def test_select_ids_rejects_non_development_or_ambiguous_scope() -> None:
    with pytest.raises(MaterializationError, match="not in development"):
        _select_ids(("1ABC",), ["9ZZZ"], limit=12, all_development=False)
    with pytest.raises(MaterializationError, match="either --structure-id"):
        _select_ids(("1ABC",), ["1ABC"], limit=12, all_development=True)


def test_chain_ids_preserves_the_union_of_hyphenated_components() -> None:
    records = ({"apo_chain": "B-A"}, {"apo_chain": "A"})

    assert _chain_ids(records) == ("A", "B")


def test_chain_ids_rejects_missing_preparation_scope() -> None:
    with pytest.raises(MaterializationError, match="No apo chains"):
        _chain_ids(({"apo_chain": ""},))
