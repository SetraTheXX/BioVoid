"""Validate a local RI-2 manifest without loading any structure data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.cryptobench_manifest import validate_manifest_payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "manifest",
        nargs="?",
        type=Path,
        default=REPO_ROOT / "data/runtime/ri2/cryptobench-development-manifest-v1.json",
    )
    args = parser.parse_args()
    payload = json.loads(args.manifest.read_text(encoding="utf-8"))
    validate_manifest_payload(payload)
    cases = payload["cases"]
    status_counts = {}
    for case in cases:
        status = case["eligibility"]["status"]
        status_counts[status] = status_counts.get(status, 0) + 1
    print("RI-2 manifest contract: PASS")
    print(f"cases: {len(cases)}")
    print(f"eligibility: {status_counts}")
    print(f"manifest sha256: {payload['manifest_sha256']}")
    print("evaluator fields: absent")
    print("sealed case rows: closed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
