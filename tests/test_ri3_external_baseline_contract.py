from __future__ import annotations

from pathlib import Path


def test_p2rank_parser_normalizes_headers_and_keeps_target_blind(tmp_path: Path) -> None:
    from scripts.run_ri3_external_baseline import _parse_p2rank_output

    output = tmp_path / "out"
    output.mkdir()
    (output / "prepared_detector.pdb_predictions.csv").write_text(
        "name     ,  rank,   score, center_x, center_y, center_z, residue_ids\n"
        "pocket1  ,     1,  4.2,    1.0,    2.0,    3.0, A_10 A_11\n",
        encoding="ascii",
    )

    rows = _parse_p2rank_output(output, "prepared_detector.pdb")

    assert rows[0]["rank"] == 1
    assert rows[0]["center_x"] == 1.0
    assert rows[0]["residues"] == ("A_10", "A_11")
    assert "ground_truth" not in rows[0]
    assert "ligand_center" not in rows[0]


def test_fpocket_parser_extracts_center_and_metrics(tmp_path: Path) -> None:
    from scripts.run_ri3_external_baseline import _parse_fpocket_output

    output = tmp_path / "prepared_detector_out"
    pockets = output / "pockets"
    pockets.mkdir(parents=True)
    (output / "prepared_detector_info.txt").write_text(
        "Pocket 1 :\n\tScore :\t0.246\n\tDruggability Score :\t0.719\n\tVolume :\t738.603\n",
        encoding="ascii",
    )
    (pockets / "pocket1_atm.pdb").write_text(
        "ATOM      1  C   ALA A   1       1.000   2.000   3.000  1.00 20.00           C\n",
        encoding="ascii",
    )

    rows = _parse_fpocket_output(output)

    assert rows[0]["rank"] == 1
    assert rows[0]["center"] == (1.0, 2.0, 3.0)
    assert rows[0]["volume"] == 738.603
    assert rows[0]["druggability_score"] == 0.719


def test_external_baseline_limits_are_single_worker() -> None:
    from scripts.run_ri3_external_baseline import BASELINE_CONFIG

    assert all(config["memory"] == "2g" for config in BASELINE_CONFIG.values())
    assert all(config["timeout_seconds"] <= 240 for config in BASELINE_CONFIG.values())
