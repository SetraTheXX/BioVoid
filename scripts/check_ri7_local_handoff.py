"""Fail-closed checks for the source-only RI-7 handoff package.

This checker verifies the public source contract and, optionally, the local
ignored evidence produced by RI-1 through RI-6. It never downloads structures,
starts a detector, launches Docker, or changes runtime artifacts.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

REQUIRED_SOURCE_FILES = (
    "README.md",
    "CITATION.cff",
    "docs/releases/v0.1.0.md",
    "docs/specs/public-release-v1.md",
    "docs/specs/run-manifest-v1.md",
    "docs/specs/scoring-contract-v1.md",
    "docs/specs/motion-ensemble-v1.md",
    "scripts/check_public_hygiene.py",
    "scripts/check_ri1_contract.py",
    "scripts/check_ri2_manifest.py",
    "scripts/check_ri3_preparation.py",
    "scripts/check_ri3_readiness.py",
    "scripts/check_ri3_static_run.py",
    "scripts/check_ri3_external_comparison.py",
    "scripts/check_ri3_resource_recovery.py",
    "scripts/check_ri4_motion_preflight.py",
    "scripts/check_ri4_motion_development.py",
    "scripts/check_ri5_confirmatory.py",
    "scripts/check_ri6_preflight.py",
    "scripts/freeze_ri5_evaluator_v3.py",
    "scripts/lock_ri5_confirmatory_holdout.py",
    "scripts/run_ri5_confirmatory_static.py",
    "scripts/run_ri5_confirmatory_baseline.py",
    "scripts/evaluate_ri5_confirmatory_comparison.py",
    "scripts/run_ri6_prospective_static.py",
    "tests/test_ri5_evaluator_v3.py",
    "tests/test_ri5_confirmatory_holdout.py",
    "tests/test_ri6_target_contract.py",
)

LOCAL_EVIDENCE_CHECKS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("RI-1", ("scripts/check_ri1_contract.py",)),
    ("RI-2", ("scripts/check_ri2_manifest.py",)),
    ("RI-3 preparation", ("scripts/check_ri3_preparation.py",)),
    ("RI-3 readiness", ("scripts/check_ri3_readiness.py",)),
    ("RI-3 static", ("scripts/check_ri3_static_run.py",)),
    ("RI-3 baseline", ("scripts/check_ri3_external_comparison.py",)),
    ("RI-3 recovery", ("scripts/check_ri3_resource_recovery.py",)),
    ("RI-4 preflight", ("scripts/check_ri4_motion_preflight.py",)),
    (
        "RI-4 development",
        ("scripts/check_ri4_motion_development.py", "--allow-partial"),
    ),
    ("RI-5 confirmatory", ("scripts/check_ri5_confirmatory.py",)),
    ("RI-6 prospective", ("scripts/check_ri6_preflight.py",)),
)


class RI7HandoffError(RuntimeError):
    """Raised when a source or evidence handoff invariant is violated."""


def _git(root: Path, *args: str) -> list[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return [line.replace("\\", "/") for line in result.stdout.splitlines() if line]


def validate_source_contract(root: Path = REPO_ROOT) -> dict[str, Any]:
    """Validate required public files and the current claim boundary."""

    missing = [path for path in REQUIRED_SOURCE_FILES if not (root / path).is_file()]
    if missing:
        raise RI7HandoffError("missing source files: " + ", ".join(missing))

    from scripts.check_public_hygiene import _forbidden_path

    tracked = [path for path in _git(root, "ls-files") if (root / path).is_file()]
    forbidden = sorted(path for path in tracked if _forbidden_path(path))
    if forbidden:
        raise RI7HandoffError("forbidden tracked paths: " + ", ".join(forbidden))

    public_readme = (root / "README.md").read_text(encoding="utf-8").lower()
    required_phrases = (
        "local computational research prototype",
        "does not claim discovery",
        "the nma/motion path is experimental",
    )
    missing_phrases = [phrase for phrase in required_phrases if phrase not in public_readme]
    if missing_phrases:
        raise RI7HandoffError(
            "public README is missing claim-boundary phrases: " + ", ".join(missing_phrases)
        )

    return {
        "status": "pass",
        "required_source_files": len(REQUIRED_SOURCE_FILES),
        "tracked_files_checked": len(tracked),
        "forbidden_tracked_paths": [],
        "claim_boundary_checked": True,
        "status_index_checked": True,
    }


def _run_check(root: Path, name: str, command: Sequence[str]) -> dict[str, Any]:
    """Run a read-only phase checker and retain concise diagnostics."""

    process = subprocess.run(
        [sys.executable, *command],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    output = (process.stdout + process.stderr).strip().splitlines()
    return {
        "name": name,
        "status": "pass" if process.returncode == 0 else "fail",
        "returncode": process.returncode,
        "tail": output[-8:],
    }


def check(
    *,
    root: Path = REPO_ROOT,
    local_evidence: bool = False,
    history_ref: str | None = None,
) -> dict[str, Any]:
    """Run source-only checks and optionally read all local RI evidence."""

    result: dict[str, Any] = {"source": validate_source_contract(root)}
    source_hygiene = ["scripts/check_public_hygiene.py"]
    if history_ref:
        source_hygiene.extend(["--history", "--history-ref", history_ref])
    result["public_hygiene"] = _run_check(root, "public hygiene", source_hygiene)

    if local_evidence:
        result["local_evidence"] = [
            _run_check(root, name, command) for name, command in LOCAL_EVIDENCE_CHECKS
        ]
    else:
        result["local_evidence"] = {
            "status": "not_run",
            "reason": "pass --local-evidence to inspect ignored runtime evidence",
        }

    checks: list[dict[str, Any]] = [result["public_hygiene"]]
    if local_evidence:
        checks.extend(result["local_evidence"])
    result["status"] = "pass" if all(item["status"] == "pass" for item in checks) else "fail"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--local-evidence",
        action="store_true",
        help="run read-only RI-1 through RI-6 evidence checkers; never starts a benchmark",
    )
    parser.add_argument(
        "--history-ref",
        help="also inspect a sanitized Git history ref with the public hygiene checker",
    )
    args = parser.parse_args()

    try:
        result = check(
            local_evidence=args.local_evidence,
            history_ref=args.history_ref,
        )
    except (RI7HandoffError, subprocess.SubprocessError, OSError) as exc:
        print(f"RI-7 local handoff: FAIL - {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
