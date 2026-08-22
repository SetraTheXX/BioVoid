"""Run a bounded evaluator-only DCC/DCA pilot for the PF00497 static smoke.

The detector-facing manifest and static run remain target-blind.  This command
opens the private apo--holo pairing only after explicit approval, downloads at
most the selected representative holo structures, aligns protein coordinates,
and evaluates the already-produced BioVoid pockets with the frozen DCC/DCA
protocol.  The report is diagnostic-only and never authorizes a discovery or
superiority claim.
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
from typing import Any, Mapping

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.benchmark_v1 import evaluate_case, phase6_frozen_protocol_v1  # noqa: E402
from src.evaluator_format import (  # noqa: E402
    adapt_biovoid_pockets,
    unavailable_record,
)
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
    load_structure_atoms,
)
from src.target_family_ranking import (  # noqa: E402
    CANDIDATE_RETENTION_FULL,
    CANDIDATE_RETENTION_TOP10,
    validate_candidate_retention,
)
from src.target_family_manifest import MAX_PILOT_CASES, validate_detector_manifest  # noqa: E402


DEFAULT_MANIFEST = (
    REPO_ROOT / "data/runtime/target-family/cohort-detector-pfam-v1/"
    "target-family-cohort-detector-pfam-v1.json"
)
DEFAULT_STATIC_RUN = (
    REPO_ROOT / "data/runtime/target-family/static-pilot-pfam-v1-rerun-v2/"
    "target-family-static-pilot-run-v1.json"
)
DEFAULT_FULL_STATIC_RUN = (
    REPO_ROOT / "data/runtime/target-family/static-pilot-pfam-v1-full-candidates/"
    "target-family-static-pilot-run-v1.json"
)
DEFAULT_RECOVERY_RUN = (
    REPO_ROOT / "data/runtime/target-family/static-pilot-recovery-pfam-v1/"
    "target-family-static-recovery-v1.json"
)
DEFAULT_PAIRS = REPO_ROOT / "local-private/research/target-family/pilot-pairs-pfam-v1.json"
DEFAULT_HOLO_DIR = REPO_ROOT / "local-private/research/target-family/holo-pfam-v1"
DEFAULT_REPORT = (
    REPO_ROOT / "data/runtime/target-family/static-evaluation-pfam-v1-rerun-v2/"
    "target-family-static-evaluation-pfam-v1.json"
)
DEFAULT_FULL_HOLO_DIR = (
    REPO_ROOT / "local-private/research/target-family/holo-pfam-v1-full-candidates"
)
DEFAULT_FULL_REPORT = (
    REPO_ROOT / "data/runtime/target-family/static-evaluation-pfam-v1-full-candidates/"
    "target-family-static-evaluation-pfam-v1.json"
)
MAX_DISK_BYTES = 10_000_000_000
DEFAULT_MAX_CASES = 6
EVALUATION_REPORT_SCHEMA_VERSION = "biovoid-target-family-static-evaluation-v1"
RCSB_DOWNLOAD_TEMPLATE = "https://files.rcsb.org/download/{structure_id}.cif"
EVALUATOR_POLICY = AlignmentPolicy(
    policy_version="ground-truth-alignment-v1-target-family-pilot",
    ambiguous_sequence_policy="reject",
)
CHAIN_SELECTION_POLICY = "representative-common-chain-v1"


class TargetFamilyEvaluationError(RuntimeError):
    """Raised when the bounded evaluator contract cannot proceed."""


def _stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TargetFamilyEvaluationError(f"Expected a JSON object: {path}")
    return payload


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def directory_size_bytes(root: Path) -> int:
    """Return regular-file bytes below ``root`` without following symlinks."""

    if not root.exists():
        return 0
    total = 0
    for directory, _, filenames in os.walk(root, followlinks=False):
        for filename in filenames:
            path = Path(directory) / filename
            try:
                if not path.is_symlink():
                    total += path.stat().st_size
            except FileNotFoundError:
                continue
    return total


def enforce_disk_quota(root: Path, max_disk_bytes: int) -> int:
    if max_disk_bytes < 1 or max_disk_bytes > MAX_DISK_BYTES:
        raise ValueError(f"max_disk_bytes must be between 1 and {MAX_DISK_BYTES}")
    used = directory_size_bytes(root)
    if used > max_disk_bytes:
        raise TargetFamilyEvaluationError(
            f"Evaluator disk quota exceeded: {used} bytes > {max_disk_bytes} bytes"
        )
    return used


def enforce_workspace_quota(
    report_root: Path,
    holo_root: Path,
    max_disk_bytes: int,
) -> int:
    """Enforce one quota across evaluator output and ignored holo cache."""

    if max_disk_bytes < 1 or max_disk_bytes > MAX_DISK_BYTES:
        raise ValueError(f"max_disk_bytes must be between 1 and {MAX_DISK_BYTES}")
    used = directory_size_bytes(report_root) + directory_size_bytes(holo_root)
    if used > max_disk_bytes:
        raise TargetFamilyEvaluationError(
            f"Evaluator workspace quota exceeded: {used} bytes > {max_disk_bytes} bytes"
        )
    return used


def build_evaluation_skeleton(
    manifest: Mapping[str, Any],
    *,
    max_cases: int = DEFAULT_MAX_CASES,
    max_disk_bytes: int = MAX_DISK_BYTES,
    candidate_scope: str = CANDIDATE_RETENTION_TOP10,
    static_run_sha256: str | None = None,
) -> dict[str, Any]:
    """Build the evaluator report before any holo coordinate is opened."""

    validate_detector_manifest(manifest)
    try:
        candidate_scope = validate_candidate_retention(candidate_scope)
    except ValueError as exc:
        raise TargetFamilyEvaluationError(str(exc)) from exc
    if max_cases < 1 or max_cases > MAX_PILOT_CASES:
        raise ValueError(f"max_cases must be between 1 and {MAX_PILOT_CASES}")
    case_count = int(manifest["constraints"]["case_count"])
    if case_count > max_cases:
        raise TargetFamilyEvaluationError(
            f"Manifest contains {case_count} cases but evaluator cap is {max_cases}"
        )
    if max_disk_bytes < 1 or max_disk_bytes > MAX_DISK_BYTES:
        raise ValueError(f"max_disk_bytes must be between 1 and {MAX_DISK_BYTES}")
    protocol = phase6_frozen_protocol_v1()
    payload: dict[str, Any] = {
        "schema_version": EVALUATION_REPORT_SCHEMA_VERSION,
        "status": "not_started",
        "manifest_sha256": manifest["manifest_sha256"],
        "protocol_sha256": protocol.protocol_sha256,
        "detector_target_blind": True,
        "evaluator_only": True,
        "sealed_evaluation_authorized": False,
        "claim_boundary": "diagnostic_dcc_dca_only",
        "execution": {
            "workers": 1,
            "motion_enabled": False,
            "external_baselines_enabled": False,
            "max_cases": max_cases,
            "max_disk_bytes": max_disk_bytes,
            "disk_quota_enforced": True,
            "holo_coordinates_downloaded": False,
            "candidate_scope": candidate_scope,
        },
        "source": {
            "holo_provider": "RCSB files.rcsb.org",
            "holo_role": "evaluator_only",
            "raw_holo_files_ignored": True,
        },
        "alignment_policy": asdict(EVALUATOR_POLICY),
        "chain_selection_policy": CHAIN_SELECTION_POLICY,
        "candidate_scope": candidate_scope,
        "static_run_sha256": static_run_sha256,
        "interpretation_status": "pending_independent_review",
        "records": {},
        "counts": {
            "completed_ground_truth": 0,
            "alignment_unavailable": 0,
            "download_failed": 0,
            "canonical_completed": 0,
            "secondary_recovery_completed": 0,
        },
        "summary": {
            "status": "not_ready",
            "dcc_dca_computed": False,
            "scientific_superiority_claim_authorized": False,
        },
        "roadmap": {
            "current_gate": "G2-bounded-static-development-pilot",
            "status": "partial",
            "current_state": (
                "Target-family static smoke and evaluator-only DCC/DCA are bounded; "
                "results remain diagnostic."
            ),
            "next_step": (
                "Review the representative-chain policy and 4P0I secondary metrics; "
                "keep DCC/DCA diagnostic-only before any broader benchmark, NMA, or ML work."
            ),
        },
        "created_at_utc": _utc_now(),
        "updated_at_utc": _utc_now(),
    }
    payload["run_sha256"] = _stable_hash(
        {key: value for key, value in payload.items() if key != "run_sha256"}
    )
    return payload


def _seal(payload: dict[str, Any]) -> None:
    payload["updated_at_utc"] = _utc_now()
    payload["run_sha256"] = _stable_hash(
        {key: value for key, value in payload.items() if key != "run_sha256"}
    )


def _download_holo(session: requests.Session, structure_id: str, holo_dir: Path) -> dict[str, Any]:
    structure_id = structure_id.upper()
    # CLI callers commonly pass a repository-relative cache path. Resolve it
    # before serializing a repo-relative provenance path; otherwise
    # ``Path.relative_to(REPO_ROOT)`` raises after a successful download.
    holo_dir = holo_dir.resolve()
    path = holo_dir / f"{structure_id}.cif"
    if path.is_file():
        content = path.read_bytes()
        if content and b"_atom_site." in content:
            return {
                "status": "cached",
                "structure_id": structure_id,
                "path": str(path.relative_to(REPO_ROOT)).replace("\\", "/"),
                "sha256": _sha256_file(path),
                "bytes": len(content),
                "url": RCSB_DOWNLOAD_TEMPLATE.format(structure_id=structure_id),
            }
        path.unlink(missing_ok=True)
    response = session.get(
        RCSB_DOWNLOAD_TEMPLATE.format(structure_id=structure_id),
        timeout=(30, 120),
    )
    response.raise_for_status()
    content = response.content
    if not content or b"_atom_site." not in content:
        raise TargetFamilyEvaluationError(
            f"RCSB response is not an atom-containing mmCIF: {structure_id}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(content)
    temporary.replace(path)
    return {
        "status": "downloaded",
        "structure_id": structure_id,
        "path": str(path.relative_to(REPO_ROOT)).replace("\\", "/"),
        "sha256": _sha256_file(path),
        "bytes": len(content),
        "url": RCSB_DOWNLOAD_TEMPLATE.format(structure_id=structure_id),
    }


def _component_names(pair: Mapping[str, Any]) -> tuple[str, ...]:
    components = pair.get("holo_components")
    if not isinstance(components, list) or not components:
        raise TargetFamilyEvaluationError(f"No holo component declared for {pair.get('case_id')}")
    names = tuple(
        str(component.get("comp_id", "")).strip().upper()
        for component in components
        if isinstance(component, Mapping) and str(component.get("comp_id", "")).strip()
    )
    if not names:
        raise TargetFamilyEvaluationError(
            f"Holo component declaration is empty: {pair.get('case_id')}"
        )
    return names


def _ligand_selector(
    holo_path: Path,
    component_names: tuple[str, ...],
    *,
    preferred_chain_id: str | None = None,
) -> LigandSelector:
    grouped: dict[tuple[str, int, str, str], list[Any]] = defaultdict(list)
    for atom in load_structure_atoms(holo_path):
        if atom.record.upper() != "HETATM" or atom.res_name.upper() not in component_names:
            continue
        grouped[(atom.chain_id, atom.res_id, atom.ins_code.strip(), atom.res_name.upper())].append(
            atom
        )
    candidates = [
        (key, atoms)
        for key, atoms in grouped.items()
        if any(atom.element.strip().upper() not in {"H", "D"} for atom in atoms)
    ]
    if not candidates:
        raise GroundTruthAlignmentError(
            f"No HETATM residue matched declared components {component_names}"
        )
    if preferred_chain_id is not None:
        preferred = [item for item in candidates if item[0][0] == preferred_chain_id]
        if preferred:
            candidates = preferred
    ranked = sorted(
        candidates,
        key=lambda item: (
            -sum(atom.element.strip().upper() not in {"H", "D"} for atom in item[1]),
            item[0],
        ),
    )
    if len(ranked) > 1:
        top_heavy = sum(atom.element.strip().upper() not in {"H", "D"} for atom in ranked[0][1])
        second_heavy = sum(atom.element.strip().upper() not in {"H", "D"} for atom in ranked[1][1])
        if top_heavy == second_heavy:
            raise GroundTruthAlignmentError(
                f"Ligand selector is ambiguous for components {component_names}"
            )
    chain_id, residue_id, insertion_code, residue_name = ranked[0][0]
    return LigandSelector(
        residue_name=residue_name,
        chain_id=chain_id,
        residue_id=int(residue_id),
        insertion_code=insertion_code,
    )


def _chain_pairs(prepared_path: Path, holo_path: Path) -> tuple[ChainPair, ...]:
    protein_names = PROTEIN_RESIDUES | MODIFIED_AMINO_ACIDS
    apo_counts: dict[str, int] = defaultdict(int)
    holo_counts: dict[str, int] = defaultdict(int)
    for atom in load_structure_atoms(prepared_path):
        if atom.res_name.upper() in protein_names and atom.atom_name.strip().upper() == "CA":
            apo_counts[atom.chain_id] += 1
    for atom in load_structure_atoms(holo_path):
        if atom.res_name.upper() in protein_names and atom.atom_name.strip().upper() == "CA":
            holo_counts[atom.chain_id] += 1
    common_chains = [
        chain
        for chain in sorted(set(apo_counts) & set(holo_counts))
        if min(apo_counts[chain], holo_counts[chain]) >= EVALUATOR_POLICY.minimum_matched_residues
    ]
    if common_chains:
        chain = common_chains[0]
        return (ChainPair(apo_chain_id=chain, holo_chain_id=chain),)
    raise GroundTruthAlignmentError("No common apo/holo protein chain met alignment minimum")


def _detector_record(
    structure_id: str,
    primary_case: Mapping[str, Any] | None,
    recovery_case: Mapping[str, Any] | None,
    *,
    candidate_scope: str = CANDIDATE_RETENTION_TOP10,
) -> tuple[Any, str]:
    try:
        candidate_scope = validate_candidate_retention(candidate_scope)
    except ValueError as exc:
        raise TargetFamilyEvaluationError(str(exc)) from exc
    if primary_case is not None and primary_case.get("status") == "completed":
        pockets_key = (
            "all_pockets" if candidate_scope == CANDIDATE_RETENTION_FULL else "top_pockets"
        )
        pockets = primary_case.get(pockets_key)
        if not isinstance(pockets, list) or not pockets:
            raise TargetFamilyEvaluationError(
                f"Canonical case has no {candidate_scope} pockets: {structure_id}"
            )
        if candidate_scope == CANDIDATE_RETENTION_FULL:
            if primary_case.get("candidate_retention") != CANDIDATE_RETENTION_FULL:
                raise TargetFamilyEvaluationError(
                    f"Canonical case is not sealed with full candidate retention: {structure_id}"
                )
            pocket_count = primary_case.get("pocket_count")
            top_pockets = primary_case.get("top_pockets")
            if not isinstance(pocket_count, int) or len(pockets) != pocket_count:
                raise TargetFamilyEvaluationError(
                    f"Full candidate count is inconsistent: {structure_id}"
                )
            if not isinstance(top_pockets, list) or pockets[:10] != top_pockets:
                raise TargetFamilyEvaluationError(
                    f"Full candidate top10 prefix is inconsistent: {structure_id}"
                )
        return (
            adapt_biovoid_pockets(
                structure_id,
                pockets,
                provenance={
                    "source": (
                        "target-family-static-pilot-full-candidates-v1"
                        if candidate_scope == CANDIDATE_RETENTION_FULL
                        else "target-family-static-pilot-v1"
                    ),
                    "canonical_static_result": True,
                    "candidate_scope": candidate_scope,
                    "stored_candidate_count": len(pockets),
                },
            ),
            "canonical_static",
        )
    if candidate_scope == CANDIDATE_RETENTION_FULL:
        reason = "canonical full-candidate result unavailable; recovery is not eligible"
        return unavailable_record("biovoid_static", structure_id, reason), "unavailable"
    if recovery_case is not None and recovery_case.get("status") == "completed":
        pockets = recovery_case.get("top_pockets")
        if not isinstance(pockets, list) or not pockets:
            raise TargetFamilyEvaluationError(f"Recovery case has no pockets: {structure_id}")
        return (
            adapt_biovoid_pockets(
                structure_id,
                pockets,
                provenance={
                    "source": "target-family-static-pilot-recovery-v4",
                    "canonical_static_result": False,
                },
            ),
            "secondary_recovery",
        )
    reason = "canonical static result unavailable and no completed recovery result"
    if primary_case is not None and primary_case.get("status") == "resource_blocked":
        reason = "canonical SAFE_16GB resource blocked; recovery unavailable"
    return unavailable_record("biovoid_static", structure_id, reason), "unavailable"


def _case_summary(evaluation: Any) -> dict[str, Any]:
    result = asdict(evaluation)
    result["top_k_dcc_hits"] = {str(key): value for key, value in result["top_k_dcc_hits"].items()}
    result["top_k_dca_hits"] = {str(key): value for key, value in result["top_k_dca_hits"].items()}
    return result


def _evaluation_payload(record: Mapping[str, Any]) -> Mapping[str, Any] | None:
    value = record.get("case_evaluation")
    return value if isinstance(value, Mapping) else None


def _is_completed_evaluation(record: Mapping[str, Any]) -> bool:
    evaluation = _evaluation_payload(record)
    return evaluation is not None and evaluation.get("status") == "completed"


def _recall(records: list[Mapping[str, Any]], key: str, k: int) -> float:
    available = [
        evaluation
        for record in records
        if (evaluation := _evaluation_payload(record)) is not None
        and evaluation.get("status") == "completed"
    ]
    if not available:
        return 0.0
    return round(
        sum(bool(record[key].get(str(k), False)) for record in available) / len(available),
        8,
    )


def _summary(report: Mapping[str, Any]) -> dict[str, Any]:
    records = list(report.get("records", {}).values())
    completed = [record for record in records if _is_completed_evaluation(record)]
    canonical = [record for record in completed if record.get("detector_arm") == "canonical_static"]
    secondary = [
        record for record in completed if record.get("detector_arm") == "secondary_recovery"
    ]
    return {
        "status": "diagnostic_only_not_for_claim",
        "dcc_dca_computed": bool(completed),
        "ground_truth_available_case_count": len(completed),
        "canonical_case_count": len(canonical),
        "secondary_recovery_case_count": len(secondary),
        "top_k_dcc_recall_on_available_cases": {
            str(k): _recall(records, "top_k_dcc_hits", k) for k in (1, 3, 5)
        },
        "top_k_dca_recall_on_available_cases": {
            str(k): _recall(records, "top_k_dca_hits", k) for k in (1, 3, 5)
        },
        "scientific_superiority_claim_authorized": False,
        "discovery_claim_authorized": False,
    }


def validate_evaluation_report(
    report: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Fail closed if an evaluator report can be mistaken for canonical evidence."""

    validate_detector_manifest(manifest)
    if report.get("schema_version") != EVALUATION_REPORT_SCHEMA_VERSION:
        raise TargetFamilyEvaluationError("Unexpected target-family evaluator report schema")
    if report.get("manifest_sha256") != manifest.get("manifest_sha256"):
        raise TargetFamilyEvaluationError("Evaluator report manifest hash mismatch")
    if report.get("protocol_sha256") != phase6_frozen_protocol_v1().protocol_sha256:
        raise TargetFamilyEvaluationError("Evaluator report protocol hash mismatch")
    if report.get("detector_target_blind") is not True:
        raise TargetFamilyEvaluationError("Evaluator report is not detector-target-blind")
    if report.get("evaluator_only") is not True:
        raise TargetFamilyEvaluationError("Evaluator report is not evaluator-only")
    if report.get("sealed_evaluation_authorized") is not False:
        raise TargetFamilyEvaluationError("sealed evaluation authorization must remain false")
    if report.get("claim_boundary") != "diagnostic_dcc_dca_only":
        raise TargetFamilyEvaluationError("Evaluator report claim boundary is unsafe")
    if report.get("chain_selection_policy") != CHAIN_SELECTION_POLICY:
        raise TargetFamilyEvaluationError("Evaluator chain-selection policy is not locked")
    try:
        candidate_scope = validate_candidate_retention(
            report.get("candidate_scope", CANDIDATE_RETENTION_TOP10)
        )
    except ValueError as exc:
        raise TargetFamilyEvaluationError(str(exc)) from exc

    execution = report.get("execution")
    if not isinstance(execution, Mapping):
        raise TargetFamilyEvaluationError("Evaluator report is missing execution controls")
    if execution.get("workers") != 1:
        raise TargetFamilyEvaluationError("Evaluator report violates single-worker boundary")
    if execution.get("motion_enabled") is not False:
        raise TargetFamilyEvaluationError("Evaluator report unexpectedly enables motion")
    if execution.get("external_baselines_enabled") is not False:
        raise TargetFamilyEvaluationError(
            "Evaluator report unexpectedly enables external baselines"
        )
    if execution.get("candidate_scope", CANDIDATE_RETENTION_TOP10) != candidate_scope:
        raise TargetFamilyEvaluationError("Evaluator candidate scope metadata drifted")
    if (
        candidate_scope == CANDIDATE_RETENTION_FULL
        and str(report.get("status", "")) != "not_started"
        and not str(report.get("static_run_sha256", "")).strip()
    ):
        raise TargetFamilyEvaluationError("Full evaluator report is missing static run hash")
    max_disk_bytes = execution.get("max_disk_bytes")
    if not isinstance(max_disk_bytes, int) or max_disk_bytes < 1 or max_disk_bytes > MAX_DISK_BYTES:
        raise TargetFamilyEvaluationError("Evaluator report has no bounded disk quota")
    final_disk_bytes = execution.get("final_disk_bytes")
    if final_disk_bytes is not None and (
        not isinstance(final_disk_bytes, int) or final_disk_bytes > max_disk_bytes
    ):
        raise TargetFamilyEvaluationError("Evaluator report exceeds its disk quota")

    roadmap = report.get("roadmap")
    if not isinstance(roadmap, Mapping):
        raise TargetFamilyEvaluationError("Evaluator report is missing roadmap state")
    if roadmap.get("current_gate") != "G2-bounded-static-development-pilot":
        raise TargetFamilyEvaluationError("Evaluator report roadmap gate drifted")
    if not str(roadmap.get("next_step", "")).strip():
        raise TargetFamilyEvaluationError("Evaluator report roadmap next step is empty")

    expected_case_ids = {str(case["case_id"]) for case in manifest["cases"]}
    records = report.get("records")
    if not isinstance(records, Mapping):
        raise TargetFamilyEvaluationError("Evaluator report records must be an object")
    if set(str(key) for key in records) - expected_case_ids:
        raise TargetFamilyEvaluationError("Evaluator report contains an unknown case")
    counts = report.get("counts")
    if not isinstance(counts, Mapping):
        raise TargetFamilyEvaluationError("Evaluator report is missing counts")
    completed_ground_truth = sum(
        record.get("status") == "completed_ground_truth"
        for record in records.values()
        if isinstance(record, Mapping)
    )
    alignment_unavailable = sum(
        record.get("status") == "alignment_unavailable"
        for record in records.values()
        if isinstance(record, Mapping)
    )
    download_failed = sum(
        record.get("status") == "download_failed"
        for record in records.values()
        if isinstance(record, Mapping)
    )
    canonical_completed = sum(
        record.get("detector_arm") == "canonical_static"
        and record.get("status") == "completed_ground_truth"
        for record in records.values()
        if isinstance(record, Mapping)
    )
    secondary_completed = sum(
        record.get("detector_arm") == "secondary_recovery"
        and record.get("status") == "completed_ground_truth"
        for record in records.values()
        if isinstance(record, Mapping)
    )
    expected_counts = {
        "completed_ground_truth": completed_ground_truth,
        "alignment_unavailable": alignment_unavailable,
        "download_failed": download_failed,
        "canonical_completed": canonical_completed,
        "secondary_recovery_completed": secondary_completed,
    }
    if any(counts.get(key) != value for key, value in expected_counts.items()):
        raise TargetFamilyEvaluationError("Evaluator report counts do not match records")

    for case_id, record in records.items():
        if not isinstance(record, Mapping):
            raise TargetFamilyEvaluationError(f"Evaluator case is not an object: {case_id}")
        arm = record.get("detector_arm")
        if arm not in {"unavailable", "canonical_static", "secondary_recovery"}:
            raise TargetFamilyEvaluationError(f"Evaluator case has unsafe detector arm: {case_id}")
        evaluation = record.get("case_evaluation")
        if isinstance(evaluation, Mapping) and evaluation.get("status") == "completed":
            if arm not in {"canonical_static", "secondary_recovery"}:
                raise TargetFamilyEvaluationError(
                    f"Completed evaluation has no valid detector arm: {case_id}"
                )
            if evaluation.get("detector") != "biovoid_static":
                raise TargetFamilyEvaluationError(
                    f"Unexpected detector in evaluator result: {case_id}"
                )

    status = str(report.get("status", ""))
    if status == "not_started":
        return {"status": "diagnostic_contract_valid", "claim_authorized": False}
    summary = report.get("summary")
    if not isinstance(summary, Mapping):
        raise TargetFamilyEvaluationError("Completed evaluator report is missing summary")
    if summary.get("status") != "diagnostic_only_not_for_claim":
        raise TargetFamilyEvaluationError("Evaluator summary is not diagnostic-only")
    if summary.get("ground_truth_available_case_count") != completed_ground_truth:
        raise TargetFamilyEvaluationError("Evaluator summary denominator drifted")
    if summary.get("canonical_case_count") != canonical_completed:
        raise TargetFamilyEvaluationError("Evaluator canonical count drifted")
    if summary.get("secondary_recovery_case_count") != secondary_completed:
        raise TargetFamilyEvaluationError("Evaluator secondary count drifted")
    if summary.get("scientific_superiority_claim_authorized") is not False:
        raise TargetFamilyEvaluationError("Scientific superiority claim is unexpectedly enabled")
    if summary.get("discovery_claim_authorized") is not False:
        raise TargetFamilyEvaluationError("Discovery claim is unexpectedly enabled")
    return {
        "status": "diagnostic_contract_valid",
        "claim_authorized": False,
        "canonical_cases": canonical_completed,
        "secondary_cases": secondary_completed,
        "ground_truth_cases": completed_ground_truth,
    }


