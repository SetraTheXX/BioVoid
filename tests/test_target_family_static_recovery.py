from __future__ import annotations

import json

from scripts.run_target_family_static_recovery import (
    RECOVERY_MAX_DISK_BYTES,
    RECOVERY_RSS_LIMIT_BYTES,
    build_recovery_run_skeleton,
    validate_recovery_run,
)


def test_recovery_run_is_separate_bounded_and_redacted() -> None:
    payload = build_recovery_run_skeleton(
        manifest_sha256="a" * 64,
        primary_run_sha256="b" * 64,
        structure_id="4P0I",
        max_disk_bytes=RECOVERY_MAX_DISK_BYTES,
        rss_limit_bytes=RECOVERY_RSS_LIMIT_BYTES,
    )

    validate_recovery_run(payload)

    assert payload["execution"]["workers"] == 1
    assert payload["execution"]["motion_enabled"] is False
    assert payload["execution"]["canonical_static_result"] is False
    assert payload["execution"]["rss_limit_bytes"] == RECOVERY_RSS_LIMIT_BYTES
    assert payload["execution"]["max_disk_bytes"] == RECOVERY_MAX_DISK_BYTES
    serialized = json.dumps(payload, sort_keys=True).casefold()
    assert "holo" not in serialized
    assert "ligand" not in serialized
    assert "evaluator" not in serialized
    assert "ground_truth" not in serialized
