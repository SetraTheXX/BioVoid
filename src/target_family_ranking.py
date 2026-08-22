"""Contracts shared by the bounded target-family ranking workflows.

The canonical static pilot keeps its historical top-ten output by default.  A
separate, explicitly selected full-candidate arm may retain every detector
candidate for a later held-out ranking analysis.  This module contains only
the small, machine-checkable vocabulary for that boundary; it does not open
coordinates, evaluator labels, or start a computation.
"""

from __future__ import annotations

from typing import Any


CANDIDATE_RETENTION_TOP10 = "top10"
CANDIDATE_RETENTION_FULL = "full"
CANDIDATE_RETENTION_MODES = frozenset({CANDIDATE_RETENTION_TOP10, CANDIDATE_RETENTION_FULL})

HELD_OUT_RANKING_CONTRACT = "target-family-heldout-ranking-v1"


def validate_candidate_retention(value: Any) -> str:
    """Return a supported retention mode or fail closed."""

    if not isinstance(value, str) or value not in CANDIDATE_RETENTION_MODES:
        supported = ", ".join(sorted(CANDIDATE_RETENTION_MODES))
        raise ValueError(f"candidate_retention must be one of: {supported}")
    return value
