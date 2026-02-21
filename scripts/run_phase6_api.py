"""Run Phase 6 Job API locally."""

from __future__ import annotations

import argparse

import uvicorn


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run BioVoid Phase 6 API server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    uvicorn.run(
        "src.api.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
