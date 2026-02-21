# Phase 6 Rollback Runbook

- Last updated: 2026-02-21
- Scope: Step 4 operational rollback guide

## Trigger Conditions

Run rollback if any of these happen after deployment:

1. `GET /ready` reports `degraded` continuously.
2. Error budget breach or repeated `5xx` spikes.
3. Strict gate/guard snapshot fails after deployment.

## Rollback Strategy

1. Freeze new traffic and disable deploy pipeline.
2. Roll back to previous stable commit/tag.
3. Restart API process with previous artifact.
4. Re-run guard command pack:

```bash
python scripts/run_phase6_ops_guard_pack.py --strict-recall-floor 0.30 --strict-overlap-floor 0.25
```

5. Confirm:
   - `GET /health` -> `ok`
   - `GET /ready` -> `ready`
   - portal smoke passes

## One-Attempt Rehearsal Record

- Rehearsal date (UTC): 2026-02-21
- Method: isolated rollback candidate check via temporary git worktree at `HEAD~1`
- Outcome: `PASS`
- Notes:
  1. Previous stable revision resolved and loaded in isolated worktree.
  2. API module compile check passed.
  3. Temporary worktree cleaned after rehearsal.
