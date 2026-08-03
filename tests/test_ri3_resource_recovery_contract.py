from __future__ import annotations

import pytest


def test_ri3_recovery_profile_is_bounded_and_opt_in() -> None:
    from src.resources import RI3_STATIC_RECOVERY, ResourceLimitError

    assert RI3_STATIC_RECOVERY.name == "ri3-static-recovery-v1"
    assert RI3_STATIC_RECOVERY.max_static_atoms == 12500
    assert RI3_STATIC_RECOVERY.max_static_candidates == 14000
    assert RI3_STATIC_RECOVERY.max_analysis_workers == 1
    assert RI3_STATIC_RECOVERY.static_candidate_estimate_multiplier == 1.5
    assert (
        RI3_STATIC_RECOVERY.validate_static_request(
            atom_count=5000,
            available_memory_bytes=8 * 1024**3,
        )
        < RI3_STATIC_RECOVERY.soft_memory_budget_bytes
    )

    with pytest.raises(ResourceLimitError, match="static detector"):
        RI3_STATIC_RECOVERY.validate_static_request(
            atom_count=RI3_STATIC_RECOVERY.max_static_atoms + 1,
            available_memory_bytes=8 * 1024**3,
        )


def test_ri3_recovery_profile_rejects_invalid_multiplier() -> None:
    from src.resources import ResourceLimitError, ResourceProfile

    profile = ResourceProfile(
        name="invalid",
        soft_memory_budget_bytes=1024,
        minimum_available_memory_bytes=0,
        max_heavy_jobs=1,
        max_analysis_workers=1,
        max_download_workers=1,
        max_nma_atoms=1,
        max_motion_modes=1,
        max_samples_per_mode=1,
        max_motion_samples=1,
        max_static_atoms=100,
        max_static_candidates=100,
        static_candidate_estimate_multiplier=0,
    )
    with pytest.raises(ResourceLimitError, match="multiplier"):
        profile.validate_static_request(atom_count=50, available_memory_bytes=2048)
