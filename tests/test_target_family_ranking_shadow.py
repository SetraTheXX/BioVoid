from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.analyze_target_family_ranking import (
    RankingAnalysisError,
    analyze_target_family_ranking,
)


def _pocket(pocket_id: str, volume: float, enclosure: float, depth: float) -> dict:
    return {
        "pocket_id": pocket_id,
        "volume": volume,
        "enclosure": enclosure,
        "depth": depth,
        "enclosure_ray_length": 8.0,
    }


def _inputs(tmp_path: Path, *, score_used: bool = False) -> tuple[Path, Path, Path]:
    case_id = "PF00497:TEST:case"
    static_path = tmp_path / "static.json"
    evaluation_path = tmp_path / "evaluation.json"
    cohort_path = tmp_path / "cohort.json"
    static_path.write_text(
        json.dumps(
            {
                "family_id": "PF00497",
                "detector": {"version": "canonical-static-v1"},
                "cases": {
                    case_id: {
                        "structure_id": "TEST",
                        "pocket_count": 3,
                        "top_pockets": [
                            _pocket("BV-1", 220.0, 0.40, 3.20),
                            _pocket("BV-2", 200.0, 0.80, 6.40),
                            _pocket("BV-3", 100.0, 0.20, 1.60),
                        ],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    evaluation_path.write_text(
        json.dumps(
            {
                "detector_target_blind": True,
                "evaluator_only": True,
                "records": {
                    case_id: {
                        "alignment": {
                            "status": "ACCEPTED",
                            "fit_rmsd_angstrom": 1.0,
                            "warnings": [],
                        },
                        "case_evaluation": {
                            "status": "completed",
                            "score_used": score_used,
                            "dcc_by_rank": [10.0, 2.0, 20.0],
                            "dca_by_rank": [10.0, 2.0, 20.0],
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    cohort_path.write_text(
        json.dumps({"cases": [{"case_id": case_id, "split": "development"}]}),
        encoding="utf-8",
    )
    return static_path, evaluation_path, cohort_path


def test_shadow_analysis_keeps_depth_derived_and_marks_top10_scope(tmp_path: Path) -> None:
    static, evaluation, cohort = _inputs(tmp_path)
    output = tmp_path / "report.json"
    markdown = tmp_path / "report.md"

    report = analyze_target_family_ranking(
        static_run_path=static,
        evaluation_report_path=evaluation,
        cohort_path=cohort,
        output_path=output,
        markdown_output_path=markdown,
    )

    case = report["cases"][0]
    assert report["canonical_artifact_modified"] is False
    assert report["scope"]["tail_censored_case_count"] == 0
    assert case["depth_audit"]["within_tolerance"] is True
    assert case["depth_audit"]["used_as_independent_feature"] is False
    assert case["shadow"]["order_original_ranks"][:2] == [2, 1]
    assert case["canonical"]["dcc"]["best_rank"] == 2
    assert case["shadow"]["dcc"]["best_rank"] == 1
    assert output.is_file()
    assert markdown.is_file()


def test_shadow_analysis_rejects_evaluator_score_usage(tmp_path: Path) -> None:
    static, evaluation, cohort = _inputs(tmp_path, score_used=True)

    with pytest.raises(RankingAnalysisError, match="score_used"):
        analyze_target_family_ranking(
            static_run_path=static,
            evaluation_report_path=evaluation,
            cohort_path=cohort,
            output_path=tmp_path / "report.json",
            markdown_output_path=tmp_path / "report.md",
        )


def test_shadow_analysis_marks_tail_censoring(tmp_path: Path) -> None:
    static, evaluation, cohort = _inputs(tmp_path)
    payload = json.loads(static.read_text(encoding="utf-8"))
    case = next(iter(payload["cases"].values()))
    case["pocket_count"] = 12
    static.write_text(json.dumps(payload), encoding="utf-8")

    report = analyze_target_family_ranking(
        static_run_path=static,
        evaluation_report_path=evaluation,
        cohort_path=cohort,
        output_path=tmp_path / "report.json",
        markdown_output_path=tmp_path / "report.md",
    )

    assert report["scope"]["tail_censored_case_count"] == 1
    assert report["cases"][0]["tail_censored"] is True