def run_target_family_evaluation(
    *,
    manifest_path: Path = DEFAULT_MANIFEST,
    static_run_path: Path = DEFAULT_STATIC_RUN,
    recovery_run_path: Path = DEFAULT_RECOVERY_RUN,
    pairs_path: Path = DEFAULT_PAIRS,
    holo_dir: Path = DEFAULT_HOLO_DIR,
    report_path: Path = DEFAULT_REPORT,
    max_cases: int = DEFAULT_MAX_CASES,
    max_disk_bytes: int = MAX_DISK_BYTES,
    user_approved: bool = False,
    candidate_scope: str = CANDIDATE_RETENTION_TOP10,
) -> dict[str, Any]:
    if not user_approved:
        raise TargetFamilyEvaluationError(
            "Opening evaluator-only holo coordinates requires --approve-evaluator"
        )
    try:
        candidate_scope = validate_candidate_retention(candidate_scope)
    except ValueError as exc:
        raise TargetFamilyEvaluationError(str(exc)) from exc
    manifest = _read_json(manifest_path.resolve())
    validate_detector_manifest(manifest)
    static_run = _read_json(static_run_path.resolve())
    recovery_run = (
        {}
        if candidate_scope == CANDIDATE_RETENTION_FULL
        else (_read_json(recovery_run_path.resolve()) if recovery_run_path.is_file() else {})
    )
    pairs_payload = _read_json(pairs_path.resolve())
    pairs = pairs_payload.get("pairs")
    if not isinstance(pairs, list):
        raise TargetFamilyEvaluationError("Private pilot pair inventory is invalid")
    if static_run.get("manifest_sha256") != manifest.get("manifest_sha256"):
        raise TargetFamilyEvaluationError("Static run manifest hash mismatch")
    static_retention = (
        static_run.get("execution", {}).get("candidate_retention")
        if isinstance(static_run.get("execution"), Mapping)
        else None
    )
    if candidate_scope == CANDIDATE_RETENTION_FULL and static_retention != CANDIDATE_RETENTION_FULL:
        raise TargetFamilyEvaluationError(
            "Full evaluator scope requires a static run sealed with full candidate retention"
        )
    if recovery_run and recovery_run.get("manifest_sha256") != manifest.get("manifest_sha256"):
        raise TargetFamilyEvaluationError("Recovery run manifest hash mismatch")
    if len(manifest["cases"]) > max_cases:
        raise TargetFamilyEvaluationError("Target-family evaluator case cap exceeded")

    report = build_evaluation_skeleton(
        manifest,
        max_cases=max_cases,
        max_disk_bytes=max_disk_bytes,
        candidate_scope=candidate_scope,
        static_run_sha256=_sha256_file(static_run_path.resolve()),
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report["status"] = "running"
    _seal(report)
    _write_json_atomic(report_path, report)
    enforce_workspace_quota(report_path.parent, holo_dir, max_disk_bytes)

    pair_by_case = {
        str(pair.get("case_id")): pair
        for pair in pairs
        if isinstance(pair, Mapping) and pair.get("case_id")
    }
    static_cases = static_run.get("cases", {})
    recovery_result = recovery_run.get("result", {}) if isinstance(recovery_run, Mapping) else {}
    recovery_case_by_structure = {}
    if recovery_result.get("structure_id"):
        recovery_case_by_structure[str(recovery_result["structure_id"]).upper()] = recovery_result

    session = requests.Session()
    session.headers.update({"User-Agent": "BioVoid/0.1 target-family evaluator pilot"})
    for case in manifest["cases"]:
        case_id = str(case["case_id"])
        structure_id = str(case["structure_id"]).upper()
        pair = pair_by_case.get(case_id)
        if pair is None:
            raise TargetFamilyEvaluationError(f"No private evaluator pair for case {case_id}")
        started = time.perf_counter()
        record: dict[str, Any] = {
            "case_id": case_id,
            "structure_id": structure_id,
            "status": "download_failed",
            "detector_arm": "unavailable",
            "ground_truth": None,
            "case_evaluation": None,
        }
        try:
            primary_case = static_cases.get(case_id)
            recovery_case = recovery_case_by_structure.get(structure_id)
            detector_record, detector_arm = _detector_record(
                structure_id,
                primary_case,
                recovery_case,
                candidate_scope=candidate_scope,
            )
            record["detector_arm"] = detector_arm
            record["detector_status"] = detector_record.status
            prepared_path_text = None
            if isinstance(primary_case, Mapping):
                prepared_path_text = primary_case.get("prepared_path")
            if not prepared_path_text and isinstance(recovery_case, Mapping):
                prepared_path_text = recovery_case.get("prepared_path")
            if not prepared_path_text:
                prepared_path_text = (
                    f"data/runtime/target-family/static-pilot-pfam-v1-rerun-v2/cases/{structure_id}/preparation/"
                    "prepared_detector.pdb"
                )
            prepared_path = (REPO_ROOT / str(prepared_path_text)).resolve()
            if not prepared_path.is_file():
                raise TargetFamilyEvaluationError(f"Prepared apo file missing: {prepared_path}")
            holo_id = str(pair["holo_pdb_id"]).upper()
            holo_source = _download_holo(session, holo_id, holo_dir)
            enforce_workspace_quota(report_path.parent, holo_dir, max_disk_bytes)
            holo_path = (REPO_ROOT / str(holo_source["path"])).resolve()
            chain_pairs = _chain_pairs(prepared_path, holo_path)
            selector = _ligand_selector(
                holo_path,
                _component_names(pair),
                preferred_chain_id=chain_pairs[0].holo_chain_id,
            )
            alignment = build_aligned_ground_truth_from_files(
                case_id=case_id,
                structure_id=structure_id,
                prepared_apo_path=prepared_path,
                holo_path=holo_path,
                ligand=selector,
                chain_pairs=chain_pairs,
                provenance_label="target-family-rcsb-representative-holo-evaluator-v1",
                policy=EVALUATOR_POLICY,
            )
            evaluation = evaluate_case(
                detector_record, alignment.ground_truth, phase6_frozen_protocol_v1()
            )
            record.update(
                {
                    "status": "completed_ground_truth",
                    "detector_arm": detector_arm,
                    "holo_source": holo_source,
                    "ligand_selector": asdict(selector),
                    "chain_pairs": [asdict(pair_value) for pair_value in chain_pairs],
                    "chain_selection_policy": CHAIN_SELECTION_POLICY,
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
                }
            )
            report["execution"]["holo_coordinates_downloaded"] = True
            report["counts"]["completed_ground_truth"] += 1
            if detector_arm == "canonical_static":
                report["counts"]["canonical_completed"] += 1
            elif detector_arm == "secondary_recovery":
                report["counts"]["secondary_recovery_completed"] += 1
        except GroundTruthAlignmentError as exc:
            record.update(
                {"status": "alignment_unavailable", "error": f"{type(exc).__name__}: {exc}"}
            )
            report["counts"]["alignment_unavailable"] += 1
        except (
            requests.RequestException,
            OSError,
            ValueError,
            KeyError,
            TargetFamilyEvaluationError,
        ) as exc:
            record.update({"status": "download_failed", "error": f"{type(exc).__name__}: {exc}"})
            report["counts"]["download_failed"] += 1
        record["runtime_seconds"] = round(time.perf_counter() - started, 6)
        report["records"][case_id] = record
        report["summary"] = _summary(report)
        report["updated_at_utc"] = _utc_now()
        _seal(report)
        _write_json_atomic(report_path, report)
        enforce_workspace_quota(report_path.parent, holo_dir, max_disk_bytes)

    report["summary"] = _summary(report)
    report["roadmap"]["current_state"] = (
        f"G2 static smoke: {report['counts']['canonical_completed']} canonical case(s), "
        f"{report['counts']['secondary_recovery_completed']} secondary recovery case(s); "
        f"DCC/DCA ground truth available for {report['counts']['completed_ground_truth']} case(s)."
    )
    report["status"] = "completed_diagnostic_only"
    report["updated_at_utc"] = _utc_now()
    report["execution"]["final_disk_bytes"] = enforce_workspace_quota(
        report_path.parent,
        holo_dir,
        max_disk_bytes,
    )
    _seal(report)
    _write_json_atomic(report_path, report)
    enforce_workspace_quota(report_path.parent, holo_dir, max_disk_bytes)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--static-run", type=Path, default=DEFAULT_STATIC_RUN)
    parser.add_argument("--recovery-run", type=Path, default=DEFAULT_RECOVERY_RUN)
    parser.add_argument("--pairs", type=Path, default=DEFAULT_PAIRS)
    parser.add_argument("--holo-dir", type=Path, default=DEFAULT_HOLO_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--max-cases", type=int, default=DEFAULT_MAX_CASES)
    parser.add_argument("--max-disk-bytes", type=int, default=MAX_DISK_BYTES)
    parser.add_argument(
        "--candidate-scope",
        choices=(CANDIDATE_RETENTION_TOP10, CANDIDATE_RETENTION_FULL),
        default=CANDIDATE_RETENTION_TOP10,
        help="Evaluate the stored top ten, or an explicitly sealed full-candidate run.",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate an existing evaluator report without network or holo access.",
    )
    parser.add_argument(
        "--approve-evaluator",
        action="store_true",
        help="Explicitly authorize evaluator-only holo access and DCC/DCA calculation.",
    )
    args = parser.parse_args()
    if args.validate_only:
        manifest = _read_json(args.manifest.resolve())
        report = _read_json(args.report.resolve())
        result = validate_evaluation_report(report, manifest)
        print(f"status={result['status']}")
        print(f"claim_authorized={result['claim_authorized']}")
        return 0
    report = run_target_family_evaluation(
        manifest_path=args.manifest,
        static_run_path=args.static_run,
        recovery_run_path=args.recovery_run,
        pairs_path=args.pairs,
        holo_dir=args.holo_dir,
        report_path=args.report,
        max_cases=args.max_cases,
        max_disk_bytes=args.max_disk_bytes,
        user_approved=args.approve_evaluator,
        candidate_scope=args.candidate_scope,
    )
    print(f"status={report['status']}")
    print(f"completed_ground_truth={report['counts']['completed_ground_truth']}")
    print(f"alignment_unavailable={report['counts']['alignment_unavailable']}")
    print(f"download_failed={report['counts']['download_failed']}")
    print(f"disk_bytes={report['execution']['final_disk_bytes']}")
    print(f"run_sha256={report['run_sha256']}")
    print(f"summary={json.dumps(report['summary'], sort_keys=True)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except TargetFamilyEvaluationError as exc:
        print(f"target-family evaluator error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
