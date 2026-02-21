# Phase 6 Transition Prompt Pack (Updated)

- Date: 2026-02-21
- Context: Phase 5.5 strict gate PASS, Faz 6 teknik olarak hazir.
- Operational mode: `PAUSED` (bu dosya sadece start verildiginde kullanilacak).

## Prompt 0 (Pre-Start Safety Check)

```text
Role: Transition Gate Controller
Branch: ws-main/recovery-v3-integration
Goal: Faz 6 start oncesi strict PASS durumunu yeniden dogrula.

Run:
1) python scripts/generate_phase5_5_gate_decision.py --gate-profile strict --fpocket-report docs/fpocket_benchmark_report.md
2) python scripts/run_recovery_v2_regression_guard.py --fpocket-report docs/fpocket_benchmark_report.md
3) python scripts/recovery_v2_intake_check.py --strict --recall-floor 0.30 --overlap-floor 0.25

Accept only if:
- Decision: PASS
- Overall WS-C guard: PASS
- hard_checks_ok=True
- readiness_signals_ok=True
```

## Prompt A (Phase 6A: API + Job Orchestration)

```text
Role: Phase6-A Backend
Branch: phase6/api-orchestrator
Goal: PDB job kabul eden ve status/sonuc donen minimal production API.

Scope:
1) POST /jobs (input validation + idempotency key)
2) GET /jobs/{id} (queued/running/succeeded/failed)
3) Worker queue integration (single-node first)
4) Retry/backoff + timeout policy
5) Structured error model

Constraints:
- Canonical scientific lock parametreleri request ile override edilemez.
- Validation artifacts immutable tutulur (SoT only).
- Rate limit zorunlu.

Acceptance:
- 50 ardisik job testinde crash yok.
- Failed job retry policy deterministic.
- OpenAPI/Swagger guncel.
```

## Prompt B (Phase 6B: Web Portal + UX)

```text
Role: Phase6-B Frontend
Branch: phase6/web-portal
Goal: Arastirmaci odakli minimal portal (submit + monitor + download report).

Scope:
1) Job submit form (PDB id / file upload)
2) Job status timeline
3) Result view (recall-style summary + artifacts link)
4) Basic auth/session (opsiyonel)
5) Error + empty states

Constraints:
- Existing visual language korunacak.
- Mobile/desktop responsive.
- Long-running job UX (polling + cancellation feedback) net olacak.

Acceptance:
- E2E: submit -> done -> report download.
- Invalid inputlar net hata mesaji veriyor.
```

## Prompt C (Phase 6C: Ops, SLO, Release Guard)

```text
Role: Phase6-C Ops/QA
Branch: phase6/ops-guard
Goal: Faz 6 canliya cikis oncesi operasyonel guvenlik katmani.

Scope:
1) Basic SLO: availability, p95 job latency, error budget
2) Health endpoints + readiness probes
3) Release checklist + rollback runbook
4) Log correlation ids + basic dashboards
5) Regression guard command pack in CI

Acceptance:
- Dry-run release checklist PASS.
- Rollback adimlari 1 deneme ile calisiyor.
- CI gate strict/pass durumunu bozmadan tamamlaniyor.
```

## Prompt D (Single-Agent Mode)

```text
Role: Phase6 Single Integrator
Branch: phase6/single-integrator
Goal: A/B/C kapsamini tek ajan ile sirali yurutmek.

Execution order:
1) Prompt 0 (safety check)
2) Prompt A
3) Prompt B
4) Prompt C
5) Final integration + smoke tests

Rule:
- Her adim sonrasi strict gate + guard snapshot tekrar alinacak.
- Strict PASS bozulursa bir sonraki adima gecilmez.
```
