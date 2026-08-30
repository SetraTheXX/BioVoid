"""Run the BioVoid local research API."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import uvicorn

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.api.app import app
from src.bind_policy import is_loopback_host


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the BioVoid local research API.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    parser.add_argument(
        "--allow-remote",
        action="store_true",
        help="explicitly allow a non-loopback bind (local-only mode rejects it)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not is_loopback_host(args.host) and not args.allow_remote:
        raise SystemExit(
            "Refusing non-loopback bind in local-only mode. "
            "Use --allow-remote only behind an authenticated network boundary."
        )
    app_url = f"http://{args.host}:{args.port}/"
    print(f"[BioVoid] Canonical React application: {app_url}")
    print("[BioVoid] The canonical React interface is served at the root URL.")
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
