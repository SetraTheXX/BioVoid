import numpy as np

from src.multiframe import ConsensusConfig, aggregate_consensus_pockets


def _pocket(center, *, score=0.8, volume=100.0, druggable=False):
    return {
        "center": np.asarray(center, dtype=float),
        "bio_score": float(score),
        "volume": float(volume),
        "druggable": bool(druggable),
    }


def test_consensus_requires_min_three_frames():
    per_frame = [
        [_pocket([0.0, 0.0, 0.0], score=0.70)],
        [_pocket([0.5, 0.1, -0.1], score=0.80)],
        [_pocket([0.9, -0.2, 0.2], score=0.75)],
    ]
    labels = ["frame_001.pdb", "frame_002.pdb", "frame_003.pdb"]
    config = ConsensusConfig(
        min_support_frames=3,
        cluster_distance=2.0,
        per_frame_top_n=20,
    )

    consensus, stats = aggregate_consensus_pockets(per_frame, labels, config)

    assert len(consensus) == 1
    assert consensus[0]["consensus_support_frames"] == 3
    assert consensus[0]["rank"] == 1
    assert stats["consensus_clusters"] == 1


def test_consensus_filters_low_support_clusters():
    per_frame = [
        [_pocket([0.0, 0.0, 0.0], druggable=False), _pocket([20.0, 0.0, 0.0])],
        [_pocket([0.4, 0.1, 0.2], druggable=True), _pocket([20.5, 0.2, 0.0])],
        [_pocket([0.8, 0.0, -0.1], druggable=False)],
    ]
    labels = ["frame_001.pdb", "frame_002.pdb", "frame_003.pdb"]
    config = ConsensusConfig(
        min_support_frames=3,
        cluster_distance=1.5,
        per_frame_top_n=20,
    )

    consensus, _ = aggregate_consensus_pockets(per_frame, labels, config)

    assert len(consensus) == 1
    # At least one frame had druggable pocket in the same cluster.
    assert consensus[0]["druggable"] is True
    # Two-frame cluster at x~20 should be dropped.
    assert consensus[0]["center"][0] < 2.0


def test_consensus_stability_metrics_are_reported():
    per_frame = [
        [_pocket([1.0, 1.0, 1.0], volume=100.0, score=0.6)],
        [_pocket([1.2, 1.1, 0.9], volume=110.0, score=0.7)],
        [_pocket([0.9, 1.0, 1.1], volume=90.0, score=0.8)],
    ]
    labels = ["frame_001.pdb", "frame_002.pdb", "frame_003.pdb"]
    config = ConsensusConfig(
        min_support_frames=3,
        cluster_distance=1.0,
        per_frame_top_n=20,
        center_stability_max=2.0,
        volume_cv_max=0.20,
    )

    consensus, stats = aggregate_consensus_pockets(per_frame, labels, config)

    assert len(consensus) == 1
    pocket = consensus[0]
    assert pocket["consensus_center_stability"] < 0.5
    assert pocket["consensus_volume_cv"] < 0.2
    assert pocket["consensus_center_stable"] is True
    assert pocket["consensus_volume_stable"] is True
    assert pocket["consensus_score"] > 0.0
    assert stats["avg_center_stability"] > 0.0
