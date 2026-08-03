# Security Policy

BioVoid is a local research prototype. The public repository is intended to
contain source code, tests, configuration, and conservative documentation
only.

## Reporting

Please use GitHub's private vulnerability reporting feature when it is enabled
for the repository. Do not open a public issue containing credentials, access
tokens, private structure files, local databases, model files, or generated
research outputs.

## Repository boundary

The following are intentionally outside the public repository boundary:

- local databases and Atlas data
- raw PDB/mmCIF files and downloaded structures
- trained models and model checkpoints
- generated reports, benchmark artifacts, and caches
- private planning or memory-bank files

The public hygiene checker and CI workflow are release guards, not a substitute
for reviewing the complete Git history before a release.

## Supported state

Only the current public release candidate is considered supported. Scientific
outputs remain unvalidated research candidates and must not be treated as
clinical, diagnostic, or drug-development results.
