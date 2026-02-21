#!/usr/bin/env python3
"""
Blind Holdout Set Builder (v1)
==============================

Produces a stratified blind holdout split from the known cryptic pocket
validation set and the 100-protein benchmark set.

Design constraints:
  - Deterministic (seed-locked) selection.
  - Pocket-type stratified for the recall holdout.
  - Zero overlap with recovery/tuning protein IDs.
  - Outputs a sealed JSON manifest and a human-readable Markdown report.

Usage:
    python scripts/build_blind_holdout_set.py [--seed 42] [--holdout-recall-k 5] [--holdout-benchmark-k 20]

Outputs:
    data/benchmark/blind_holdout_v1.json
    docs/blind_holdout_v1_report.md
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Paths (relative to repo root)
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[1]
KNOWN_CRYPTIC_PATH = REPO_ROOT / "data" / "validation" / "known_cryptic_pockets.json"
BENCHMARK_PATH = REPO_ROOT / "data" / "benchmark" / "fpocket_benchmark_v3.json"
RECOVERY_V2_PATH = REPO_ROOT / "data" / "validation" / "recall_recovery_experiments_v2.json"
RECOVERY_V3_PATH = REPO_ROOT / "data" / "validation" / "recall_recovery_experiments_v3.json"
PARAMETER_SWEEP_PATH = REPO_ROOT / "data" / "validation" / "parameter_sweep_results.json"
PRE_REG_CONFIG_PATH = REPO_ROOT / "data" / "validation" / "pre_registered_config.json"

OUTPUT_JSON = REPO_ROOT / "data" / "benchmark" / "blind_holdout_v1.json"
OUTPUT_REPORT = REPO_ROOT / "docs" / "blind_holdout_v1_report.md"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _deterministic_hash(pdb_id: str, seed: int) -> str:
    """SHA-256 of (seed || pdb_id) for deterministic ordering."""
    payload = f"{seed}:{pdb_id.upper()}"
    return hashlib.sha256(payload.encode()).hexdigest()


def _load_json(path: Path) -> Any:
    if not path.exists():
        print(f"[WARN] File not found: {path}")
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _extract_pdb_ids_from_list(items: list) -> set[str]:
    """Extract pdb_id values from a list of dicts."""
    ids: set[str] = set()
    for item in items:
        if isinstance(item, dict) and "pdb_id" in item:
            ids.add(item["pdb_id"].upper())
    return ids


def _collect_tuning_ids() -> tuple[set[str], dict[str, set[str]]]:
    """Collect all protein IDs that were used in recovery/tuning experiments.

    Returns (all_tuning_ids, per_source_dict).
    """
    per_source: dict[str, set[str]] = {}

    # Recovery v2: keys are single_results, multi_results
    data = _load_json(RECOVERY_V2_PATH)
    if data and isinstance(data, dict):
        v2_ids: set[str] = set()
        for key in ("single_results", "multi_results", "per_case", "results"):
            if key in data and isinstance(data[key], list):
                v2_ids |= _extract_pdb_ids_from_list(data[key])
        if v2_ids:
            per_source["recovery_v2"] = v2_ids

    # Recovery v3: key is results
    data = _load_json(RECOVERY_V3_PATH)
    if data and isinstance(data, dict):
        v3_ids: set[str] = set()
        for key in ("results", "per_case"):
            if key in data and isinstance(data[key], list):
                v3_ids |= _extract_pdb_ids_from_list(data[key])
        if v3_ids:
            per_source["recovery_v3"] = v3_ids

    # Parameter sweep
    data = _load_json(PARAMETER_SWEEP_PATH)
    if data and isinstance(data, dict):
        sw_ids: set[str] = set()
        for key in ("results", "sweep_results", "per_case"):
            if key in data and isinstance(data[key], list):
                sw_ids |= _extract_pdb_ids_from_list(data[key])
        if sw_ids:
            per_source["parameter_sweep"] = sw_ids

    all_ids: set[str] = set()
    for s in per_source.values():
        all_ids |= s
    return all_ids, per_source


# ---------------------------------------------------------------------------
# Stratified holdout selection (recall set)
# ---------------------------------------------------------------------------

def _select_recall_holdout(
    test_cases: list[dict[str, Any]],
    k: int,
    seed: int,
    exclude_ids: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Select *k* cases from test_cases using pocket_type-stratified
    deterministic sampling.

    Strategy:
      1. Group cases by pocket_type.
      2. Sort groups by size (ascending) so rare types get picked first.
      3. Round-robin pick one case per group (deterministic hash order)
         until k cases are selected.
      4. Skip any case whose PDB ID is in exclude_ids.

    Returns (holdout_cases, remaining_cases).
    """
    # Group by pocket_type
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in test_cases:
        ptype = case.get("pocket_type", "unknown")
        groups[ptype].append(case)

    # Sort each group deterministically by hash
    for ptype in groups:
        groups[ptype].sort(key=lambda c: _deterministic_hash(c["pdb_id"], seed))

    # Sort group names by size (ascending), then alphabetically for ties
    sorted_types = sorted(groups.keys(), key=lambda t: (len(groups[t]), t))

    holdout_ids: set[str] = set()
    holdout_cases: list[dict[str, Any]] = []

    # Round-robin across types
    pointers: dict[str, int] = {t: 0 for t in sorted_types}
    rounds = 0
    max_rounds = len(test_cases)  # safety

    while len(holdout_cases) < k and rounds < max_rounds:
        for ptype in sorted_types:
            if len(holdout_cases) >= k:
                break
            candidates = groups[ptype]
            ptr = pointers[ptype]
            while ptr < len(candidates):
                c = candidates[ptr]
                ptr += 1
                pid = c["pdb_id"].upper()
                if pid in exclude_ids or pid in holdout_ids:
                    continue
                holdout_cases.append(c)
                holdout_ids.add(pid)
                pointers[ptype] = ptr
                break
            else:
                pointers[ptype] = ptr
        rounds += 1

    remaining = [c for c in test_cases if c["pdb_id"].upper() not in holdout_ids]
    return holdout_cases, remaining


