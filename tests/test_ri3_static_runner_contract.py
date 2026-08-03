from __future__ import annotations

import pytest

from scripts.run_ri3_static_development import (
    RI3RunError,
    _stable_hash,
    _validate_batch_size,
    _validate_manifest,
)


def test_ri3_checkpoint_batch_is_bounded() -> None:
    assert _validate_batch_size(1) == 1
    assert _validate_batch_size(10) == 10
    with pytest.raises(RI3RunError, match="between 1 and 10"):
        _validate_batch_size(11)


def test_manifest_hash_is_content_bound_and_target_blind() -> None:
    payload = {
        "schema_version": "biovoid-ri3-target-blind-runtime-manifest-v1",
        "structure_count": 663,
        "case_count": 825,
        "detector_boundary": {"evaluator_fields_in_manifest": False},
        "manifest_sha256": "",
    }
    payload["manifest_sha256"] = _stable_hash(
        {key: value for key, value in payload.items() if key != "manifest_sha256"}
    )
    with pytest.raises(RI3RunError, match="protocol"):
        _validate_manifest(payload)
