# Public Release Contract v1

Status: public source release v0.1.0; future releases require maintainer review.

## Repository boundary

The public repository contains code, tests, reproducible configuration, and
documentation that does not depend on a private working environment. It does
not contain local Atlas databases, downloaded structures, trained models,
generated outputs, caches, or private planning files.

Required controls:

- `git ls-files` contains no forbidden scientific or private paths.
- The complete history reachable from the release ref contains no forbidden
  paths.
- `.gitignore` and the public hygiene checker protect the same boundary.
- Frontend dependencies and build output remain local or build-generated.
- No remote push, force-push, tag deletion, or branch deletion is performed by
  an automated release step.

## History strategy

The working tree boundary and the reachable-history boundary are separate
release gates. Removing a forbidden file from the current tree does not remove
it from existing commits.

Before a public release, the maintainer must choose one explicitly approved
strategy: a sanitized history rewrite that preserves the repository identity,
or a new public repository with a clean source-only history. A rewrite changes
commit IDs and requires separate approval before any force-push. Original refs
must remain local-only and must never be included in a public push set.

The selected sanitized release ref must pass the history hygiene check and be
reviewed before it is used to update public branches.

## Scientific wording

BioVoid is presented as a local computational research prototype for generating
and inspecting geometry-based pocket candidates. Static output is the current
canonical engineering path. Motion-aware output remains experimental until a
sealed benchmark and external validation support a stronger claim.

Terms such as discovery, prediction, confidence, druggability, or success
probability must not be used as validated scientific claims without the
corresponding evidence and evaluator protocol.

## Release gates

1. Public hygiene check passes on the sanitized history.
2. Python tests and frontend lint, tests, and build pass.
3. API health and portal smoke checks pass.
4. README and security boundary review is complete.
5. Changed files, commit IDs, refs, and remote state are shown to the
   maintainer.
6. For future releases, the maintainer explicitly approves the push;
   force-push requires separate explicit approval.
