"""Freeze target-blind and evaluator-only locks for the train-3 holdout."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.confirmatory_holdout import build_confirmatory_locks  # noqa: E402
from src.evaluator_v3 import stable_hash, validate_development_eligibility_lock  # noqa: E402


DEFAULT_METADATA_DIR = REPO_ROOT / "data/runtime/cryptobench-source/metadata"
DEFAULT_RI1_LOCK = REPO_ROOT / "local-private/research/ri-1-lock-v1.json"
DEFAULT_EVALUATOR_V3_LOCK = REPO_ROOT / (
    "data/runtime/ri5-confirmatory/evaluator-v3-development-lock-v1.json"
)
DEFAULT_ROOT = REPO_ROOT / "data/runtime/ri5-confirmatory"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _locked_json(path: Path, expected_sha256: str) -> dict:
    if _sha256_file(path) != expected_sha256:
        raise RuntimeError(f"Locked metadata hash mismatch: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata-dir", type=Path, default=DEFAULT_METADATA_DIR)
    parser.add_argument("--ri1-lock", type=Path, default=DEFAULT_RI1_LOCK)
    parser.add_argument("--evaluator-v3-lock", type=Path, default=DEFAULT_EVALUATOR_V3_LOCK)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args()

    ri1 = json.loads(args.ri1_lock.read_text(encoding="utf-8"))
    metadata = ri1["dataset"]["metadata_files"]
    dataset = _locked_json(args.metadata_dir / "dataset.json", metadata["dataset.json"]["sha256"])
    folds = _locked_json(args.metadata_dir / "folds.json", metadata["folds.json"]["sha256"])
    evaluator_v3 = json.loads(args.evaluator_v3_lock.read_text(encoding="utf-8"))
    validate_development_eligibility_lock(evaluator_v3)
    source, evaluator = build_confirmatory_locks(
        dataset,
        folds,
        snapshot_id=ri1["dataset"]["snapshot_id"],
        evaluator_v3_lock_sha256=evaluator_v3["lock_sha256"],
    )
    _write(args.output_root / "confirmatory-source-lock-v1.json", source)
    _write(args.output_root / "confirmatory-evaluator-lock-v1.json", evaluator)
    open_contract = {
        "schema_version": "biovoid-ri5-confirmatory-open-contract-v1",
        "status": "ready_for_single_authorized_open",
        "source_lock_sha256": source["source_lock_sha256"],
        "evaluator_lock_sha256": evaluator["evaluator_lock_sha256"],
        "evaluator_v3_lock_sha256": evaluator_v3["lock_sha256"],
        "structure_count": source["structure_count"],
        "case_count": source["case_count"],
        "contains_evaluator_fields": False,
    }
    open_contract["open_contract_sha256"] = stable_hash(open_contract)
    _write(args.output_root / "confirmatory-open-contract-v1.json", open_contract)
    print(
        "RI-5.2 confirmatory holdout frozen: "
        f"structures={source['structure_count']} cases={source['case_count']}"
    )
    print(f"source_lock_sha256={source['source_lock_sha256']}")
    print(f"evaluator_lock_sha256={evaluator['evaluator_lock_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
