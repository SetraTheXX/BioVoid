from __future__ import annotations

from scripts.evaluate_ahoj_geometry_ranking_policies import (
    POLICY_IDS,
    rank_pockets,
)


def test_ahoj_locked_policy_set_is_finite_and_deterministic() -> None:
    pockets = [
        {"pocket_id": "large-open", "volume": 10.0, "enclosure": 0.1, "center": [0, 0, 0]},
        {"pocket_id": "small-closed", "volume": 9.0, "enclosure": 1.0, "center": [1, 0, 0]},
        {"pocket_id": "medium", "volume": 8.0, "enclosure": 0.5, "center": [2, 0, 0]},
    ]

    assert POLICY_IDS == (
        "A-canonical-volume-v1",
        "B-volume-enclosure-70-30-v1",
        "C-volume-enclosure-50-50-v1",
    )
    assert [item["pocket_id"] for item in rank_pockets(pockets, POLICY_IDS[0])] == [
        "large-open",
        "small-closed",
        "medium",
    ]
    assert [item["pocket_id"] for item in rank_pockets(pockets, POLICY_IDS[1])] == [
        "large-open",
        "small-closed",
        "medium",
    ]
    assert [item["rank"] for item in rank_pockets(pockets, POLICY_IDS[2])] == [1, 2, 3]


def test_ahoj_policy_tie_break_is_stable() -> None:
    pockets = [
        {"pocket_id": "z", "volume": 1.0, "enclosure": 0.5, "center": [0, 0, 0]},
        {"pocket_id": "a", "volume": 1.0, "enclosure": 0.5, "center": [1, 0, 0]},
    ]
    ranked = rank_pockets(pockets, "A-canonical-volume-v1")
    assert [item["pocket_id"] for item in ranked] == ["a", "z"]
    assert [item["rank"] for item in ranked] == [1, 2]
