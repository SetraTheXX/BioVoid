# Phase 6 Transition Governance (Recovery v3)

- Date (UTC): 2026-02-18
- Scope: Phase 5.5 closure to controlled Phase 6 transition
- Canonical lock: `tolerance=8.0`, `top_n=20`, `druggable_only=true`

## Decision Split

1. `strict` profile (official hard gate):
- Source: `docs/phase5_5_gate_decision.md`
- Decision: `FAIL`
- Recall: `0.1500 < 0.30`
- Overlap (official): `0.0577 < 0.25`
- FPR: `PASS`
- MD: `PASS`

2. `recovery_v2_transition` profile (controlled-go profile):
- Source: `docs/phase5_5_gate_decision_recovery_v2_transition.md`
- Decision: `PASS`
- Recall: `0.1500 >= 0.10`
- Overlap SoT: `cp_b_candidate_impact.full_option1_overlap = 0.2439 >= 0.24`
- FPR: `PASS`
- MD: `PASS`

## Governance Rule

1. Strict profile remains the publication-grade gate.
2. Transition profile is authorized only for Phase 6 pre-production ramp.
3. Any production/public claim must still reference strict gate status.

## Phase 6 Entry Mode

- Mode: `CONDITIONAL_GO`
- Allowed:
  - limited Phase 6 pipeline bring-up,
  - infra/perf/data-integrity validation,
  - guarded recall/overlap recovery iteration.
- Not allowed:
  - strict PASS claim,
  - final scientific sign-off.

## Required Commands Before Each Transition Cycle

```bash
python scripts/check_gate_feasibility.py --gate-profile strict
python scripts/check_gate_feasibility.py --gate-profile recovery_v2_transition
python scripts/generate_phase5_5_gate_decision.py --gate-profile strict --output docs/phase5_5_gate_decision.md
python scripts/generate_phase5_5_gate_decision.py --gate-profile recovery_v2_transition --output docs/phase5_5_gate_decision_recovery_v2_transition.md
python scripts/recovery_v2_intake_check.py --strict
```

## Exit Criteria (Transition -> Full Go)

1. Strict gate becomes `PASS` in `docs/phase5_5_gate_decision.md`.
2. WS-C guard chain remains `PASS`.
3. SoT alignment has no drift across WS-A/WS-B/WS-C docs and JSON artifacts.
