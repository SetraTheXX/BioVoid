"""Offline unit tests for structure fetching and cache behavior."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest

import src.fetcher as fetcher
from src.fetcher import (
    FetchError,
    batch_fetch,
    fetch_pdb,
    fetch_structure_input,
    get_ca_atoms,
    get_structure,
)
from src.structure_preparation import StructureSource


PDB_TEXT = """\
ATOM      1  N   ALA A   1       0.000   0.000   0.000  1.00 20.00           N
ATOM      2  CA  ALA A   1       1.450   0.000   0.000  1.00 20.00           C
ATOM      3  C   ALA A   1       2.100   1.300   0.000  1.00 20.00           C
ATOM      4  O   ALA A   1       1.600   2.400   0.000  1.00 20.00           O
ATOM      5  N   GLY A   2       3.300   1.200   0.000  1.00 20.00           N
ATOM      6  CA  GLY A   2       4.000   2.450   0.000  1.00 20.00           C
ATOM      7  C   GLY A   2       5.500   2.300   0.000  1.00 20.00           C
ATOM      8  O   GLY A   2       6.100   1.250   0.000  1.00 20.00           O
TER
END
"""


def _fake_rcsb_download(pdb_id: str, _format: str, target_path: str) -> None:
    Path(target_path, f"pdb{pdb_id}.ent").write_text(PDB_TEXT, encoding="ascii")


def test_rcsb_download_uses_injected_cache_and_normalizes_filename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mocked = Mock(side_effect=_fake_rcsb_download)
    monkeypatch.setattr(fetcher.rcsb, "fetch", mocked)

    path = fetch_pdb("1ABC", cache_dir=tmp_path)

    assert path == (tmp_path / "1abc.pdb").absolute()
    assert path.read_text(encoding="ascii") == PDB_TEXT
    mocked.assert_called_once_with("1abc", "pdb", target_path=str(tmp_path))


def test_valid_cache_hit_never_calls_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cached = tmp_path / "1abc.pdb"
    cached.write_text(PDB_TEXT, encoding="ascii")
    mocked = Mock(side_effect=AssertionError("network must not be called"))
    monkeypatch.setattr(fetcher.rcsb, "fetch", mocked)

    first = fetch_pdb("1abc", cache_dir=tmp_path)
    second = fetch_pdb("1abc", cache_dir=tmp_path)

    assert first == second == cached.absolute()
    mocked.assert_not_called()


def test_corrupt_cache_is_replaced_through_mock_transport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cached = tmp_path / "1abc.pdb"
    cached.write_text("", encoding="ascii")
    monkeypatch.setattr(fetcher.rcsb, "fetch", _fake_rcsb_download)

    path = fetch_pdb("1abc", cache_dir=tmp_path)

    assert path.read_text(encoding="ascii") == PDB_TEXT


@pytest.mark.parametrize("pdb_id", ["12", "ABCDE", "AB-C", ""])
def test_invalid_rcsb_ids_fail_before_network(tmp_path: Path, pdb_id: str) -> None:
    with pytest.raises(FetchError, match="Invalid PDB ID"):
        fetch_pdb(pdb_id, cache_dir=tmp_path)


def test_local_source_missing_path_fails_closed() -> None:
    source = StructureSource(
        provider="local",
        identifier="fixture",
        representation="local",
        local_path=Path("fixture.pdb"),
    ).model_copy(update={"local_path": None})

    with pytest.raises(FetchError, match="missing local_path"):
        fetch_structure_input(source)


def test_alphafold_download_uses_mock_http_transport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata_response = Mock()
    metadata_response.raise_for_status.return_value = None
    metadata_response.json.return_value = [
        {
            "modelEntityId": "AF-P12345-F1",
            "pdbUrl": "https://example.test/AF-P12345-F1-model_v6.pdb",
            "paeDocUrl": "https://example.test/AF-P12345-F1-pae_v6.json",
            "sequenceStart": 1,
            "sequenceEnd": 100,
            "latestVersion": 6,
        }
    ]
    structure_response = Mock(content=PDB_TEXT.encode("ascii"))
    structure_response.raise_for_status.return_value = None
    get = Mock(side_effect=[metadata_response, structure_response])
    monkeypatch.setattr(fetcher.requests, "get", get)

    path = fetch_pdb("P12345", cache_dir=tmp_path, source="alphafold")

    assert path.name == "AF-P12345.pdb"
    assert path.read_bytes() == PDB_TEXT.encode("ascii")
    assert get.call_count == 2
    assert "/api/prediction/P12345" in get.call_args_list[0].args[0]
    assert get.call_args_list[1].args[0].endswith("model_v6.pdb")
    assert all(call.kwargs["timeout"] == 30 for call in get.call_args_list)


def test_batch_fetch_retries_without_real_sleep(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0

    def flaky_fetch(pdb_id: str, **_kwargs) -> Path:
        nonlocal attempts
        attempts += 1
        if attempts < 2:
            raise FetchError("temporary")
        return tmp_path / f"{pdb_id}.pdb"

    monkeypatch.setattr(fetcher, "fetch_pdb", flaky_fetch)
    monkeypatch.setattr(fetcher.time, "sleep", lambda _seconds: None)

    result = batch_fetch(["1ABC"], cache_dir=tmp_path, max_retries=2)

    assert result["1ABC"] == tmp_path / "1ABC.pdb"
    assert attempts == 2


def test_structure_loading_and_ca_selection(tmp_path: Path) -> None:
    path = tmp_path / "fixture.pdb"
    path.write_text(PDB_TEXT, encoding="ascii")

    structure = get_structure(path)
    ca_atoms = get_ca_atoms(structure)

    assert len(structure) == 8
    assert len(ca_atoms) == 2
    assert set(ca_atoms.atom_name) == {"CA"}
