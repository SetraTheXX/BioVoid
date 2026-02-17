#!/usr/bin/env python3
"""Recovery v2 intake checker for WS-A/WS-B/WS-C outputs.

Usage:
    python scripts/recovery_v2_intake_check.py

This script validates three output artifacts and prints a concise summary:
1) WS-A mini-set recall artifact
2) WS-B overlap pilot artifact
3) WS-C regression guard artifact

It separates hard integrity checks (must pass) from progress signals.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


CANONICAL_TOLERANCE = 8.0
CANONICAL_TOP_N = 20
CANONICAL_DRUGGABLE = True


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing artifact: {path}")
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _check_canonical_lock(lock: dict[str, Any]) -> tuple[bool, str]:
    tol_raw = lock.get("tolerance", lock.get("tolerance_angstrom", -1.0))
    tol = float(tol_raw)
    top_n = int(lock.get("top_n", -1))
    drug_raw = lock.get("druggable_only", lock.get("druggable", False))
    drug = bool(drug_raw)

    ok = (
        abs(tol - CANONICAL_TOLERANCE) < 1e-9
        and top_n == CANONICAL_TOP_N
        and drug is CANONICAL_DRUGGABLE
    )
    detail = (
        f"tolerance={tol}, top_n={top_n}, druggable_only={str(drug).lower()}"
    )
    return ok, detail


def _check_ws_a(payload: dict[str, Any], recall_floor: float) -> dict[str, Any]:
    lock = payload.get("canonical_lock", {})
    lock_ok, lock_detail = _check_canonical_lock(lock)

    best_trial = payload.get("best_trial", {})
    summary = best_trial.get("summary", {})
    best_recall = float(summary.get("recall", 0.0))
    dm_hits = int(best_trial.get("domain_motion_hits", 0))
    dm_total = int(best_trial.get("domain_motion_total", 0))
    errors = int(summary.get("error_count", 0))
    decision = str(payload.get("cp_a_decision", "UNKNOWN"))

    return {
        "lock_ok": lock_ok,
        "lock_detail": lock_detail,
        "best_trial_id": best_trial.get("trial_id", "unknown"),
        "best_recall": best_recall,
        "domain_motion_hits": dm_hits,
        "domain_motion_total": dm_total,
        "error_count": errors,
        "cp_a_decision": decision,
        "signal_recall_ge_floor": best_recall >= recall_floor,
        "signal_domain_motion_hit": dm_hits >= 1 and dm_total >= 1,
    }


def _check_ws_b(payload: dict[str, Any], overlap_floor: float) -> dict[str, Any]:
    metadata = payload.get("metadata", {})
    lock = metadata.get("canonical_lock", {})
    lock_ok, lock_detail = _check_canonical_lock(lock)

    baseline = payload.get("baseline_reference", {})
    pilot = payload.get("pilot", {})
    results = pilot.get("results", [])
    best_cfg = pilot.get("best_config", {})

    base_official = float(baseline.get("official_overlap_center_volume_greedy", 0.0))
    best_overlap = float(best_cfg.get("overlap", 0.0))
    best_config_name = str(best_cfg.get("config", "unknown"))

    return {
        "lock_ok": lock_ok,
        "lock_detail": lock_detail,
        "base_official_overlap": base_official,
        "best_overlap": best_overlap,
        "best_config": best_config_name,
        "n_configs": len(results),
        "signal_overlap_ge_floor": best_overlap >= overlap_floor,
        "signal_overlap_improved": best_overlap > base_official,
    }


def _check_ws_c(payload: dict[str, Any]) -> dict[str, Any]:
    overall = str(payload.get("overall_regression_guard_status", "UNKNOWN"))
    guards = payload.get("guards", {})

    def _guard_status(name: str) -> str:
        return str(guards.get(name, {}).get("status", "UNKNOWN"))

    fpr = _guard_status("fpr_guard")
    md = _guard_status("md_guard")
    drift = _guard_status("drift_guard")
    consistency = _guard_status("report_consistency_guard")
    hard_ok = all(item == "PASS" for item in (overall, fpr, md, drift, consistency))

    return {
        "overall": overall,
        "fpr_guard": fpr,
        "md_guard": md,
        "drift_guard": drift,
        "report_consistency_guard": consistency,
        "hard_ok": hard_ok,
    }


def _print_summary(ws_a: dict[str, Any], ws_b: dict[str, Any], ws_c: dict[str, Any]) -> None:
    print("Recovery v2 intake summary")
    print("")
    print("[WS-A]")
    print(
        "  best_trial={tid} recall={rec:.4f} dm={dmh}/{dmt} errors={err} decision={dec}".format(
            tid=ws_a["best_trial_id"],
            rec=ws_a["best_recall"],
            dmh=ws_a["domain_motion_hits"],
            dmt=ws_a["domain_motion_total"],
            err=ws_a["error_count"],
            dec=ws_a["cp_a_decision"],
        )
    )
    print(f"  canonical_lock_ok={ws_a['lock_ok']} ({ws_a['lock_detail']})")
    print(
        "  signals: recall_floor={r} domain_motion_hit={d}".format(
            r=ws_a["signal_recall_ge_floor"],
            d=ws_a["signal_domain_motion_hit"],
        )
    )
    print("")
    print("[WS-B]")
    print(
        "  best_config={cfg} best_overlap={best:.4f} base_overlap={base:.4f} configs={n}".format(
            cfg=ws_b["best_config"],
            best=ws_b["best_overlap"],
            base=ws_b["base_official_overlap"],
            n=ws_b["n_configs"],
        )
    )
    print(f"  canonical_lock_ok={ws_b['lock_ok']} ({ws_b['lock_detail']})")
    print(
        "  signals: overlap_floor={f} overlap_improved={i}".format(
            f=ws_b["signal_overlap_ge_floor"],
            i=ws_b["signal_overlap_improved"],
        )
    )
    print("")
    print("[WS-C]")
    print(
        "  overall={o} fpr={fpr} md={md} drift={d} report={r}".format(
            o=ws_c["overall"],
            fpr=ws_c["fpr_guard"],
            md=ws_c["md_guard"],
            d=ws_c["drift_guard"],
            r=ws_c["report_consistency_guard"],
        )
    )
    print(f"  hard_ok={ws_c['hard_ok']}")
    print("")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Recovery v2 intake validator.")
    parser.add_argument(
        "--ws-a-json",
        default="data/validation/recovery_v2_domain_motion_eval.json",
        help="Path to WS-A mini-set output JSON.",
    )
    parser.add_argument(
        "--ws-b-json",
        default="data/benchmark/recovery_v2_overlap_pilot.json",
        help="Path to WS-B pilot output JSON.",
    )
    parser.add_argument(
        "--ws-c-json",
        default="data/validation/recovery_v2_regression_guard.json",
        help="Path to WS-C guard output JSON.",
    )
    parser.add_argument(
        "--recall-floor",
        type=float,
        default=0.22,
        help="Signal threshold for mini-set recall readiness.",
    )
    parser.add_argument(
        "--overlap-floor",
        type=float,
        default=0.15,
        help="Signal threshold for pilot overlap readiness.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Exit non-zero when hard checks fail or both readiness signals "
            "(recall_floor + overlap_floor) are not satisfied."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]

    ws_a_payload = _load_json(root / args.ws_a_json)
    ws_b_payload = _load_json(root / args.ws_b_json)
    ws_c_payload = _load_json(root / args.ws_c_json)

    ws_a = _check_ws_a(ws_a_payload, args.recall_floor)
    ws_b = _check_ws_b(ws_b_payload, args.overlap_floor)
    ws_c = _check_ws_c(ws_c_payload)

    _print_summary(ws_a, ws_b, ws_c)

    hard_ok = ws_a["lock_ok"] and ws_b["lock_ok"] and ws_c["hard_ok"]
    readiness_ok = ws_a["signal_recall_ge_floor"] and ws_b["signal_overlap_ge_floor"]
    print(f"hard_checks_ok={hard_ok}")
    print(f"readiness_signals_ok={readiness_ok}")

    if args.strict and (not hard_ok or not readiness_ok):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
