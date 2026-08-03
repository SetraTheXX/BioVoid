from __future__ import annotations

from scripts.build_publication_repro_bundle import _bundle_exit_code


def test_publication_bundle_fails_closed_when_files_are_missing() -> None:
    assert _bundle_exit_code(0) == 0
    assert _bundle_exit_code(1) == 1
    assert _bundle_exit_code(6) == 1
