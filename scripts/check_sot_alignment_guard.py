#!/usr/bin/env python3
"""
SoT Alignment Guard
====================

Scans active docs and scripts for overlap threshold claims that
conflict with the Source of Truth (pre_registered_config.json).

Fails if any active file contains a strict-gate claim equivalent
to `overlap >= 0.40` as current SoT without a legacy marker
(legacy, formerly, eski).

Outputs:
  - data/validation/sot_alignment_guard.json
  - docs/sot_alignment_guard_report.md
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
PRE_REG = REPO_ROOT / "data" / "validation" / "pre_registered_config.json"
OUTPUT_JSON = REPO_ROOT / "data" / "validation" / "sot_alignment_guard.json"
OUTPUT_MD = REPO_ROOT / "docs" / "sot_alignment_guard_report.md"

SCAN_DIRS = [
    REPO_ROOT / "docs",
    REPO_ROOT / "scripts",
]
EXCLUDE_PATTERNS = [
    "**/archive/**",
    "**/__pycache__/**",
    "**/*.pyc",
]
SCAN_EXTENSIONS = {".md", ".py", ".txt"}

# Legacy markers — if a line contains one of these near the 0.40 reference,
# it is treated as an acknowledged historical mention, not a drift error.
LEGACY_MARKERS = ["legacy", "formerly", "eski", "eski gate", "old gate", "revised"]

# Files to skip (self-references in guard code/report)
SELF_WHITELIST = {
    "scripts/check_sot_alignment_guard.py",
    "docs/sot_alignment_guard_report.md",
}

# Pattern: overlap threshold claim with 0.40
# Matches things like: overlap >= 0.40, threshold 0.40, gate 0.40,
# min_fpocket_overlap.*0.40, overlap.*0.40
DRIFT_PATTERNS = [
    re.compile(r"overlap\s*>=?\s*0\.40", re.IGNORECASE),
    re.compile(r"threshold[^0-9]*0\.40", re.IGNORECASE),
    re.compile(r"gate[^0-9]*0\.40", re.IGNORECASE),
    re.compile(r"min_fpocket_overlap[^0-9]*0\.40", re.IGNORECASE),
]

# FPR threshold sweep grid mentions 0.40 for FPR, not overlap — whitelist
FPR_WHITELIST = [
    re.compile(r"fpr.*0\.40", re.IGNORECASE),
    re.compile(r"FPR_THRESHOLD_GRID", re.IGNORECASE),
    re.compile(r"fpr_threshold.*0\.40", re.IGNORECASE),
    re.compile(r"weighted_score.*0\.40", re.IGNORECASE),
]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_json(path: Path) -> Any | None:
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _is_excluded(path: Path) -> bool:
    rel = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    if "archive/" in rel or "archive\\" in rel:
        return True
    if "__pycache__" in rel:
        return True
    return False


def _has_legacy_marker(line: str) -> bool:
    low = line.lower()
    return any(m in low for m in LEGACY_MARKERS)


def _is_fpr_context(line: str) -> bool:
    return any(p.search(line) for p in FPR_WHITELIST)


def scan_file(path: Path) -> list[dict[str, Any]]:
    """Scan a single file for SoT drift violations."""
    violations: list[dict[str, Any]] = []
    rel = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    if rel in SELF_WHITELIST:
        return violations
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return violations

    for i, line in enumerate(lines, 1):
        for pattern in DRIFT_PATTERNS:
            if pattern.search(line):
                # Check if it's a FPR context (not overlap)
                if _is_fpr_context(line):
                    continue
                # Check if it has a legacy marker
                if _has_legacy_marker(line):
                    continue
                violations.append({
                    "file": str(path.relative_to(REPO_ROOT)).replace("\\", "/"),
                    "line": i,
                    "content": line.strip()[:200],
                    "pattern": pattern.pattern,
                })
    return violations


def main() -> int:
    print("[INFO] Running SoT alignment guard...")

    # Load SoT
    pre_reg = _load_json(PRE_REG)
    if not pre_reg:
        print("[ERROR] Cannot load pre_registered_config.json")
        return 1

    decision_gates = pre_reg.get("decision_gates", {})
    sot_overlap = decision_gates.get("min_fpocket_overlap", "NOT_SET")
    sot_snapshot = {
        "min_recall": decision_gates.get("min_recall"),
        "min_fpocket_overlap": sot_overlap,
        "max_false_positive_rate": decision_gates.get("max_false_positive_rate"),
        "min_md_validated_proteins": decision_gates.get("min_md_validated_proteins"),
    }
    print(f"[INFO] SoT overlap threshold: {sot_overlap}")

    # Collect files to scan
    files_to_scan: list[Path] = []
    for scan_dir in SCAN_DIRS:
        if not scan_dir.exists():
            continue
        for ext in SCAN_EXTENSIONS:
            for f in scan_dir.rglob(f"*{ext}"):
                if not _is_excluded(f):
                    files_to_scan.append(f)

    print(f"[INFO] Scanning {len(files_to_scan)} files...")

    # Scan
    all_violations: list[dict[str, Any]] = []
    checked_files: list[str] = []
    for f in sorted(files_to_scan):
        rel = str(f.relative_to(REPO_ROOT)).replace("\\", "/")
        checked_files.append(rel)
        violations = scan_file(f)
        all_violations.extend(violations)

    # Determine status
    errors = [v for v in all_violations]
    status = "PASS" if len(errors) == 0 else "FAIL"

    print(f"[INFO] Status: {status}")
    if errors:
        print(f"[WARN] {len(errors)} SoT drift violation(s) found:")
        for e in errors:
            print(f"  {e['file']}:{e['line']} — {e['content'][:80]}")
    else:
        print("[INFO] No SoT drift violations found.")

    # Write JSON
    output = {
        "generated_at_utc": _utc_now_iso(),
        "status": status,
        "sot_snapshot": sot_snapshot,
        "checked_files_count": len(checked_files),
        "checked_files": checked_files,
        "errors": errors,
        "warnings": [],
    }
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"[INFO] Wrote: {OUTPUT_JSON}")

    # Write report
    lines = [
        "# SoT Alignment Guard Report",
        "",
        f"- Generated: {_utc_now_iso()}",
        f"- Status: **{status}**",
        f"- SoT overlap threshold: `{sot_overlap}`",
        f"- Files scanned: {len(checked_files)}",
        f"- Violations: {len(errors)}",
        "",
        "---",
        "",
        "## SoT Snapshot",
        "",
        "| Parameter | Value |",
        "|-----------|-------|",
    ]
    for k, v in sot_snapshot.items():
        lines.append(f"| `{k}` | `{v}` |")

    lines += ["", "---", ""]

    if errors:
        lines.append("## Violations")
        lines.append("")
        lines.append("| # | File | Line | Content |")
        lines.append("|---|------|------|---------|")
        for i, e in enumerate(errors, 1):
            content = e["content"][:80].replace("|", "\\|")
            lines.append(f"| {i} | `{e['file']}` | {e['line']} | {content} |")
        lines.append("")
    else:
        lines.append("## Result")
        lines.append("")
        lines.append("No SoT drift violations found. All active docs and scripts are aligned with `pre_registered_config.json`.")
        lines.append("")

    lines += [
        "---",
        "",
        "## Guard Rules",
        "",
        "1. Active files must not claim `overlap >= 0.40` as current SoT.",
        "2. Historical mentions are allowed if marked with: `legacy`, `formerly`, `eski`.",
        "3. Archive files (`docs/archive/**`) are excluded from scanning.",
        "4. FPR threshold sweep grids containing `0.40` are whitelisted (not overlap).",
        "",
    ]

    OUTPUT_MD.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[INFO] Wrote: {OUTPUT_MD}")

    print(f"\n[DONE] SoT alignment guard: {status}")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
