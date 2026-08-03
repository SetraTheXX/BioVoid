from __future__ import annotations

from scripts.run_phase6_api import is_loopback_host


def test_api_bind_policy_accepts_loopback_targets() -> None:
    assert is_loopback_host("127.0.0.1")
    assert is_loopback_host("::1")
    assert is_loopback_host("localhost")


def test_api_bind_policy_rejects_remote_targets_by_default() -> None:
    assert not is_loopback_host("0.0.0.0")
    assert not is_loopback_host("192.168.1.10")
