"""Freeze evaluator v3 from complete development-only structural recovery evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.evaluator_v3 import build_development_eligibility_lock  # noqa: E402


DEFAULT_RECOVERY = REPO_ROOT / (
    "data/runtime/ri3/ri3-static-development-evaluation-structural-recovery-v1.json"
)
DEFAULT_OUTPUT = REPO_ROOT / "data/runtime/ri5-confirmatory/evaluator-v3-development-lock-v1.json"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recovery", type=Path, default=DEFAULT_RECOVERY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    recovery = json.loads(args.recovery.read_text(encoding="utf-8"))
    payload = build_development_eligibility_lock(
        recovery,
        recovery_file_sha256=_sha256_file(args.recovery),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(args.output)
    print(
        "RI-5.1 evaluator v3 frozen: "
        f"eligible={payload['eligible_case_count']} "
        f"ineligible={payload['ineligible_case_count']}"
    )
    print(f"lock_sha256={payload['lock_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

