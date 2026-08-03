#!/usr/bin/env python3
"""
Publication Reproducibility Bundle Verifier
============================================

Verifies the integrity of the publication reproducibility bundle
by checking file existence, SHA-256 hashes, and manifest consistency.

Outputs:
  - data/validation/publication_repro_verify_v1.json
  - docs/publication_repro_verify_v1.md

Exit codes:
  0 = all checks pass
  1 = one or more checks fail
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
BUNDLE_DIR = REPO_ROOT / "artifacts" / "publication_repro_bundle_v1"
MANIFEST_PATH = BUNDLE_DIR / "manifest.json"
OUTPUT_JSON = REPO_ROOT / "data" / "validation" / "publication_repro_verify_v1.json"
OUTPUT_MD = REPO_ROOT / "docs" / "publication_repro_verify_v1.md"


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
    print("[INFO] Verifying publication reproducibility bundle v1...")

    errors: list[str] = []
    checks: list[dict[str, Any]] = []

    # 1. Manifest exists
    if not MANIFEST_PATH.exists():
        errors.append(f"Manifest not found: {MANIFEST_PATH}")
        print(f"[FAIL] Manifest not found: {MANIFEST_PATH}")
        _write_outputs("FAIL", errors, checks, 0)
        return 1

    # 2. Load manifest
    try:
        with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        errors.append(f"Cannot parse manifest: {exc}")
        print(f"[FAIL] Cannot parse manifest: {exc}")
        _write_outputs("FAIL", errors, checks, 0)
        return 1

    # 3. Schema sanity
    required_keys = ["total_files", "copied", "missing", "files"]
    for key in required_keys:
        present = key in manifest
        checks.append({"check": f"manifest_has_{key}", "pass": present})
        if not present:
            errors.append(f"Manifest missing key: {key}")

    files_list = manifest.get("files", [])
    total_files = manifest.get("total_files", 0)
    copied = manifest.get("copied", 0)
    missing = manifest.get("missing", 0)

    # 4. File count consistency
    count_ok = total_files == len(files_list)
    checks.append({"check": "file_count_consistency", "pass": count_ok,
                    "detail": f"total_files={total_files}, len(files)={len(files_list)}"})
    if not count_ok:
        errors.append(f"File count mismatch: total_files={total_files} vs len(files)={len(files_list)}")

    # 5. Missing == 0
    no_missing = missing == 0
    checks.append({"check": "no_missing_files", "pass": no_missing,
                    "detail": f"missing={missing}"})
    if not no_missing:
        errors.append(f"Bundle has {missing} missing file(s)")

    # 6. Per-file existence + SHA-256 verification
    hash_mismatches = 0
    file_missing = 0
    for entry in files_list:
        rel = entry.get("relative_path", "")
        expected_sha = entry.get("sha256")
        bundle_path = BUNDLE_DIR / rel

        exists = bundle_path.exists()
        if not exists:
            file_missing += 1
            checks.append({"check": f"file_exists:{rel}", "pass": False})
            errors.append(f"File missing in bundle: {rel}")
            continue

        actual_sha = _sha256(bundle_path)
        sha_ok = actual_sha == expected_sha
        checks.append({"check": f"sha256_match:{rel}", "pass": sha_ok,
                        "expected": expected_sha, "actual": actual_sha})
        if not sha_ok:
            hash_mismatches += 1
            errors.append(f"SHA-256 mismatch: {rel}")

    print(f"[INFO] Files checked: {len(files_list)}")
    print(f"[INFO] Hash mismatches: {hash_mismatches}")
    print(f"[INFO] Files missing: {file_missing}")

    status = "PASS" if len(errors) == 0 else "FAIL"
    print(f"[INFO] Status: {status}")

    if errors:
        for e in errors:
            print(f"  [FAIL] {e}")

    _write_outputs(status, errors, checks, len(files_list))

    print(f"\n[DONE] Bundle verification: {status}")
    return 0 if status == "PASS" else 1


def _write_outputs(
    status: str, errors: list[str], checks: list[dict], files_checked: int
) -> None:
    output = {
        "generated_at_utc": _utc_now_iso(),
        "status": status,
        "files_checked": files_checked,
        "errors_count": len(errors),
        "errors": errors,
        "checks": checks,
    }
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"[INFO] Wrote: {OUTPUT_JSON}")

    lines = [
        "# Publication Reproducibility Bundle Verification v1",
        "",
        f"- Generated: {_utc_now_iso()}",
        f"- Status: **{status}**",
        f"- Files checked: {files_checked}",
        f"- Errors: {len(errors)}",
        "",
        "---",
        "",
    ]
    if errors:
        lines.append("## Errors")
        lines.append("")
        for i, e in enumerate(errors, 1):
            lines.append(f"{i}. {e}")
        lines.append("")
    else:
        lines.append("## Result")
        lines.append("")
        lines.append("All files present and SHA-256 hashes match. Bundle is verified.")
        lines.append("")

    lines += [
        "---",
        "",
        "## Checks Detail",
        "",
        "| # | Check | Pass |",
        "|---|-------|------|",
    ]
    for i, c in enumerate(checks, 1):
        p = "YES" if c["pass"] else "**NO**"
        lines.append(f"| {i} | `{c['check']}` | {p} |")
    lines.append("")

    OUTPUT_MD.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[INFO] Wrote: {OUTPUT_MD}")


if __name__ == "__main__":
    sys.exit(main())
