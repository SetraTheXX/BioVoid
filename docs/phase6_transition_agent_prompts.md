# Phase 6 Transition Agent Prompt Pack (A/B/C)

Use these prompts as-is in separate Codex sessions. All three sessions must start from the same base commit on `ws-main/recovery-v3-integration`.

## Prompt A (WS-A: Recall Full20 Stabilization)

```text
Role: WS-A Recall Specialist
Branch: ws-a/phase6-transition-recall
Base: ws-main/recovery-v3-integration (current HEAD)

Goal:
1) Keep canonical lock fixed (tolerance=8.0, top_n=20, druggable_only=true).
2) Reconcile mini success with full20 failure.
3) Produce a reproducible full20 recall artifact and report without long uncontrolled runs.

Do:
1. git switch -c ws-a/phase6-transition-recall
2. python -m py_compile BioVoid/scripts/run_recovery_v2_recall_workstream.py
3. Run bounded sequence:
   - python BioVoid/scripts/run_recovery_v2_recall_workstream.py --cp-a-mini-only --cp-a-trials t4_atom_mode_heavy,t6_atom_mode_heavy_relaxed --cp-a-max-minutes 90
   - python BioVoid/scripts/validate_known_pockets.py --engine v2_advanced
4. Update:
   - BioVoid/docs/recovery_v2_recall_domain_motion_report.md
   - BioVoid/docs/validation_report.md
   - BioVoid/data/validation/validation_results.json (artifact; ignored olabilir)
5. Commit only WS-A scoped tracked files.

Acceptance:
- No hang process left running.
- validation_results recall must be reproducible in one rerun.
- Report must include explicit mini vs full20 delta analysis.
```

## Prompt B (WS-B: Overlap SoT Hardening)

```text
Role: WS-B Overlap Specialist
Branch: ws-b/phase6-transition-overlap
Base: ws-main/recovery-v3-integration (current HEAD)

Goal:
1) Keep official overlap metric unchanged.
2) Keep transition overlap SoT (`cp_b_candidate_impact.full_option1_overlap`) consistent across docs.
3) Produce a clean overlap readiness snapshot for transition cycles.

Do:
1. git switch -c ws-b/phase6-transition-overlap
2. Re-run overlap reporting only:
   - python BioVoid/scripts/generate_benchmark_report.py
3. Refresh docs if values drift:
   - BioVoid/docs/recovery_v2_overlap_option1_lock.md
   - BioVoid/docs/recovery_v2_overlap_calibration_report.md
4. Verify exact numeric consistency:
   - official baseline 0.0577
   - full option1 overlap 0.2439 (delta +0.1862)
   - top10 candidate-set 0.0290 -> 0.3246 (delta +0.2957)
5. Commit only WS-B scoped tracked files.

Acceptance:
- No metric mismatch between WS-B docs and JSON SoT.
- Official gate metric unchanged statement present.
```

## Prompt C (WS-C: Guard + Transition Gate Control)

```text
Role: WS-C Guard/QA Specialist
Branch: ws-c/phase6-transition-guard
Base: ws-main/recovery-v3-integration (current HEAD)

Goal:
1) Re-run guard chain and keep PASS.
2) Generate both gate profiles and validate controlled-go posture.

Do:
1. git switch -c ws-c/phase6-transition-guard
2. Run:
   - python BioVoid/scripts/check_gate_feasibility.py --gate-profile strict
   - python BioVoid/scripts/check_gate_feasibility.py --gate-profile recovery_v2_transition
   - python BioVoid/scripts/generate_phase5_5_gate_decision.py --gate-profile strict --output docs/phase5_5_gate_decision.md
   - python BioVoid/scripts/generate_phase5_5_gate_decision.py --gate-profile recovery_v2_transition --output docs/phase5_5_gate_decision_recovery_v2_transition.md
   - python BioVoid/scripts/run_recovery_v2_regression_guard.py --fpocket-report docs/fpocket_benchmark_report.md
   - python BioVoid/scripts/recovery_v2_intake_check.py --strict
3. Update guard docs:
   - BioVoid/docs/recovery_v2_regression_guard_report.md
   - BioVoid/docs/recovery_v2_drift_check_report.md
   - BioVoid/docs/recovery_v2_reports_alignment.md
4. Commit only WS-C scoped tracked files.

Acceptance:
- WS-C guard overall PASS.
- strict gate remains explicit FAIL.
- recovery_v2_transition gate explicit PASS.
- hard_checks_ok=True and readiness_signals_ok=True.
```
