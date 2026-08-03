"""Check the source-only boundary required by the public release contract.

The check is intentionally conservative.  It validates the current tracked
tree and, when requested, reachable Git objects.  A passing tree check does
not erase an unsafe historical object; history cleanup remains a separate,
explicitly approved operation.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_TOP_LEVEL = {
    "artifacts",
    "data",
    "generated",
    "memory-bank",
    "outputs",
    "plans",
    "roadmaps",
    "notes",
    "private",
    "local-notes",
    "local-private",
    "research-local",
}

# Suffixes cover structures, model weights, generated arrays, archives and
# native tools that must never become part of a source-only release.
FORBIDDEN_SUFFIXES = {
    ".bin",
    ".cif",
    ".cif.gz",
    ".ckpt",
    ".db",
    ".dll",
    ".dylib",
    ".ent",
    ".exe",
    ".h5",
    ".hdf5",
    ".joblib",
    ".keras",
    ".mmcif",
    ".mmcif.gz",
    ".npy",
    ".npz",
    ".onnx",
    ".parquet",
    ".pdb",
    ".pdb.gz",
    ".pfx",
    ".pkl",
    ".pt",
    ".pth",
    ".rar",
    ".safetensors",
    ".so",
    ".sqlite",
    ".sqlite3",
    ".tar.gz",
    ".zip",
    ".7z",
}

REQUIRED_IGNORE_RULES = {
    "artifacts/",
    "data/",
    "frontend/dist/",
    "frontend/node_modules/",
    "memory-bank/",
    "plans/",
    "roadmaps/",
    "private/",
    "local-private/",
    "research-local/",
    "docs/research/",
    "docs/specs/*-draft.md",
    "docs/specs/ri*",
    "docs/specs/benchmark-case-manifest*.md",
    "docs/specs/benchmark-protocol-v*.md",
    "docs/specs/baseline-lock-v1.md",
    "docs/specs/ground-truth-alignment*.md",
    "*.bin",
    "*.cif",
    "*.cif.gz",
    "*.ckpt",
    "*.dll",
    "*.exe",
    "*.mmcif",
    "*.npy",
    "*.npz",
    "*.parquet",
    "*.pdb",
    "*.pdb.gz",
    "*.pkl",
    "*.sqlite",
    "*.tar.gz",
    "*.zip",
}

FORBIDDEN_DOCUMENT_PATH = re.compile(
    r"^(?:docs/(?:private|internal|roadmaps|plans|research)/|"
    r"docs/specs/(?:ri[-0-9]|phase6-dataset-strategy).*|"
    r"docs/specs/benchmark-protocol-v[^/]*\.md$|"
    r"docs/specs/.*-draft.*\.md$)",
    re.IGNORECASE,
)

_UNIX_USER_PREFIX = "/" + "Users/"
_UNIX_HOME_PREFIX = "/" + "home/"
ABSOLUTE_USER_PATH = re.compile(
    r"(?:[A-Za-z]:[\\/]Users[\\/][^\s\"'<>]+|"
    + rf"(?<![A-Za-z0-9_]){re.escape(_UNIX_USER_PREFIX)}[^\s\"'<>]+|"
    + rf"(?<![A-Za-z0-9_]){re.escape(_UNIX_HOME_PREFIX)}[^\s\"'<>]+)",
    re.IGNORECASE,
)
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----"),
    re.compile(r"\b(?:ghp|gho|ghs|ghr|github_pat)_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
)
MAX_SCANNABLE_BYTES = 5 * 1024 * 1024


def _git(*args: str) -> list[str]:
    result = subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
    )
    return [line.replace("\\", "/") for line in result.stdout.splitlines() if line]


def _forbidden_path(path: str) -> bool:
    normalized = path.strip().replace("\\", "/")
    parts = normalized.split("/")
    if parts and parts[0].lower() in FORBIDDEN_TOP_LEVEL:
        return True
    if normalized.startswith("frontend/node_modules/") or normalized.startswith("frontend/dist/"):
        return True
    if FORBIDDEN_DOCUMENT_PATH.search(normalized):
        return True
    lower = normalized.lower()
    return any(lower.endswith(suffix) for suffix in FORBIDDEN_SUFFIXES)


def _check_paths(paths: list[str], source: str) -> list[str]:
    violations = sorted({path for path in paths if _forbidden_path(path)})
    if violations:
        print(f"{source}: forbidden paths detected:", file=sys.stderr)
        for path in violations:
            print(f"  {path}", file=sys.stderr)
    return violations


def _text_findings(text: str, source: str) -> list[str]:
    findings: list[str] = []
    if ABSOLUTE_USER_PATH.search(text):
        findings.append(f"{source}: absolute user path detected")
    for pattern in SECRET_PATTERNS:
        if pattern.search(text):
            findings.append(f"{source}: credential-like content detected")
            break
    return findings


def _scan_file(path: Path, source: str) -> list[str]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return [f"{source}: unable to read {path}: {exc}"]
    if len(raw) > MAX_SCANNABLE_BYTES or b"\x00" in raw:
        return []
    return _text_findings(raw.decode("utf-8", errors="replace"), source)


def _scan_tracked_content(paths: list[str], source: str) -> list[str]:
    findings: list[str] = []
    for relative in paths:
        findings.extend(_scan_file(ROOT / relative, f"{source}:{relative}"))
    return findings


def _history_content_findings(history_ref: str) -> list[str]:
    findings = _text_findings(
        "\n".join(_git("log", history_ref, "--format=%B")),
        f"reachable history ({history_ref}) commit messages",
    )
    for row in _git("rev-list", "--objects", history_ref):
        object_id, _, object_path = row.partition(" ")
        if not object_path:
            continue
        object_type = _git("cat-file", "-t", object_id)
        if not object_type or object_type[0] != "blob":
            continue
        size = int(_git("cat-file", "-s", object_id)[0])
        if size > MAX_SCANNABLE_BYTES:
            continue
        result = subprocess.run(
            ["git", "cat-file", "blob", object_id],
            check=True,
            capture_output=True,
            cwd=ROOT,
        )
        if b"\x00" in result.stdout:
            continue
        findings.extend(
            _text_findings(
                result.stdout.decode("utf-8", errors="replace"),
                f"reachable history ({history_ref}):{object_path}",
            )
        )
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--history",
        action="store_true",
        help="also inspect names and text in reachable Git objects",
    )
    parser.add_argument(
        "--history-ref",
        default="HEAD",
        help="Git ref to inspect with --history (default: HEAD)",
    )
    args = parser.parse_args()

    # Treat pending deletions as removed from the release candidate.  Reachable
    # history is checked separately with --history and remains intentionally
    # fail-closed until its objects are sanitized.
    tracked = [path for path in _git("ls-files") if (ROOT / path).is_file()]
    violations = _check_paths(tracked, "tracked tree")
    violations.extend(_scan_tracked_content(tracked, "tracked tree"))

    ignore_lines = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    missing_rules = sorted(REQUIRED_IGNORE_RULES - set(ignore_lines))
    if missing_rules:
        print(".gitignore: required rules missing:", file=sys.stderr)
        for rule in missing_rules:
            print(f"  {rule}", file=sys.stderr)
        violations.extend(missing_rules)

    if args.history:
        history_paths = _git("rev-list", "--objects", args.history_ref)
        violations.extend(
            _check_paths(
                [row.split(" ", 1)[1] for row in history_paths if " " in row],
                f"reachable history ({args.history_ref})",
            )
        )
        violations.extend(_history_content_findings(args.history_ref))

    if violations:
        for finding in sorted(set(violations)):
            if ": forbidden paths detected:" not in finding and ": absolute" not in finding:
                print(finding, file=sys.stderr)
        return 1

    scope = "tracked tree and reachable history" if args.history else "tracked tree"
    print(f"Public hygiene check passed for {scope}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
