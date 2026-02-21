#!/usr/bin/env python3
"""
Artifact Hash Manifest Generator
=================================

Computes SHA-256 hashes for all critical validation artifacts to
establish an integrity chain.  This allows reviewers to verify
that no artifact was modified after the validation was completed.

Outputs:
  - data/validation/artifact_hash_manifest_v1.json
  - docs/artifact_integrity_chain_v1.md
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_JSON = REPO_ROOT / "data" / "validation" / "artifact_hash_manifest_v1.json"
OUTPUT_MD = REPO_ROOT / "docs" / "artifact_integrity_chain_v1.md"

# Files to hash (relative to REPO_ROOT)
ARTIFACT_PATHS = [
    "data/validation/pre_registered_config.json",
    "data/validation/known_cryptic_pockets.json",
    "data/benchmark/fpocket_benchmark_v3.json",
    "data/validation/md_validation_1g66.json",
    "data/validation/false_positive_results.json",
    "data/validation/validation_results.json",
    "data/validation/fpocket_known20_direct_eval.json",
    "data/validation/fpocket_known20_pairing.json",
    "data/validation/sensitivity_sweeps_v1.json",
    "docs/phase5_5_gate_decision.md",
    "docs/recovery_v2_regression_guard_report.md",
    "docs/scientific_evidence_report_v1.md",
    "docs/scientific_validation_plan_v1.md",
    "docs/sensitivity_sweeps_v1_report.md",
]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    print("[INFO] Generating artifact hash manifest...")

    entries: list[dict[str, Any]] = []
    n_found = 0
    n_missing = 0

    for rel in ARTIFACT_PATHS:
        full = REPO_ROOT / rel
        sha = _sha256(full)
        size = full.stat().st_size if full.exists() else None
        status = "found" if sha else "missing"
        if sha:
            n_found += 1
        else:
            n_missing += 1
            print(f"  [WARN] Missing: {rel}")

        entries.append({
            "path": rel,
            "sha256": sha,
            "size_bytes": size,
            "status": status,
        })

    manifest = {
        "generated_at_utc": _utc_now_iso(),
        "total_artifacts": len(entries),
        "found": n_found,
        "missing": n_missing,
        "artifacts": entries,
    }

    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    print(f"[INFO] Wrote: {OUTPUT_JSON}")

    # Generate markdown report
    lines = [
        "# Artifact Integrity Chain v1",
        "",
        f"- Generated: {_utc_now_iso()}",
        f"- Total artifacts: {len(entries)}",
        f"- Found: {n_found}",
        f"- Missing: {n_missing}",
        "",
        "---",
        "",
        "## SHA-256 Hashes",
        "",
        "| # | Artifact | SHA-256 | Size | Status |",
        "|---|----------|---------|------|--------|",
    ]
    for i, e in enumerate(entries, 1):
        sha_short = e["sha256"][:16] + "..." if e["sha256"] else "—"
        size_str = f"{e['size_bytes']:,}" if e["size_bytes"] is not None else "—"
        lines.append(
            f"| {i} | `{e['path']}` | `{sha_short}` | {size_str} | {e['status']} |"
        )

    lines += [
        "",
        "---",
        "",
        "## Verification",
        "",
        "To verify artifact integrity, run:",
        "",
        "```bash",
        "python scripts/generate_artifact_hash_manifest.py",
        "```",
        "",
        "Then compare the output `data/validation/artifact_hash_manifest_v1.json` "
        "against this document. Any SHA-256 mismatch indicates the artifact was "
        "modified after the manifest was generated.",
        "",
        "## Full Hashes",
        "",
        "```",
    ]
    for e in entries:
        sha = e["sha256"] or "MISSING"
        lines.append(f"{sha}  {e['path']}")
    lines += [
        "```",
        "",
    ]

    OUTPUT_MD.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[INFO] Wrote: {OUTPUT_MD}")

    print(f"\n[DONE] Artifact hash manifest: {n_found} found, {n_missing} missing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
