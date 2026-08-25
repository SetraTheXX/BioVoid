from __future__ import annotations


def test_locked_shadow_policies_are_deterministic_and_distinct() -> None:
    from scripts.evaluate_pocketminer_ranking_policies import (
        POLICY_IDS,
        _rank_pockets,
    )

    pockets = [
        {"pocket_id": "large-open", "volume": 10.0, "enclosure": 0.1},
        {"pocket_id": "small-closed", "volume": 9.9, "enclosure": 1.0},
        {"pocket_id": "tiny-open", "volume": 1.0, "enclosure": 0.2},
    ]

    canonical = _rank_pockets(pockets, POLICY_IDS[0])
    enclosure_aware = _rank_pockets(pockets, POLICY_IDS[1])

    assert [pocket["pocket_id"] for pocket in canonical] == [
        "large-open",
        "small-closed",
        "tiny-open",
    ]
    assert [pocket["pocket_id"] for pocket in enclosure_aware] == [
        "small-closed",
        "large-open",
        "tiny-open",
    ]
    assert [pocket["rank"] for pocket in enclosure_aware] == [1, 2, 3]
