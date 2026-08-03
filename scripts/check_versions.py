"""Fail when Python metadata and frontend package versions diverge."""

from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.version import __version__


def main() -> int:
    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    package = json.loads((PROJECT_ROOT / "frontend/package.json").read_text(encoding="utf-8"))
    versions = {
        "src.version": __version__,
        "pyproject": str(pyproject["project"]["version"]),
        "frontend": str(package["version"]),
    }
    if len(set(versions.values())) != 1:
        print(json.dumps(versions, sort_keys=True))
        return 1
    print(f"BioVoid version {__version__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
