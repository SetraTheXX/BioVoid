#!/usr/bin/env python3
"""
Publication Reproducibility Bundle Builder
===========================================

Collects canonical validation artifacts into a self-contained
reproducibility bundle with SHA-256 manifest for publication
handoff.

Outputs:
  - artifacts/publication_repro_bundle_v1/  (copied files)
  - artifacts/publication_repro_bundle_v1/manifest.json
  - docs/publication_repro_bundle_v1.md
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
BUNDLE_DIR = REPO_ROOT / "artifacts" / "publication_repro_bundle_v1"
MANIFEST_PATH = BUNDLE_DIR / "manifest.json"
OUTPUT_MD = REPO_ROOT / "docs" / "publication_repro_bundle_v1.md"

BUNDLE_FILES = [
    "docs/phase5_5_gate_decision.md",
    "docs/recovery_v2_regression_guard_report.md",
    "docs/scientific_validation_plan_v1.md",
    "docs/scientific_evidence_report_v1.md",
    "docs/sensitivity_sweeps_v1_report.md",
    "docs/artifact_integrity_chain_v1.md",
    "docs/sot_alignment_guard_report.md",
    "data/validation/pre_registered_config.json",
    "data/validation/validation_results.json",
    "data/validation/recovery_v2_regression_guard.json",
    "data/validation/sensitivity_sweeps_v1.json",
    "data/validation/artifact_hash_manifest_v1.json",
    "data/validation/sot_alignment_guard.json",
    "data/validation/fpocket_known20_direct_eval.json",
    "data/validation/fpocket_known20_pairing.json",
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
    print("[INFO] Building publication reproducibility bundle v1...")

    # Create bundle dir (clean if exists)
    if BUNDLE_DIR.exists():
        shutil.rmtree(BUNDLE_DIR)
    BUNDLE_DIR.mkdir(parents=True, exist_ok=True)

    entries: list[dict[str, Any]] = []
    n_copied = 0
    n_missing = 0

    for rel in BUNDLE_FILES:
        src = REPO_ROOT / rel
        # Flatten into bundle dir preserving relative path structure
        dst = BUNDLE_DIR / rel
        dst.parent.mkdir(parents=True, exist_ok=True)

        if src.exists():
            shutil.copy2(src, dst)
            sha = _sha256(dst)
            size = dst.stat().st_size
            n_copied += 1
            status = "copied"
            print(f"  [OK] {rel}")
        else:
            sha = None
            size = None
            n_missing += 1
            status = "missing"
            print(f"  [WARN] Missing: {rel}")

        entries.append({
            "relative_path": rel,
            "sha256": sha,
            "size_bytes": size,
            "status": status,
        })

    # Write manifest
    manifest = {
        "generated_at_utc": _utc_now_iso(),
        "bundle_version": "v1",
        "total_files": len(entries),
        "copied": n_copied,
        "missing": n_missing,
        "files": entries,
    }
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    print(f"[INFO] Wrote manifest: {MANIFEST_PATH}")

    # Write summary doc
    lines = [
        "# Publication Reproducibility Bundle v1",
        "",
        f"- Generated: {_utc_now_iso()}",
        f"- Bundle path: `artifacts/publication_repro_bundle_v1/`",
        f"- Total files: {len(entries)}",
        f"- Copied: {n_copied}",
        f"- Missing: {n_missing}",
        "",
        "---",
        "",
        "## Contents",
        "",
        "| # | File | SHA-256 | Size | Status |",
        "|---|------|---------|------|--------|",
    ]
    for i, e in enumerate(entries, 1):
        sha_short = e["sha256"][:16] + "..." if e["sha256"] else "—"
        size_str = f"{e['size_bytes']:,}" if e["size_bytes"] is not None else "—"
        lines.append(
            f"| {i} | `{e['relative_path']}` | `{sha_short}` | {size_str} | {e['status']} |"
        )

    lines += [
        "",
        "---",
        "",
        "## Verification",
        "",
        "To rebuild this bundle:",
        "",
        "```bash",
        "python scripts/build_publication_repro_bundle.py",
        "```",
        "",
        "To verify integrity, compare SHA-256 hashes in "
        "`artifacts/publication_repro_bundle_v1/manifest.json` against the source files.",
        "",
        "## Bundle Completeness",
        "",
    ]
    if n_missing == 0:
        lines.append("**All files present.** Bundle is complete and ready for publication handoff.")
    else:
        lines.append(f"**{n_missing} file(s) missing.** Bundle is incomplete.")
    lines.append("")

    OUTPUT_MD.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[INFO] Wrote: {OUTPUT_MD}")

    print(f"\n[DONE] Publication repro bundle: {n_copied} copied, {n_missing} missing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
