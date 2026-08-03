from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_standalone_docker_image_is_loopback_only_by_default() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert '"--host", "127.0.0.1"' in dockerfile
    assert "--allow-remote" not in dockerfile


def test_compose_makes_remote_container_bind_explicit_and_keeps_host_loopback() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert '"127.0.0.1:8000:8000"' in compose
    assert "--allow-remote" in compose
