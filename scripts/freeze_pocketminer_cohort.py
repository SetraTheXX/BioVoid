"""Freeze the PocketMiner metadata allocation into private cohort metadata.

This command consumes the already sealed metadata-only source/catalog report.
It writes evaluator-side private metadata and a redacted apo-only detector
manifest, then performs readiness validation. It downloads no structures and
starts no detector, evaluator, model, NMA, baseline, or ML computation.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.audit_pocketminer_source_catalog import (  # noqa: E402
    PocketMinerCatalogError,
    build_pocketminer_cohort_payload,
)
from src.target_family_cohort import (  # noqa: E402
    CohortContractError,
    assess_cohort_readiness,
    build_target_blind_manifest,
)


DEFAULT_CATALOG = (
    REPO_ROOT / "local-private/research/ranking-study-source-catalog/pocketminer-v1/"
    "pocketminer-source-catalog-v1.json"
)
DEFAULT_COHORT = (
    REPO_ROOT / "local-private/research/ranking-study-source-catalog/pocketminer-v1/"
    "pocketminer-cohort-v1.json"
)
DEFAULT_READINESS = (
    REPO_ROOT / "data/runtime/ranking-study/pocketminer-v1/pocketminer-cohort-readiness-v1.json"
)
DEFAULT_DETECTOR = (
    REPO_ROOT / "data/runtime/ranking-study/pocketminer-v1/pocketminer-detector-manifest-v1.json"
)
DEFAULT_FAMILY_ID = "POCKETMINER-NOVEL-CRYPTIC"


class PocketMinerCohortFreezeError(RuntimeError):
    """Raised when a sealed PocketMiner catalog cannot produce a cohort."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PocketMinerCohortFreezeError(f"cannot read catalog: {path}") from exc
    if not isinstance(value, dict):
        raise PocketMinerCohortFreezeError("catalog JSON must be an object")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def freeze_pocketminer_cohort(
    *,
    catalog_path: Path = DEFAULT_CATALOG,
    cohort_path: Path = DEFAULT_COHORT,
    readiness_path: Path = DEFAULT_READINESS,
    detector_path: Path = DEFAULT_DETECTOR,
    family_id: str = DEFAULT_FAMILY_ID,
) -> dict[str, Any]:
    catalog = _read_json(catalog_path.resolve())
    try:
        cohort = build_pocketminer_cohort_payload(catalog, family_id=family_id)
        readiness = assess_cohort_readiness(cohort, minimum_cases=6)
        detector_manifest = build_target_blind_manifest(cohort)
    except (PocketMinerCatalogError, CohortContractError, ValueError) as exc:
        raise PocketMinerCohortFreezeError(str(exc)) from exc
    readiness_payload = {
        **readiness,
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source_catalog_path": str(catalog_path),
        "source_catalog_sha256": _sha256_file(catalog_path.resolve()),
        "cohort_sha256": cohort["cohort_sha256"],
        "detector_manifest_sha256": detector_manifest["manifest_sha256"],
        "detector_manifest_written": True,
        "coordinates_downloaded": False,
        "detector_started": False,
        "evaluator_started": False,
        "model_inference_started": False,
        "nma_started": False,
        "ml_training_started": False,
    }
    _write_json(cohort_path.resolve(), cohort)
    _write_json(readiness_path.resolve(), readiness_payload)
    _write_json(detector_path.resolve(), detector_manifest)
    print(
        f"PocketMiner cohort freeze: {readiness['status']} "
        f"cases={readiness['case_count']} splits={readiness['split_counts']}"
    )
    print(f"private cohort: {cohort_path}")
    print(f"readiness report: {readiness_path}")
    print(f"apo-only detector manifest: {detector_path}")
    print("coordinates/detector/evaluator/model/NMA/ML started: no")
    return readiness_payload


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--cohort", type=Path, default=DEFAULT_COHORT)
    parser.add_argument("--readiness", type=Path, default=DEFAULT_READINESS)
    parser.add_argument("--detector", type=Path, default=DEFAULT_DETECTOR)
    parser.add_argument("--family-id", default=DEFAULT_FAMILY_ID)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        freeze_pocketminer_cohort(
            catalog_path=args.catalog,
            cohort_path=args.cohort,
            readiness_path=args.readiness,
            detector_path=args.detector,
            family_id=args.family_id,
        )
    except (PocketMinerCohortFreezeError, OSError) as exc:
        print(f"PocketMiner cohort freeze error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
