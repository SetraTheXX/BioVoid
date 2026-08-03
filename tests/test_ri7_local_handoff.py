from __future__ import annotations

from pathlib import Path

import pytest

from scripts.check_ri7_local_handoff import (
    RI7HandoffError,
    REQUIRED_SOURCE_FILES,
    validate_source_contract,
)


def test_current_source_contract_is_complete() -> None:
    result = validate_source_contract()
    assert result["status"] == "pass"
    assert result["forbidden_tracked_paths"] == []
    assert result["claim_boundary_checked"] is True
    assert result["status_index_checked"] is True


def test_source_contract_fails_closed_when_required_file_is_missing(tmp_path: Path) -> None:
    for relative_path in REQUIRED_SOURCE_FILES:
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("placeholder", encoding="utf-8")

    missing = tmp_path / REQUIRED_SOURCE_FILES[0]
    missing.unlink()

    with pytest.raises(RI7HandoffError, match="missing source files"):
        validate_source_contract(tmp_path)
