from __future__ import annotations

from types import SimpleNamespace

import pytest

from scripts.evaluate_ri3_static_development import (
    RI3EvaluationError,
    _representative_chain_pairs,
    _split_chain_field,
)
from src.ground_truth_alignment import GroundTruthAlignmentError


def test_hyphenated_chain_union_expands_to_ordered_pairs() -> None:
    representative = SimpleNamespace(apo_chain="B-A", holo_chain="C-D")

    pairs = _representative_chain_pairs(representative)

    assert [(pair.apo_chain_id, pair.holo_chain_id) for pair in pairs] == [
        ("B", "C"),
        ("A", "D"),
    ]


def test_chain_union_requires_matching_apo_holo_lengths() -> None:
    with pytest.raises(RI3EvaluationError, match="Chain field is empty"):
        _split_chain_field("-")

    with pytest.raises(GroundTruthAlignmentError, match="different lengths"):
        _representative_chain_pairs(SimpleNamespace(apo_chain="A-B", holo_chain="A"))
