# fpocket Fairness Audit (Phase 5.5)

## Audit Scope

- Compare fpocket and BioVoid under identical benchmark membership and locked canonical parameters.
- Validate parameter drift and reporting symmetry before gate decision.

## Checklist

- [x] Same benchmark set size used by both methods (100 proteins).
- [x] Canonical tolerance locked at 8.0 A.
- [x] Canonical top-N locked at 20.
- [x] Druggable filter lock enforced by extraction/report scripts.
- [x] fpocket status accounting captured (ok=99, missing_input=1).
- [x] Drift checks performed before gate write-out.

## Symmetry Notes

- Matching uses center proximity with canonical tolerance and one-to-one assignment policy.
- Aggregate overlap uses the same formula for all proteins in scope.
- Missing fpocket input is reported explicitly and not silently dropped.

## Residual Risks

- fpocket preprocessing/protonation parity is not fully normalized in this environment.
- Volume-ratio constraint in overlap matching may penalize geometric but not volumetric matches.
- One missing-input target can slightly bias aggregate overlap downward.

## Audit Verdict

- Fairness checks are **sufficient for gate accounting**, with documented preprocessing limitations.
