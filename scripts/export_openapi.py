"""Export the canonical FastAPI OpenAPI schema for frontend type generation."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.api.app import create_app
from src.api.orchestrator import JobOrchestrator


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    schema = create_app(orchestrator=JobOrchestrator()).openapi()
    canonical = json.dumps(schema, sort_keys=True, separators=(",", ":")).encode("utf-8")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(schema, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"BioVoid OpenAPI SHA256: {hashlib.sha256(canonical).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