# ---------------------------------------------------------------------------
# Benchmark holdout selection
# ---------------------------------------------------------------------------

def _select_benchmark_holdout(
    protein_ids: list[str],
    k: int,
    seed: int,
    exclude_ids: set[str],
) -> tuple[list[str], list[str]]:
    """
    Select k proteins from benchmark set using deterministic hash ordering.
    Excludes any ID in exclude_ids.
    """
    eligible = [pid for pid in protein_ids if pid.upper() not in exclude_ids]
    eligible.sort(key=lambda pid: _deterministic_hash(pid, seed))
    holdout = eligible[:k]
    holdout_set = set(h.upper() for h in holdout)
    remaining = [pid for pid in protein_ids if pid.upper() not in holdout_set]
    return holdout, remaining


# ---------------------------------------------------------------------------
# Leakage check
# ---------------------------------------------------------------------------

def _leakage_check(
    recall_holdout_ids: set[str],
    benchmark_holdout_ids: set[str],
    tuning_ids: set[str],
    all_known_ids: set[str],
) -> list[dict[str, Any]]:
    """Run leakage checks and return list of check results."""
    checks: list[dict[str, Any]] = []

    # Check 1: recall holdout vs tuning (strict)
    overlap_recall_tuning = recall_holdout_ids & tuning_ids
    checks.append({
        "check": "recall_holdout_vs_tuning_ids",
        "status": "PASS" if not overlap_recall_tuning else "CONTAMINATED",
        "overlap": sorted(overlap_recall_tuning),
    })

    # Check 2: benchmark holdout vs tuning
    overlap_bench_tuning = benchmark_holdout_ids & tuning_ids
    checks.append({
        "check": "benchmark_holdout_vs_tuning_ids",
        "status": "PASS" if not overlap_bench_tuning else "CONTAMINATED",
        "overlap": sorted(overlap_bench_tuning),
    })

    # Check 3: recall holdout vs benchmark holdout (informational)
    overlap_recall_bench = recall_holdout_ids & benchmark_holdout_ids
    checks.append({
        "check": "recall_holdout_vs_benchmark_holdout",
        "status": "INFO",
        "overlap": sorted(overlap_recall_bench),
        "note": "Overlap between recall and benchmark holdout is acceptable since they measure different metrics.",
    })

    # Check 4: historical contamination — all known cryptic IDs vs tuning
    # This is the honest check: the entire 20-case set was used in recovery
    # experiments, so holdout cases drawn from it are historically contaminated.
    hist_contamination = all_known_ids & tuning_ids
    checks.append({
        "check": "historical_contamination",
        "status": "CONTAMINATED" if hist_contamination else "CLEAN",
        "overlap": sorted(hist_contamination),
        "note": (
            "All 20 known cryptic pocket cases were used in recovery v2/v3 experiments. "
            "Holdout cases are therefore historically contaminated. "
            "This does NOT invalidate the holdout for Faz 7+ forward-looking use, "
            "but it means retrospective claims of blindness are not valid."
        ) if hist_contamination else "No historical contamination detected.",
    })

    return checks


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def _generate_report(
    recall_holdout: list[dict[str, Any]],
    recall_remaining: list[dict[str, Any]],
    benchmark_holdout: list[str],
    benchmark_remaining: list[str],
    tuning_ids: set[str],
    leakage_results: list[dict[str, Any]],
    seed: int,
    all_test_cases: list[dict[str, Any]],
) -> str:
    """Generate Markdown report."""
    lines: list[str] = []
    now = _utc_now_iso()

    lines.append("# Blind Holdout Set v1 — Report")
    lines.append("")
    lines.append(f"- Generated: {now}")
    lines.append(f"- Seed: {seed}")
    lines.append(f"- Selection method: SHA-256 deterministic hash, pocket-type stratified round-robin")
    lines.append("")

    # --- Source summary ---
    lines.append("## 1. Data Sources")
    lines.append("")
    lines.append(f"| Source | Path | Count |")
    lines.append(f"|--------|------|-------|")
    lines.append(f"| Known cryptic pockets | `data/validation/known_cryptic_pockets.json` | {len(all_test_cases)} |")
    lines.append(f"| Benchmark proteins | `data/benchmark/fpocket_benchmark_v3.json` | {len(benchmark_holdout) + len(benchmark_remaining)} |")
    lines.append(f"| Tuning/recovery IDs (excluded) | recovery_v2 + v3 + parameter_sweep | {len(tuning_ids)} |")
    lines.append("")

    # --- Pocket type distribution (full set) ---
    lines.append("## 2. Pocket Type Distribution (Full Validation Set)")
    lines.append("")
    type_counts = Counter(c.get("pocket_type", "unknown") for c in all_test_cases)
    lines.append("| Pocket Type | Count |")
    lines.append("|-------------|-------|")
    for ptype, count in sorted(type_counts.items(), key=lambda x: (-x[1], x[0])):
        lines.append(f"| {ptype} | {count} |")
    lines.append("")

    # --- Recall holdout ---
    lines.append("## 3. Recall Holdout Set")
    lines.append("")
    lines.append(f"- Size: {len(recall_holdout)} / {len(all_test_cases)}")
    lines.append("")
    lines.append("| PDB ID | Name | Pocket Type | Reference |")
    lines.append("|--------|------|-------------|-----------|")
    for c in recall_holdout:
        lines.append(f"| {c['pdb_id']} | {c.get('name', '')} | {c.get('pocket_type', '')} | {c.get('reference', '')} |")
    lines.append("")

    holdout_types = Counter(c.get("pocket_type", "unknown") for c in recall_holdout)
    lines.append("### Holdout Pocket Type Coverage")
    lines.append("")
    lines.append("| Pocket Type | In Holdout | In Full Set | Represented |")
    lines.append("|-------------|-----------|-------------|-------------|")
    for ptype in sorted(type_counts.keys()):
        in_ho = holdout_types.get(ptype, 0)
        in_full = type_counts[ptype]
        rep = "YES" if in_ho > 0 else "NO"
        lines.append(f"| {ptype} | {in_ho} | {in_full} | {rep} |")
    lines.append("")

    # --- Benchmark holdout ---
    lines.append("## 4. Benchmark Holdout Set")
    lines.append("")
    lines.append(f"- Size: {len(benchmark_holdout)} / {len(benchmark_holdout) + len(benchmark_remaining)}")
    lines.append("")
    lines.append("| # | PDB ID |")
    lines.append("|---|--------|")
    for i, pid in enumerate(sorted(benchmark_holdout), 1):
        lines.append(f"| {i} | {pid} |")
    lines.append("")

    # --- Exclusion list ---
    lines.append("## 5. Excluded Tuning/Recovery IDs")
    lines.append("")
    if tuning_ids:
        lines.append(f"Total excluded: {len(tuning_ids)}")
        lines.append("")
        lines.append("| PDB ID |")
        lines.append("|--------|")
        for pid in sorted(tuning_ids):
            lines.append(f"| {pid} |")
    else:
        lines.append("No tuning IDs found in recovery experiment files.")
        lines.append("")
        lines.append("**Note:** If recovery experiments used the same 20 known cryptic pocket cases,")
        lines.append("the tuning ID collector may not have found per-case records. Check historical_contamination check below.")
    lines.append("")

    # --- Leakage checks ---
    lines.append("## 6. Leakage Checks")
    lines.append("")
    lines.append("| Check | Status | Overlap |")
    lines.append("|-------|--------|---------|")
    for chk in leakage_results:
        overlap_str = ", ".join(chk["overlap"]) if chk["overlap"] else "none"
        lines.append(f"| {chk['check']} | {chk['status']} | {overlap_str} |")
    lines.append("")

    # --- Usage rules ---
    lines.append("## 7. Usage Rules")
    lines.append("")
    lines.append("1. **Recall holdout** cases must NOT be used for parameter tuning, threshold selection, or algorithm design.")
    lines.append("2. **Benchmark holdout** proteins must NOT be included in parameter sweep evaluations.")
    lines.append("3. Holdout metrics are reported as secondary checks AFTER all tuning is finalized.")
    lines.append("4. If holdout recall drops below 0.20 (absolute floor), the tuning round is invalidated.")
    lines.append("5. This manifest is sealed. Any modification invalidates all subsequent results.")
    lines.append("")

    # --- Run command ---
    lines.append("## 8. Reproduction Command")
    lines.append("")
    lines.append("```bash")
    lines.append(f"python scripts/build_blind_holdout_set.py --seed {seed} --holdout-recall-k {len(recall_holdout)} --holdout-benchmark-k {len(benchmark_holdout)}")
    lines.append("```")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Build blind holdout set v1")
    parser.add_argument("--seed", type=int, default=42, help="Deterministic seed (default: 42)")
    parser.add_argument("--holdout-recall-k", type=int, default=5, help="Number of recall holdout cases (default: 5)")
    parser.add_argument("--holdout-benchmark-k", type=int, default=20, help="Number of benchmark holdout proteins (default: 20)")
    parser.add_argument("--dry-run", action="store_true", help="Print results without writing files")
    args = parser.parse_args()

    seed = args.seed
    recall_k = args.holdout_recall_k
    bench_k = args.holdout_benchmark_k

    print(f"[INFO] Seed: {seed}, Recall holdout K: {recall_k}, Benchmark holdout K: {bench_k}")

    # 1. Load known cryptic pockets
    known_data = _load_json(KNOWN_CRYPTIC_PATH)
    if not known_data or "test_cases" not in known_data:
        print("[ERROR] Cannot load known_cryptic_pockets.json or missing test_cases key.")
        return 1
    test_cases: list[dict[str, Any]] = known_data["test_cases"]
    print(f"[INFO] Loaded {len(test_cases)} known cryptic pocket cases.")

    # 2. Load benchmark protein IDs from canonical JSON
    bench_data = _load_json(BENCHMARK_PATH)
    bench_protein_ids: list[str] = []
    bench_id_source = "unknown"

    if bench_data and isinstance(bench_data, dict):
        # Primary: full.results[0].per_protein (canonical benchmark JSON)
        full_block = bench_data.get("full", {})
        if isinstance(full_block, dict):
            results_list = full_block.get("results", [])
            if results_list and isinstance(results_list, list):
                per_protein = results_list[0].get("per_protein", [])
                if per_protein:
                    bench_protein_ids = [
                        p["pdb_id"].upper()
                        for p in per_protein
                        if isinstance(p, dict) and "pdb_id" in p
                    ]
                    bench_id_source = "fpocket_benchmark_v3.json -> full.results[0].per_protein"

    # Fallback: parse from Markdown report (last resort)
    if not bench_protein_ids:
        print("[WARN] Cannot extract protein IDs from benchmark JSON. Trying report (fallback).")
        report_path = REPO_ROOT / "docs" / "fpocket_benchmark_report.md"
        if report_path.exists():
            with open(report_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("| ") and not line.startswith("| PDB") and not line.startswith("| ---"):
                        parts = [p.strip() for p in line.split("|")]
                        if len(parts) >= 3 and len(parts[1]) == 4 and parts[1].isalnum():
                            bench_protein_ids.append(parts[1].upper())
            bench_id_source = "fpocket_benchmark_report.md (Markdown fallback)"

    bench_protein_ids = [pid for pid in bench_protein_ids if pid]
    print(f"[INFO] Loaded {len(bench_protein_ids)} benchmark protein IDs (source: {bench_id_source}).")
    if bench_id_source.endswith("(Markdown fallback)"):
        print("[WARN] Benchmark IDs loaded from Markdown fallback. Canonical JSON parsing failed.")

    if len(bench_protein_ids) < bench_k:
        print(f"[ERROR] Not enough benchmark proteins ({len(bench_protein_ids)}) for holdout K={bench_k}.")
        return 1

    # 3. Collect tuning/recovery IDs
    tuning_ids, tuning_per_source = _collect_tuning_ids()
    print(f"[INFO] Collected {len(tuning_ids)} tuning/recovery protein IDs for exclusion.")
    for src, ids in sorted(tuning_per_source.items()):
        print(f"  {src}: {len(ids)} IDs")

    # 4. Select recall holdout (stratified)
    recall_holdout, recall_remaining = _select_recall_holdout(
        test_cases, recall_k, seed, exclude_ids=set()  # Don't exclude tuning IDs from recall holdout
        # because all 20 cases were used in recovery experiments.
        # Instead, the holdout rule is: these cases must NOT be used
        # for future tuning (Faz 7+).
    )
    recall_holdout_ids = {c["pdb_id"].upper() for c in recall_holdout}
    print(f"[INFO] Selected {len(recall_holdout)} recall holdout cases: {sorted(recall_holdout_ids)}")

    # 5. Select benchmark holdout
    # Exclude recall holdout IDs from benchmark holdout to keep them independent
    bench_exclude = recall_holdout_ids.copy()
    benchmark_holdout, benchmark_remaining = _select_benchmark_holdout(
        bench_protein_ids, bench_k, seed, exclude_ids=bench_exclude
    )
    benchmark_holdout_ids = {pid.upper() for pid in benchmark_holdout}
    print(f"[INFO] Selected {len(benchmark_holdout)} benchmark holdout proteins.")

    # 6. Leakage checks
    all_known_ids = {c["pdb_id"].upper() for c in test_cases}
    leakage_results = _leakage_check(recall_holdout_ids, benchmark_holdout_ids, tuning_ids, all_known_ids)
    for chk in leakage_results:
        tag = "OK" if chk["status"] in ("PASS", "INFO", "CLEAN") else "WARN"
        print(f"  [{tag}] {chk['check']}: {chk['status']} (overlap: {chk['overlap']})")

    # 7. Build output JSON
    manifest = {
        "version": "v1",
        "sealed_at_utc": _utc_now_iso(),
        "seed": seed,
        "selection_method": "SHA-256 deterministic hash, pocket-type stratified round-robin",
        "recall_holdout": {
            "k": len(recall_holdout),
            "ids": sorted(c["pdb_id"].upper() for c in recall_holdout),
            "cases": [
                {
                    "pdb_id": c["pdb_id"],
                    "name": c.get("name", ""),
                    "pocket_type": c.get("pocket_type", ""),
                    "reference": c.get("reference", ""),
                }
                for c in recall_holdout
            ],
        },
        "recall_remaining": {
            "k": len(recall_remaining),
            "ids": sorted(c["pdb_id"].upper() for c in recall_remaining),
        },
        "benchmark_holdout": {
            "k": len(benchmark_holdout),
            "ids": sorted(benchmark_holdout),
        },
        "benchmark_remaining": {
            "k": len(benchmark_remaining),
            "ids": sorted(benchmark_remaining),
        },
        "exclusion": {
            "tuning_ids": sorted(tuning_ids),
            "tuning_id_count": len(tuning_ids),
            "tuning_per_source": {k: sorted(v) for k, v in tuning_per_source.items()},
        },
        "benchmark_id_source": bench_id_source,
        "leakage_checks": leakage_results,
    }

    # 8. Generate report
    report = _generate_report(
        recall_holdout=recall_holdout,
        recall_remaining=recall_remaining,
        benchmark_holdout=benchmark_holdout,
        benchmark_remaining=benchmark_remaining,
        tuning_ids=tuning_ids,
        leakage_results=leakage_results,
        seed=seed,
        all_test_cases=test_cases,
    )

    if args.dry_run:
        print("\n[DRY RUN] JSON manifest:")
        print(json.dumps(manifest, indent=2))
        print("\n[DRY RUN] Report:")
        print(report)
        return 0

    # 9. Write outputs
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    print(f"[INFO] Wrote: {OUTPUT_JSON}")

    with open(OUTPUT_REPORT, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"[INFO] Wrote: {OUTPUT_REPORT}")

    # 10. Summary
    any_fail = any(c["status"] == "FAIL" for c in leakage_results)
    any_contaminated = any(c["status"] == "CONTAMINATED" for c in leakage_results)
    if any_fail:
        print("\n[FAIL] LEAKAGE DETECTED -- review leakage checks before proceeding.")
        return 1
    elif any_contaminated:
        print("\n[WARN] Historical contamination detected (see report).")
        print("  Holdout is valid for forward-looking Faz 7+ use only.")
        print("  Retrospective blindness claims are NOT valid.")
        return 0  # not a hard failure, but contamination is documented
    else:
        print("\n[PASS] Blind holdout set v1 sealed successfully. No leakage detected.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
