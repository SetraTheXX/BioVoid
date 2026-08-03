"""Tool-neutral pocket output records for static detector comparisons."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Literal, Mapping

EVALUATOR_SCHEMA_VERSION = "pocket-evaluator-input-v1"
PRODUCT_RANKING_CONTRACT_VERSION = "product-heuristic-ranking-v1"
DetectorName = Literal[
    "biovoid_static",
    "biovoid_motion",
    "fpocket",
    "p2rank",
]
DetectorStatus = Literal["completed", "unavailable", "failed"]

_PROHIBITED_DETECTOR_KEYS = frozenset(
    {
        "cryptic_pocket_center",
        "ground_truth",
        "ground_truth_center",
        "hit",
        "holo",
        "holo_center",
        "known_center",
        "known_ligand",
        "known_pocket_center",
        "ligand_atoms",
        "ligand_center",
        "ligand_residues",
        "reference_center",
        "success",
        "target_center",
        "target_residues",
    }
)


class DetectorLeakageError(ValueError):
    """Raised when evaluator-only target information enters detector output."""


@dataclass(frozen=True)
class EvaluatorPocket:
    pocket_id: str
    center: tuple[float, float, float]
    volume: float | None
    rank: int
    score: float | None
    raw: dict[str, Any]


@dataclass(frozen=True)
class DetectorEvaluationRecord:
    schema_version: str
    detector: DetectorName
    structure_id: str
    status: DetectorStatus
    pockets: tuple[EvaluatorPocket, ...]
    error: str | None = None
    provenance: dict[str, Any] | None = None


def _center(value: Any) -> tuple[float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError("Pocket center must contain exactly three coordinates")
    center = (float(value[0]), float(value[1]), float(value[2]))
    if not all(math.isfinite(item) for item in center):
        raise ValueError("Pocket center coordinates must be finite")
    return center


def assert_detector_payload_is_blind(payload: Any, *, path: str = "payload") -> None:
    """Reject evaluator-only labels anywhere in detector-owned data."""
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            normalized = str(key).strip().lower().replace("-", "_").replace(" ", "_")
            if normalized in _PROHIBITED_DETECTOR_KEYS:
                raise DetectorLeakageError(f"Evaluator-only field '{key}' found at {path}")
            assert_detector_payload_is_blind(value, path=f"{path}.{key}")
    elif isinstance(payload, (list, tuple)):
        for index, value in enumerate(payload):
            assert_detector_payload_is_blind(value, path=f"{path}[{index}]")


def _validated_raw(payload: dict[str, Any]) -> dict[str, Any]:
    assert_detector_payload_is_blind(payload)
    return dict(payload)


def adapt_biovoid_pockets(
    structure_id: str,
    pockets: list[dict[str, Any]],
    *,
    provenance: dict[str, Any] | None = None,
) -> DetectorEvaluationRecord:
    normalized = tuple(
        EvaluatorPocket(
            pocket_id=str(pocket.get("pocket_id", pocket.get("id", index))),
            center=_center(pocket["center"]),
            volume=float(pocket["volume"]) if pocket.get("volume") is not None else None,
            rank=int(pocket.get("rank", index)),
            score=(float(pocket["bio_score"]) if pocket.get("bio_score") is not None else None),
            raw=_validated_raw(pocket),
        )
        for index, pocket in enumerate(pockets, start=1)
    )
    return DetectorEvaluationRecord(
        EVALUATOR_SCHEMA_VERSION,
        "biovoid_static",
        structure_id.upper(),
        "completed",
        normalized,
        provenance=provenance,
    )


def adapt_biovoid_product_pockets(
    structure_id: str,
    pockets: list[dict[str, Any]],
    *,
    provenance: dict[str, Any] | None = None,
) -> DetectorEvaluationRecord:
    """Adapt only pockets ranked by the same contract exposed to product users."""
    for pocket in pockets:
        if pocket.get("ranking_contract_version") != PRODUCT_RANKING_CONTRACT_VERSION:
            raise ValueError(
                f"Product evaluation requires pockets ranked by {PRODUCT_RANKING_CONTRACT_VERSION}"
            )
        if pocket.get("bio_score") is None or pocket.get("rank") is None:
            raise ValueError("Product evaluation requires bio_score and rank")
    merged_provenance = {
        **(provenance or {}),
        "ranking_contract_version": PRODUCT_RANKING_CONTRACT_VERSION,
    }
    return adapt_biovoid_pockets(
        structure_id,
        pockets,
        provenance=merged_provenance,
    )


def adapt_fpocket_pockets(
    structure_id: str,
    pockets: list[dict[str, Any]],
    *,
    provenance: dict[str, Any] | None = None,
) -> DetectorEvaluationRecord:
    normalized = tuple(
        EvaluatorPocket(
            pocket_id=f"fpocket-{pocket.get('pocket_id', pocket.get('id', index))}",
            center=_center(pocket["center"]),
            volume=float(pocket["volume"]) if pocket.get("volume") is not None else None,
            rank=int(
                pocket.get(
                    "rank",
                    pocket.get("pocket_id", pocket.get("id", index)),
                )
            ),
            score=float(pocket["score"]) if pocket.get("score") is not None else None,
            raw=_validated_raw(pocket),
        )
        for index, pocket in enumerate(pockets, start=1)
    )
    return DetectorEvaluationRecord(
        EVALUATOR_SCHEMA_VERSION,
        "fpocket",
        structure_id.upper(),
        "completed",
        normalized,
        provenance=provenance,
    )


def adapt_p2rank_rows(
    structure_id: str,
    rows: list[dict[str, Any]],
    *,
    provenance: dict[str, Any] | None = None,
) -> DetectorEvaluationRecord:
    normalized = tuple(
        EvaluatorPocket(
            pocket_id=f"p2rank-{row.get('rank', index)}",
            center=(
                float(row["center_x"]),
                float(row["center_y"]),
                float(row["center_z"]),
            ),
            volume=float(row["volume"]) if row.get("volume") is not None else None,
            rank=int(row.get("rank", index)),
            score=float(row["score"]) if row.get("score") is not None else None,
            raw=_validated_raw(row),
        )
        for index, row in enumerate(rows, start=1)
    )
    return DetectorEvaluationRecord(
        EVALUATOR_SCHEMA_VERSION,
        "p2rank",
        structure_id.upper(),
        "completed",
        normalized,
        provenance=provenance,
    )


def adapt_biovoid_motion_pockets(
    structure_id: str,
    pockets: list[dict[str, Any]],
    *,
    provenance: dict[str, Any] | None = None,
) -> DetectorEvaluationRecord:
    normalized = tuple(
        EvaluatorPocket(
            pocket_id=str(pocket.get("motion_pocket_id", pocket.get("pocket_id", index))),
            center=_center(pocket["center"]),
            volume=(
                float(pocket["volume_mean"]) if pocket.get("volume_mean") is not None else None
            ),
            rank=int(pocket.get("rank", index)),
            score=None,
            raw=_validated_raw(pocket),
        )
        for index, pocket in enumerate(pockets, start=1)
    )
    return DetectorEvaluationRecord(
        EVALUATOR_SCHEMA_VERSION,
        "biovoid_motion",
        structure_id.upper(),
        "completed",
        normalized,
        provenance=provenance,
    )


def unavailable_record(
    detector: DetectorName,
    structure_id: str,
    reason: str,
) -> DetectorEvaluationRecord:
    return DetectorEvaluationRecord(
        EVALUATOR_SCHEMA_VERSION,
        detector,
        structure_id.upper(),
        "unavailable",
        (),
        reason,
    )


def failed_record(
    detector: DetectorName,
    structure_id: str,
    reason: str,
) -> DetectorEvaluationRecord:
    return DetectorEvaluationRecord(
        EVALUATOR_SCHEMA_VERSION,
        detector,
        structure_id.upper(),
        "failed",
        (),
        reason,
    )
