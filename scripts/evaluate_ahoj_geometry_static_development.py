"""Run the bounded evaluator-side AHoJ development diagnostic.

The canonical static run is already complete and target-blind.  This command
opens only the six sealed development holo structures, aligns their selected
ligand to the prepared apo frame using protein C-alpha atoms, and evaluates
the retained full pocket list with the pre-frozen DCC/DCA protocol.  It never
opens validation/temporal structures and never changes detector ranking,
NMA, external baselines, or ML.

The output is private because it contains holo-derived coordinates.  The
case-level decomposition deliberately separates candidate-universe coverage
from ranking recall; an unavailable alignment is retained as a visible case
status rather than silently removed from the denominator.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.seal_ahoj_geometry_cohort import _read_json  # noqa: E402
from src.benchmark_v1 import CaseEvaluation, evaluate_case, phase6_frozen_protocol_v1  # noqa: E402
from src.evaluator_format import adapt_biovoid_pockets  # noqa: E402
from src.fetcher import FetchError, fetch_structure_input  # noqa: E402
from src.ground_truth_alignment import (  # noqa: E402
    AlignmentPolicy,
    ChainPair,
    GroundTruthAlignmentError,
    LigandSelector,
    build_aligned_ground_truth_from_files,
)
from src.structure_preparation import (  # noqa: E402
    MODIFIED_AMINO_ACIDS,
    PROTEIN_RESIDUES,
    StructureSource,
    load_structure_atoms,
)


DEFAULT_COHORT = (
    REPO_ROOT
    / "local-private/research/geometry-data-source-catalog/ahoj-v1/ahoj-geometry-cohort-v1.json"
)
DEFAULT_SOURCE_CATALOG = (
    REPO_ROOT
    / "local-private/research/geometry-data-source-catalog/ahoj-v1/"
    "ahoj-geometry-source-catalog-v1.json"
)
DEFAULT_MANIFEST = (
    REPO_ROOT
    / "data/runtime/target-family/cohort-ahoj-geometry-v1/ahoj-geometry-detector-manifest-v1.json"
)
DEFAULT_STATIC_RUN = (
    REPO_ROOT
    / "data/runtime/target-family/cohort-ahoj-geometry-v1/static-development-pilot-v1/"
    "ahoj-geometry-static-pilot-v1.json"
)
DEFAULT_PREFLIGHT = (
    REPO_ROOT
    / "data/runtime/target-family/cohort-ahoj-geometry-v1/development-materialization-v2/"
    "development-preflight-v2.json"
)
DEFAULT_OUTPUT_ROOT = (
    REPO_ROOT
    / "local-private/research/geometry-data-source-catalog/ahoj-v1/"
    "evaluator-development-v1"
)
DEFAULT_HOLO_ROOT = DEFAULT_OUTPUT_ROOT / "holo"
DEFAULT_REPORT = DEFAULT_OUTPUT_ROOT / "ahoj-geometry-static-development-evaluation-v1.json"

MAX_CASES = 6
MAX_DISK_BYTES = 1 * 1024**3
REPORT_SCHEMA_VERSION = "biovoid-ahoj-geometry-static-development-evaluation-v1"
ALIGNMENT_POLICY = AlignmentPolicy(
    policy_version="ground-truth-alignment-v1-ahoj-geometry-development-structural-recovery",
    ambiguous_sequence_policy="structural_fit",
)
PROTOCOL = phase6_frozen_protocol_v1()
PROTEIN_NAMES = PROTEIN_RESIDUES | MODIFIED_AMINO_ACIDS
FORBIDDEN_STATIC_TOKENS = ("holo", "ligand", "evaluator", "ground_truth", "bio_score")


class AhojEvaluationError(RuntimeError):
    """Raised when the private AHoJ evaluator contract is invalid."""


def _stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _directory_size_bytes(root: Path) -> int:
    total = 0
    if not root.exists():
        return total
    for directory, _, filenames in os.walk(root, followlinks=False):
        for filename in filenames:
            path = Path(directory) / filename
            if not path.is_symlink():
                total += path.stat().st_size
    return total


def _relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path.resolve()).replace("\\", "/")


def _require_mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AhojEvaluationError(f"{field} must be an object")
    return value


def _validate_inputs(
    cohort: Mapping[str, Any],
    manifest: Mapping[str, Any],
    preflight: Mapping[str, Any],
    static_run: Mapping[str, Any],
) -> tuple[list[Mapping[str, Any]], dict[str, Mapping[str, Any]]]:
    if cohort.get("schema_version") != "biovoid-ahoj-geometry-cohort-v1":
        raise AhojEvaluationError("unsupported AHoJ private cohort schema")
    if cohort.get("coordinates_downloaded") is not False:
        raise AhojEvaluationError("sealed cohort coordinates_downloaded flag drifted")
    if cohort.get("evaluator_started") is not False:
        raise AhojEvaluationError("sealed cohort evaluator_started flag drifted")
    if manifest.get("schema_version") != "biovoid-ahoj-geometry-detector-manifest-v1":
        raise AhojEvaluationError("unsupported AHoJ detector manifest schema")
    if manifest.get("manifest_kind") != "target_blind_apo_full_structure_manifest":
        raise AhojEvaluationError("detector manifest is not target-blind")
    if manifest.get("boundary") != "apo_full_structure_only_v1":
        raise AhojEvaluationError("detector manifest is not full-structure apo-only")
    if manifest.get("constraints", {}).get("analysis_workers") != 1:
        raise AhojEvaluationError("evaluator requires the one-worker sealed pilot")
    if manifest.get("constraints", {}).get("include_motion") is not False:
        raise AhojEvaluationError("evaluator requires motion-disabled static input")
    if preflight.get("schema_version") != "biovoid-ahoj-geometry-development-preflight-v1":
        raise AhojEvaluationError("unsupported AHoJ preflight schema")
    if preflight.get("status") != "ready_for_static_detector_gate":
        raise AhojEvaluationError("AHoJ preflight is not ready")
    if preflight.get("detector_manifest_sha256") != manifest.get("manifest_sha256"):
        raise AhojEvaluationError("preflight is not bound to the sealed detector manifest")
    if static_run.get("schema_version") != "biovoid-ahoj-geometry-static-pilot-v1":
        raise AhojEvaluationError("unsupported AHoJ static pilot schema")
    if static_run.get("status") != "completed_target_blind_static_diagnostic":
        raise AhojEvaluationError("static pilot is not complete")
    if static_run.get("manifest_sha256") != manifest.get("manifest_sha256"):
        raise AhojEvaluationError("static pilot is not bound to detector manifest")
    execution = _require_mapping(static_run.get("execution"), "static_run.execution")
    if execution.get("workers") != 1 or execution.get("motion_enabled") is not False:
        raise AhojEvaluationError("static pilot violates one-worker/motion-off boundary")
    if execution.get("candidate_retention") != "full_final_pocket_list":
        raise AhojEvaluationError(
            "full candidate retention is required before detector-vs-ranking decomposition"
        )
    cases = cohort.get("cases")
    manifest_cases = manifest.get("cases")
    if not isinstance(cases, list) or not isinstance(manifest_cases, list):
        raise AhojEvaluationError("cohort or manifest cases are missing")
    private_by_case = {str(case.get("case_id")): case for case in cases if isinstance(case, Mapping)}
    development_manifest = [
        case
        for case in manifest_cases
        if isinstance(case, Mapping) and case.get("split") == "development"
    ]
    if len(development_manifest) != MAX_CASES:
        raise AhojEvaluationError("exactly six development cases are required")
    selected: list[Mapping[str, Any]] = []
    for detector_case in development_manifest:
        case_id = str(detector_case.get("case_id"))
        private_case = private_by_case.get(case_id)
        if private_case is None or private_case.get("split") != "development":
            raise AhojEvaluationError(f"private development case missing: {case_id}")
        if str(private_case.get("apo_structure_id")).upper() != str(
            detector_case.get("structure_id")
        ).upper():
            raise AhojEvaluationError(f"apo structure mismatch for {case_id}")
        if not private_case.get("holo_structure_id") or not private_case.get("ligand_code"):
            raise AhojEvaluationError(f"holo/ligand metadata missing for {case_id}")
        selected.append(private_case)
    static_cases = static_run.get("cases")
    if not isinstance(static_cases, Mapping):
        raise AhojEvaluationError("static pilot cases are missing")
    static_by_case = {str(key): value for key, value in static_cases.items()}
    for case in selected:
        static_case = static_by_case.get(str(case["case_id"]))
        if not isinstance(static_case, Mapping) or static_case.get("status") != "completed":
            raise AhojEvaluationError(f"static case is not completed: {case['case_id']}")
        pockets = static_case.get("all_pockets")
        if not isinstance(pockets, list) or not pockets:
            raise AhojEvaluationError(f"full static pocket list missing: {case['case_id']}")
        if static_case.get("candidate_retention") != "full_final_pocket_list":
            raise AhojEvaluationError(f"static candidate retention drifted: {case['case_id']}")
    return sorted(selected, key=lambda case: str(case["case_id"])), static_by_case


def _source_pair_index(source_catalog: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    if source_catalog.get("schema_version") != "biovoid-ahoj-geometry-source-catalog-v1":
        raise AhojEvaluationError("unsupported AHoJ source catalog schema")
    pairs = source_catalog.get("pairs")
    if not isinstance(pairs, list):
        raise AhojEvaluationError("AHoJ source catalog pairs are missing")
    indexed: dict[str, Mapping[str, Any]] = {}
    for pair in pairs:
        if not isinstance(pair, Mapping):
            continue
        apo_id = str(pair.get("apo_structure_id", "")).upper()
        if apo_id:
            indexed[apo_id] = pair
    return indexed


def _protein_chain_ids(path: Path) -> tuple[str, ...]:
    atoms = load_structure_atoms(path)
    chain_ids = {
        str(atom.chain_id)
        for atom in atoms
        if atom.res_name.upper() in PROTEIN_NAMES and atom.atom_name.strip().upper() == "CA"
    }
    return tuple(sorted(chain_ids))


def _ligand_candidates(
    holo_path: Path,
    *,
    ligand_code: str,
    allowed_chain_ids: Sequence[str],
) -> list[tuple[LigandSelector, int]]:
    allowed = {str(value).strip() for value in allowed_chain_ids if str(value).strip()}
    if not allowed:
        raise GroundTruthAlignmentError("AHoJ ligand chain list is empty")
    grouped: dict[tuple[str, int, str, str], list[Any]] = defaultdict(list)
    for atom in load_structure_atoms(holo_path):
        if (
            atom.record.upper() != "HETATM"
            or atom.res_name.strip().upper() != ligand_code.strip().upper()
            or atom.chain_id not in allowed
        ):
            continue
        grouped[(atom.chain_id, int(atom.res_id), str(atom.ins_code).strip(), atom.res_name.upper())].append(
            atom
        )
    candidates: list[tuple[LigandSelector, int]] = []
    for (chain_id, residue_id, insertion_code, residue_name), atoms in sorted(grouped.items()):
        heavy_count = sum(atom.element.strip().upper() not in {"H", "D"} for atom in atoms)
        if heavy_count <= 0:
            continue
        candidates.append(
            (
                LigandSelector(
                    residue_name=residue_name,
                    chain_id=chain_id,
                    residue_id=residue_id,
                    insertion_code=insertion_code,
                ),
                heavy_count,
            )
        )
    if not candidates:
        raise GroundTruthAlignmentError(
            f"No HETATM ligand residue matched {ligand_code} on chains {sorted(allowed)}"
        )
    return candidates


def _source_target_residue_id(source_pair: Mapping[str, Any]) -> int | None:
    """Read the immutable AHoJ query residue for deterministic copy selection."""
    query = str(source_pair.get("ahoj_query") or "").strip().split()
    if len(query) < 4:
        return None
    try:
        return int(query[-1])
    except ValueError:
        return None


def _alignment_candidates(
    *,
    case: Mapping[str, Any],
    source_pair: Mapping[str, Any],
    apo_path: Path,
    holo_path: Path,
) -> list[tuple[Any, ChainPair, LigandSelector]]:
    apo_chains = _protein_chain_ids(apo_path)
    holo_chains = _protein_chain_ids(holo_path)
    preferred_apo = str(source_pair.get("query_chain_id") or "").strip()
    if preferred_apo not in apo_chains:
        preferred_apo = str(case.get("apo_chain_ids", [""])[0]).strip()
    if preferred_apo not in apo_chains:
        preferred_apo = apo_chains[0] if apo_chains else ""
    ligand_chain_ids = tuple(str(value).strip() for value in case.get("holo_ligand_chain_ids", []))
    ligand_candidates = _ligand_candidates(
        holo_path,
        ligand_code=str(case["ligand_code"]),
        allowed_chain_ids=ligand_chain_ids,
    )
    target_residue_id = _source_target_residue_id(source_pair)
    results: list[tuple[Any, ChainPair, LigandSelector]] = []
    for selector, _heavy_count in ligand_candidates:
        holo_chain = selector.chain_id
        if holo_chain not in holo_chains:
            continue
        chain_pairs = [
            ChainPair(apo_chain_id=preferred_apo, holo_chain_id=holo_chain),
        ]
        for chain_pair in chain_pairs:
            try:
                alignment = build_aligned_ground_truth_from_files(
                    case_id=str(case["case_id"]),
                    structure_id=str(case["apo_structure_id"]).upper(),
                    prepared_apo_path=apo_path,
                    holo_path=holo_path,
                    ligand=selector,
                    chain_pairs=(chain_pair,),
                    provenance_label="ahoj-biolip2-site-assignment-v1-geometry-evaluator",
                    policy=ALIGNMENT_POLICY,
                    ligand_residues=(
                        f"{selector.chain_id}:{selector.residue_name}:{selector.residue_id}",
                    ),
                )
            except GroundTruthAlignmentError:
                continue
            results.append((alignment, chain_pair, selector))
    if not results:
        raise GroundTruthAlignmentError(
            f"No valid apo/holo alignment for {case['case_id']} using declared ligand chains"
        )
    results.sort(
        key=lambda item: (
            float(item[0].fit_rmsd_angstrom),
            -int(item[0].matched_residue_count),
            -float(item[0].sequence_identity),
            abs(item[2].residue_id - target_residue_id)
            if target_residue_id is not None
            else 0,
            item[1].apo_chain_id,
            item[1].holo_chain_id,
            item[2].residue_id,
            item[2].insertion_code,
        )
    )
    if len(results) > 1:
        best_rmsd = float(results[0][0].fit_rmsd_angstrom)
        second_rmsd = float(results[1][0].fit_rmsd_angstrom)
        best_delta = (
            abs(results[0][2].residue_id - target_residue_id)
            if target_residue_id is not None
            else 0
        )
        second_delta = (
            abs(results[1][2].residue_id - target_residue_id)
            if target_residue_id is not None
            else 0
        )
        if (
            abs(second_rmsd - best_rmsd)
            <= ALIGNMENT_POLICY.structural_tie_rmsd_tolerance_angstrom
            and second_delta == best_delta
        ):
            raise GroundTruthAlignmentError(
                "Multiple AHoJ ligand/chain alignments remain tied within the recovery tolerance"
            )
    return results


def _first_hit(values: Sequence[float], tolerance: float, *, joint: Sequence[bool] | None = None) -> int | None:
    for index, value in enumerate(values, start=1):
        if joint is not None:
            if joint[index - 1]:
                return index
        elif value <= tolerance:
            return index
    return None


def decompose_case_evaluation(evaluation: CaseEvaluation, protocol: Any) -> dict[str, Any]:
    """Separate full-list localization coverage from ranked recall."""
    if evaluation.status != "completed":
        return {
            "status": evaluation.status,
            "candidate_universe": {
                "dcc_hit": False,
                "dca_hit": False,
                "joint_hit": False,
            },
            "best_rank": {"dcc": None, "dca": None, "joint": None},
            "taxonomy": "alignment_or_detector_unavailable",
        }
    dcc = tuple(float(value) for value in evaluation.dcc_by_rank)
    dca = tuple(float(value) for value in evaluation.dca_by_rank)
    dcc_tolerance = float(protocol.dcc_tolerance_angstrom)
    dca_tolerance = float(protocol.dca_tolerance_angstrom)
    joint = tuple(left <= dcc_tolerance and right <= dca_tolerance for left, right in zip(dcc, dca))
    universe = {
        "dcc_hit": any(value <= dcc_tolerance for value in dcc),
        "dca_hit": any(value <= dca_tolerance for value in dca),
        "joint_hit": any(joint),
    }
    best_rank = {
        "dcc": _first_hit(dcc, dcc_tolerance),
        "dca": _first_hit(dca, dca_tolerance),
        "joint": _first_hit(dcc, dcc_tolerance, joint=joint),
    }
    if universe["joint_hit"] and best_rank["joint"] is not None and best_rank["joint"] > 5:
        taxonomy = "A_candidate_present_ranking_miss"
    elif universe["joint_hit"]:
        taxonomy = "candidate_present_with_top5_support"
    elif universe["dcc_hit"] or universe["dca_hit"]:
        taxonomy = "B_metric_disagreement"
    else:
        taxonomy = "C_candidate_universe_miss"
    return {
        "status": evaluation.status,
        "candidate_universe": universe,
        "best_rank": best_rank,
        "top_k_dcc_hits": {
            **{str(key): bool(value) for key, value in evaluation.top_k_dcc_hits.items()},
            "10": any(value <= dcc_tolerance for value in dcc[:10]),
        },
        "top_k_dca_hits": {
            **{str(key): bool(value) for key, value in evaluation.top_k_dca_hits.items()},
            "10": any(value <= dca_tolerance for value in dca[:10]),
        },
        "taxonomy": taxonomy,
        "candidate_count": len(dcc),
    }


def _case_summary(evaluation: CaseEvaluation) -> dict[str, Any]:
    payload = asdict(evaluation)
    payload["top_k_dcc_hits"] = {str(key): bool(value) for key, value in evaluation.top_k_dcc_hits.items()}
    payload["top_k_dca_hits"] = {str(key): bool(value) for key, value in evaluation.top_k_dca_hits.items()}
    return payload


def _safe_error(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"[:500]


def _empty_counts() -> dict[str, int]:
    return {
        "completed": 0,
        "holo_download_failed": 0,
        "alignment_unavailable": 0,
        "resource_blocked": 0,
        "A_candidate_present_ranking_miss": 0,
        "B_metric_disagreement": 0,
        "C_candidate_universe_miss": 0,
        "candidate_present_with_top5_support": 0,
    }


def run_ahoj_geometry_evaluator(
    *,
    cohort_path: Path = DEFAULT_COHORT,
    source_catalog_path: Path = DEFAULT_SOURCE_CATALOG,
    manifest_path: Path = DEFAULT_MANIFEST,
    static_run_path: Path = DEFAULT_STATIC_RUN,
    preflight_path: Path = DEFAULT_PREFLIGHT,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    holo_root: Path = DEFAULT_HOLO_ROOT,
    report_path: Path = DEFAULT_REPORT,
    max_disk_bytes: int = MAX_DISK_BYTES,
    user_approved: bool = False,
) -> dict[str, Any]:
    if not user_approved:
        raise AhojEvaluationError("evaluator requires --approve-evaluator")
    if not 1 <= max_disk_bytes <= MAX_DISK_BYTES:
        raise ValueError("max_disk_bytes must be between 1 byte and 1 GB")
    cohort = _read_json(cohort_path.resolve())
    source_catalog = _read_json(source_catalog_path.resolve())
    manifest = _read_json(manifest_path.resolve())
    preflight = _read_json(preflight_path.resolve())
    static_run = _read_json(static_run_path.resolve())
    cases, static_by_case = _validate_inputs(cohort, manifest, preflight, static_run)
    source_by_apo = _source_pair_index(source_catalog)
    if output_root.exists() and any(output_root.iterdir()):
        raise AhojEvaluationError(f"evaluator output root is not empty: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    holo_root.mkdir(parents=True, exist_ok=True)
    if _directory_size_bytes(output_root) + _directory_size_bytes(holo_root) > max_disk_bytes:
        raise AhojEvaluationError("evaluator output quota exceeded before start")

    report: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "status": "running",
        "family_id": cohort.get("family_id"),
        "cohort_sha256": cohort.get("cohort_sha256"),
        "detector_manifest_sha256": manifest.get("manifest_sha256"),
        "static_run_sha256": static_run.get("run_sha256"),
        "source_catalog_sha256": _sha256_file(source_catalog_path.resolve()),
        "alignment_policy": asdict(ALIGNMENT_POLICY),
        "protocol": PROTOCOL.to_manifest(),
        "execution": {
            "workers": 1,
            "max_cases": MAX_CASES,
            "max_disk_bytes": max_disk_bytes,
            "validation_temporal_opened": False,
            "detector_rerun": False,
            "ranking_changed": False,
            "motion_enabled": False,
            "external_baselines_enabled": False,
            "ml_enabled": False,
        },
        "claim_boundary": "development_only_detection_vs_ranking_diagnostic",
        "counts": _empty_counts(),
        "records": {},
        "created_at_utc": _utc_now(),
        "updated_at_utc": _utc_now(),
        "report_sha256": None,
    }

    for case in cases:
        case_id = str(case["case_id"])
        apo_id = str(case["apo_structure_id"]).upper()
        started = time.perf_counter()
        record: dict[str, Any] = {
            "case_id": case_id,
            "structure_id": apo_id,
            "split": "development",
            "status": "alignment_unavailable",
            "detector_arm": "canonical_static_v1_target_blind",
            "evaluator_arm": "ahoj_biolip2_site_assignment_v1",
        }
        try:
            source_pair = source_by_apo.get(apo_id)
            if source_pair is None:
                raise AhojEvaluationError(f"source catalog pair missing for {apo_id}")
            static_case = static_by_case[case_id]
            prepared_path = (REPO_ROOT / str(static_case["prepared_path"])).resolve()
            if not prepared_path.is_file():
                raise AhojEvaluationError(f"prepared apo path missing: {prepared_path}")
            holo_id = str(case["holo_structure_id"]).upper()
            holo_source = fetch_structure_input(
                StructureSource(provider="rcsb", identifier=holo_id, representation="asymmetric_unit"),
                cache_dir=holo_root,
            )
            holo_path = holo_source.path.resolve()
            if _directory_size_bytes(output_root) + _directory_size_bytes(holo_root) > max_disk_bytes:
                raise AhojEvaluationError("evaluator holo output quota exceeded")
            alignments = _alignment_candidates(
                case=case,
                source_pair=source_pair,
                apo_path=prepared_path,
                holo_path=holo_path,
            )
            alignment, chain_pair, selector = alignments[0]
            pockets = static_case["all_pockets"]
            detector_record = adapt_biovoid_pockets(
                apo_id,
                pockets,
                provenance={
                    "source": "ahoj-geometry-static-development-v1",
                    "candidate_retention": "full_final_pocket_list",
                    "score_used": False,
                },
            )
            evaluation = evaluate_case(detector_record, alignment.ground_truth, PROTOCOL)
            decomposition = decompose_case_evaluation(evaluation, PROTOCOL)
            record.update(
                {
                    "status": "completed",
                    "holo_source": {
                        "structure_id": holo_id,
                        "path": _relative(holo_path),
                        "sha256": _sha256_file(holo_path),
                        "bytes": holo_path.stat().st_size,
                        "url": f"https://files.rcsb.org/download/{holo_id.lower()}.cif",
                    },
                    "ligand_selector": asdict(selector),
                    "chain_pair": asdict(chain_pair),
                    "alignment": {
                        "status": alignment.status,
                        "matched_residue_count": alignment.matched_residue_count,
                        "sequence_identity": alignment.sequence_identity,
                        "fit_rmsd_angstrom": alignment.fit_rmsd_angstrom,
                        "alignment_sha256": alignment.alignment_sha256,
                        "ground_truth_sha256": alignment.ground_truth_sha256,
                        "warnings": list(alignment.warnings),
                    },
                    "ground_truth": asdict(alignment.ground_truth),
                    "case_evaluation": _case_summary(evaluation),
                    "decomposition": decomposition,
                }
            )
            report["counts"]["completed"] += 1
            report["counts"][decomposition["taxonomy"]] += 1
        except FetchError as exc:
            record.update({"status": "holo_download_failed", "error": _safe_error(exc)})
            report["counts"]["holo_download_failed"] += 1
        except GroundTruthAlignmentError as exc:
            record.update({"status": "alignment_unavailable", "error": _safe_error(exc)})
            report["counts"]["alignment_unavailable"] += 1
        except (AhojEvaluationError, OSError, ValueError, KeyError, TypeError) as exc:
            record.update({"status": "alignment_unavailable", "error": _safe_error(exc)})
            report["counts"]["alignment_unavailable"] += 1
        record["runtime_seconds"] = round(time.perf_counter() - started, 6)
        report["records"][case_id] = record
        report["updated_at_utc"] = _utc_now()
        report["report_sha256"] = _stable_hash(
            {key: value for key, value in report.items() if key != "report_sha256"}
        )
        _write_json(report_path.resolve(), report)

    completed = int(report["counts"]["completed"])
    report["status"] = (
        "completed_development_evaluator_diagnostic"
        if completed == MAX_CASES
        else "completed_with_alignment_or_download_failures"
    )
    report["final_disk_bytes"] = _directory_size_bytes(output_root) + _directory_size_bytes(holo_root)
    report["updated_at_utc"] = _utc_now()
    report["report_sha256"] = _stable_hash(
        {key: value for key, value in report.items() if key != "report_sha256"}
    )
    _write_json(report_path.resolve(), report)
    print(
        "AHoJ evaluator: "
        f"{report['status']} completed={report['counts']['completed']} "
        f"alignment_unavailable={report['counts']['alignment_unavailable']} "
        f"holo_download_failed={report['counts']['holo_download_failed']}"
    )
    print(f"private evaluator report: {report_path}")
    print("validation/temporal/detector-rerun/NMA/external-baseline/ML: no")
    return report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort", type=Path, default=DEFAULT_COHORT)
    parser.add_argument("--source-catalog", type=Path, default=DEFAULT_SOURCE_CATALOG)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--static-run", type=Path, default=DEFAULT_STATIC_RUN)
    parser.add_argument("--preflight", type=Path, default=DEFAULT_PREFLIGHT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--holo-root", type=Path, default=DEFAULT_HOLO_ROOT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--max-disk-bytes", type=int, default=MAX_DISK_BYTES)
    parser.add_argument("--approve-evaluator", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        report = run_ahoj_geometry_evaluator(
            cohort_path=args.cohort,
            source_catalog_path=args.source_catalog,
            manifest_path=args.manifest,
            static_run_path=args.static_run,
            preflight_path=args.preflight,
            output_root=args.output_root,
            holo_root=args.holo_root,
            report_path=args.report,
            max_disk_bytes=args.max_disk_bytes,
            user_approved=args.approve_evaluator,
        )
    except (AhojEvaluationError, OSError, ValueError, KeyError, TypeError) as exc:
        print(f"AHoJ evaluator error: {exc}", file=sys.stderr)
        return 2
    return 0 if report["status"] == "completed_development_evaluator_diagnostic" else 2


if __name__ == "__main__":
    raise SystemExit(main())
