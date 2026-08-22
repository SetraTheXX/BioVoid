from __future__ import annotations


def test_metadata_pipeline_defaults_follow_current_pfam_artifacts() -> None:
    from scripts.audit_target_family_metadata_candidates import DEFAULT_INPUT, DEFAULT_OUTPUT
    from scripts.build_target_family_manifest import (
        DEFAULT_INVENTORY_OUTPUT,
        DEFAULT_MANIFEST_OUTPUT,
        DEFAULT_PAIRS_OUTPUT,
    )
    from scripts.materialize_target_family_sequence_clusters import (
        DEFAULT_INPUT as CLUSTER_INPUT,
        DEFAULT_OUTPUT as CLUSTER_OUTPUT,
    )

    paths = (
        DEFAULT_INPUT,
        DEFAULT_OUTPUT,
        DEFAULT_INVENTORY_OUTPUT,
        DEFAULT_PAIRS_OUTPUT,
        DEFAULT_MANIFEST_OUTPUT,
        CLUSTER_INPUT,
        CLUSTER_OUTPUT,
    )
    assert all("pfam" in path.as_posix().casefold() for path in paths)
    assert all("metadata-inventory-v1.json" not in path.name for path in paths)
    assert all("pilot-pairs-v1.json" not in path.name for path in paths)


def test_external_baseline_defaults_follow_current_pfam_rerun() -> None:
    from scripts.check_target_family_baseline_readiness import (
        DEFAULT_BASELINE_MANIFEST,
        DEFAULT_EVALUATION_REPORT,
        DEFAULT_MANIFEST,
        DEFAULT_OUTPUT,
        DEFAULT_PREPARED_ROOT,
        DEFAULT_RECOVERY_RUN,
        DEFAULT_STATIC_RUN,
    )
    from scripts.evaluate_target_family_external_baselines import (
        DEFAULT_FPOCKET_REPORT,
        DEFAULT_OUTPUT as COMPARISON_OUTPUT,
        DEFAULT_P2RANK_REPORT,
    )

    paths = (
        DEFAULT_MANIFEST,
        DEFAULT_STATIC_RUN,
        DEFAULT_RECOVERY_RUN,
        DEFAULT_EVALUATION_REPORT,
        DEFAULT_PREPARED_ROOT,
        DEFAULT_BASELINE_MANIFEST,
        DEFAULT_OUTPUT,
        DEFAULT_FPOCKET_REPORT,
        DEFAULT_P2RANK_REPORT,
        COMPARISON_OUTPUT,
    )
    serialized = "\n".join(path.as_posix() for path in paths).casefold()
    assert "cohort-detector-pfam-v1" in serialized
    assert "static-pilot-pfam-v1-rerun-v2" in serialized
    assert "static-evaluation-pfam-v1-rerun-v2" in serialized
    assert "static-pilot-recovery-pfam-v1" in serialized
    assert "external-baselines-pfam-v1" in serialized
    assert "target-blind-static-pilot-v1.json" not in serialized
    assert "static-pilot-v1/" not in serialized
    assert "static-evaluation-v1/" not in serialized
