"""Phase 0 recovery governance regression tests."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src.benchmark import LegacyBenchmarkDisabledError, benchmark_single, run_benchmark
from src.cache import AnalysisCache
from src.cli import cmd_benchmark
from src.config import PATHS, RECOVERY


def test_public_gitignore_blocks_private_and_generated_scientific_assets() -> None:
    ignore_rules = Path(".gitignore").read_text(encoding="utf-8").splitlines()

    required_rules = {
        "memory-bank/",
        "plans/",
        "artifacts/",
        "data/",
        "generated/",
        "outputs/",
        "*.db",
        "*.sqlite",
        "*.pdb",
        "*.ent",
        "*.cif",
        "*.mmcif",
        "*.pkl",
        "*.joblib",
        "*.pt",
        "*.pth",
        "*.onnx",
        "*.h5",
        "*.safetensors",
        "frontend/node_modules/",
        "frontend/dist/",
    }

    assert required_rules <= set(ignore_rules)


def test_recovery_outputs_are_isolated_from_legacy_paths() -> None:
    assert PATHS.runtime_root == Path("data/runtime")
    assert PATHS.results.is_relative_to(PATHS.runtime_root)
    assert PATHS.frames.is_relative_to(PATHS.runtime_root)
    assert PATHS.cache.is_relative_to(PATHS.runtime_root)
    assert PATHS.atlas_db.is_relative_to(PATHS.runtime_root)

    assert PATHS.results != PATHS.legacy_results
    assert PATHS.frames != PATHS.legacy_frames
    assert PATHS.cache != PATHS.legacy_cache
    assert PATHS.atlas_db != PATHS.legacy_atlas_db


def test_default_cache_uses_recovery_runtime_root(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    cache = AnalysisCache()

    assert cache.cache_dir == PATHS.cache
    assert cache.cache_dir != PATHS.legacy_cache


def test_api_reads_recovery_atlas_and_results_paths() -> None:
    from src.api.app import ATLAS_DB_PATH, PROJECT_ROOT, RESULTS_DIR

    assert ATLAS_DB_PATH == PROJECT_ROOT / PATHS.atlas_db
    assert RESULTS_DIR == PROJECT_ROOT / PATHS.results
    assert ATLAS_DB_PATH != PROJECT_ROOT / PATHS.legacy_atlas_db
    assert RESULTS_DIR != PROJECT_ROOT / PATHS.legacy_results


def test_historical_benchmark_api_is_explicitly_non_canonical() -> None:
    from src.api.app import create_app

    with TestClient(create_app()) as client:
        response = client.get("/benchmark/known-pockets")

    assert response.status_code == 200
    assert response.json()["validation_status"] == "legacy_non_validated"
    assert response.json()["canonical_eligible"] is False
    assert all(
        "center" not in pocket and "known_ligand" not in pocket
        for pocket in response.json()["pockets"]
    )


def test_portal_does_not_present_frozen_historical_claims_as_current() -> None:
    from src.api.portal import render_portal_html

    html = render_portal_html()

    for frozen_claim in (
        "35.0% (7/20)",
        "25.97%",
        "13.11%",
        "MD Validated",
        "Publication Freeze: PASS",
        "AI-powered scoring",
        "open transiently",
    ):
        assert frozen_claim not in html

    assert "canonical React interface" in html
    assert "local interface" in html


def test_recovery_feature_policy_keeps_unvalidated_layers_out_of_canonical_results() -> None:
    assert RECOVERY.mode == "recovery"
    assert RECOVERY.canonical_static_ready is True
    assert RECOVERY.motion_aware == "experimental_default_off"
    assert RECOVERY.ml_reranking == "experimental_default_off"
    assert RECOVERY.docking == "experimental_default_off"
    assert RECOVERY.legacy_benchmark == "disabled"
    assert RECOVERY.bulk_crawler == "disabled"


def test_legacy_benchmark_requires_explicit_opt_in_and_marks_its_output() -> None:
    pockets = [{"center": [9.0, 0.0, 0.0], "bio_score": 0.8}]

    with pytest.raises(LegacyBenchmarkDisabledError):
        benchmark_single("TEST", [0.0, 0.0, 0.0], pockets)

    result = benchmark_single(
        "TEST",
        [0.0, 0.0, 0.0],
        pockets,
        allow_legacy=True,
    )

    assert result.validation_status == "legacy_non_validated"
    assert result.canonical_eligible is False
    assert result.protocol_id == "legacy_score_weighted_v1"


def test_legacy_benchmark_summary_is_quarantined() -> None:
    known = {"TEST": {"center": [0.0, 0.0, 0.0]}}
    predictions = {"TEST": [{"center": [0.0, 0.0, 0.0], "bio_score": 0.8}]}

    with pytest.raises(LegacyBenchmarkDisabledError):
        run_benchmark(predictions, known)

    summary = run_benchmark(predictions, known, allow_legacy=True)

    assert summary.validation_status == "legacy_non_validated"
    assert summary.canonical_eligible is False
    assert summary.protocol_id == "legacy_score_weighted_v1"


def test_cli_benchmark_stops_before_analysis_without_legacy_opt_in() -> None:
    args = SimpleNamespace(verbose=False, allow_legacy_benchmark=False)

    with pytest.raises(SystemExit, match="2"):
        cmd_benchmark(args)


def test_pipeline_defaults_keep_experimental_features_off_and_mark_report(
    tmp_path: Path,
) -> None:
    from main import BioVoidPipeline

    pipeline = BioVoidPipeline(
        "1CBS",
        output_dir=str(tmp_path),
        use_cache=False,
    )
    pipeline.start_time = 0.0
    preparation_report = tmp_path / "preparation_report.json"
    preparation_manifest = tmp_path / "run_manifest.json"
    prepared_structure = tmp_path / "prepared_detector.pdb"
    preparation_report.write_text(
        json.dumps({"status": "valid", "schema_version": "structure-preparation-v1"}),
        encoding="utf-8",
    )
    preparation_manifest.write_text("{}", encoding="utf-8")
    prepared_structure.write_text("END\n", encoding="utf-8")
    pipeline.preparation_result = SimpleNamespace(
        report_path=preparation_report,
        manifest_path=preparation_manifest,
        prepared_path=prepared_structure,
        input_sha256="input",
        prepared_sha256="prepared",
        config_sha256="config",
        report_sha256="report",
    )

    report = pipeline._generate_report()

    from main import PROJECT_ROOT

    assert pipeline.atlas_db_path == PROJECT_ROOT / PATHS.atlas_db
    assert pipeline.atlas_db_path != PATHS.legacy_atlas_db
    assert pipeline.use_ml is False
    assert pipeline.dock is False
    assert pipeline.multiframe is False
    assert report["validation_status"] == "recovery_unvalidated"
    assert report["canonical_eligible"] is False
    assert report["feature_policy"]["motion_aware"] == "experimental_default_off"
    assert report["feature_policy"]["ml_reranking"] == "experimental_default_off"
    assert report["feature_policy"]["docking"] == "experimental_default_off"


@pytest.mark.parametrize(
    "feature_args",
    [
        {"dock": True},
        {"multiframe": True},
        {"use_ml": True},
    ],
)
def test_pipeline_requires_explicit_opt_in_for_experimental_features(
    tmp_path: Path,
    feature_args: dict[str, bool],
) -> None:
    from main import BioVoidPipeline, ExperimentalFeatureDisabledError

    with pytest.raises(ExperimentalFeatureDisabledError):
        BioVoidPipeline(
            "1CBS",
            output_dir=str(tmp_path),
            use_cache=False,
            **feature_args,
        )
