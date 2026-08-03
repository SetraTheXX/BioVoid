# BioVoid Job Runtime v1

> **Status:** Recovery contract
> **Scope:** Local single-node API and experimental crawler

## Execution

- `quick_probe` is lightweight and may run in the in-process worker.
- `full_analysis` runs in a terminable child process.
- The default API worker is single-consumer during recovery.
- Job state is in-memory and volatile across process restart. Restart recovery is not implied.

## Timeout

- A full-analysis timeout terminates the child process and returns `JOB_TIMEOUT`.
- A timed-out attempt cannot write legacy or current Atlas.
- Partial files may exist only in that attempt's ignored, unique run workspace.
- Partial workspaces are non-canonical and cannot be read by another run.
- Retry creates a new run workspace; files are never merged across attempts.
- Atlas persistence remains disabled during recovery until the run-scoped Atlas contract is implemented.

## Idempotency

- Single-job identity is the explicit idempotency key plus payload hash.
- Batch child keys are derived from the caller key, item index, and PDB ID.
- Random response identifiers do not participate in batch child identity.
- Reusing a key with a different payload is a conflict.

## Crawler

- Bulk crawling is hard-disabled without an explicit recovery override.
- Override output is `experimental_unvalidated` and `canonical_eligible=false`.
- Override output and optional DB must remain inside a non-canonical experimental root.
- Static analysis may use at most two workers; motion-aware crawling may use one heavy worker.
