"""Audit a new ranking-study cohort without materializing structures.

The command joins a bounded metadata inventory, its review-only sequence
clusters, and prior-study manifests.  It creates a deterministic, date-aware
development/validation/temporal allocation before any new detector or
evaluator result is available.  Coordinates, holo labels, benchmarks, NMA,
and ML are deliberately outside this command's boundary.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


FEASIBILITY_SCHEMA_VERSION = "biovoid-ranking-cohort-feasibility-v1"
INVENTORY_SCHEMA_VERSION = "biovoid-target-family-metadata-inventory-v1"
CLUSTER_SCHEMA_VERSION = "biovoid-target-family-sequence-clusters-v1"
DEFAULT_INVENTORY = (
    REPO_ROOT / "local-private/research/target-family/metadata-inventory-pfam-v1.json"
)
DEFAULT_CLUSTERS = (
    REPO_ROOT / "data/runtime/target-family/sequence-clusters-pfam-v1/"
    "target-family-sequence-clusters-pfam-v1.json"
)
DEFAULT_PRIOR_PAIRS = REPO_ROOT / "local-private/research/target-family/pilot-pairs-pfam-v1.json"
DEFAULT_PRIOR_COHORT = REPO_ROOT / "local-private/research/target-family/cohort-pfam-v1.json"
DEFAULT_RI3_MANIFEST = REPO_ROOT / "data/runtime/ri3/cryptobench-static-pilot-manifest-v1.json"
DEFAULT_OUTPUT = (
    REPO_ROOT / "local-private/research/ranking-cohort-feasibility-v1/"
    "ranking-cohort-feasibility-v1.json"
)
DEFAULT_MARKDOWN = (
    REPO_ROOT / "local-private/research/ranking-cohort-feasibility-v1/"
    "ranking-cohort-feasibility-v1.md"
)
DEFAULT_VALIDATION_CUTOFF = "2014-01-01"
DEFAULT_TEMPORAL_CUTOFF = "2018-01-01"
TARGET_COUNTS = {"development": 6, "validation": 2, "temporal": 2}
ALLOWED_LABEL_SOURCES = {"holo_ligand_contact_v1", "independent_annotation_v1"}
RESOURCE_STATUSES = {
    "likely_within_static_atom_cap",
    "likely_above_static_atom_cap",
    "review_required",
}
_PDB_ID_RE = re.compile(r"^[A-Z0-9]{4}$")


class RankingCohortFeasibilityError(RuntimeError):
    """Raised when a metadata input violates the feasibility contract."""


def _stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RankingCohortFeasibilityError(f"{field} must be a non-empty string")
    return value.strip()


def _family_id(payload: Mapping[str, Any]) -> str:
    value = payload.get("family_id")
    if not isinstance(value, str) or not value.strip():
        source = payload.get("source")
        value = source.get("family_id") if isinstance(source, Mapping) else None
    return _required_text(value, "family_id").upper()


def _pdb_id(value: Any, field: str) -> str:
    normalized = _required_text(value, field).upper()
    if _PDB_ID_RE.fullmatch(normalized) is None:
        raise RankingCohortFeasibilityError(f"{field} must be a four-character PDB ID")
    return normalized


def _records(payload: Mapping[str, Any], field: str) -> list[Mapping[str, Any]]:
    raw = payload.get(field)
    if not isinstance(raw, list):
        raise RankingCohortFeasibilityError(f"{field} must be a list")
    if any(not isinstance(item, Mapping) for item in raw):
        raise RankingCohortFeasibilityError(f"{field} entries must be objects")
    return [item for item in raw if isinstance(item, Mapping)]


def _uniprot_group(record: Mapping[str, Any], field: str = "uniprot_ids") -> str:
    raw = record.get(field)
    if not isinstance(raw, list) or not raw:
        raise RankingCohortFeasibilityError(f"{field} must be a non-empty list")
    values = sorted({_required_text(value, f"{field}[]").upper() for value in raw})
    return "+".join(values)


def _parse_date(value: Any, field: str) -> date | None:
    if value is None or value == "":
        return None
    text = _required_text(value, field)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError as exc:
        raise RankingCohortFeasibilityError(f"{field} must be an ISO/RFC3339 date") from exc


def _strict_inventory_records(payload: Mapping[str, Any]) -> tuple[str, list[Mapping[str, Any]]]:
    if payload.get("schema_version") != INVENTORY_SCHEMA_VERSION:
        raise RankingCohortFeasibilityError("metadata inventory schema is unsupported")
    family_id = _family_id(payload)
    records = _records(payload, "records")
    if not records:
        raise RankingCohortFeasibilityError("metadata inventory has no records")
    seen: set[str] = set()
    for record in records:
        pdb_id = _pdb_id(record.get("pdb_id"), "metadata.pdb_id")
        if pdb_id in seen:
            raise RankingCohortFeasibilityError("metadata inventory contains duplicate PDB IDs")
        seen.add(pdb_id)
        if _required_text(record.get("family_id"), "metadata.family_id").upper() != family_id:
            raise RankingCohortFeasibilityError("metadata inventory family drifted")
        _uniprot_group(record)
        _parse_date(record.get("release_date"), "metadata.release_date")
        components = record.get("likely_ligand_components")
        if not isinstance(components, list):
            raise RankingCohortFeasibilityError("metadata ligand components must be a list")

    def passes(record: Mapping[str, Any]) -> bool:
        method = str(record.get("experimental_method", "")).casefold()
        try:
            length = int(str(record.get("sequence_length")))
            resolution = float(str(record.get("resolution_angstrom")))
        except (TypeError, ValueError):
            return False
        return "x-ray" in method and 180 <= length <= 350 and resolution <= 2.8

    return family_id, [record for record in records if passes(record)]


def _cluster_index(payload: Mapping[str, Any], family_id: str) -> dict[str, str]:
    if payload.get("schema_version") != CLUSTER_SCHEMA_VERSION:
        raise RankingCohortFeasibilityError("sequence-cluster schema is unsupported")
    if payload.get("status") != "sequence_materialized_review_required":
        raise RankingCohortFeasibilityError("sequence-cluster report is not review-required")
    if _family_id(payload) != family_id:
        raise RankingCohortFeasibilityError("sequence-cluster family drifted")
    indexed: dict[str, str] = {}
    for record in _records(payload, "records"):
        pdb_id = _pdb_id(record.get("pdb_id"), "sequence_cluster.pdb_id")
        cluster_id = _required_text(record.get("sequence_cluster_id"), "sequence_cluster_id")
        if pdb_id in indexed:
            raise RankingCohortFeasibilityError(
                "sequence-cluster report contains duplicate PDB IDs"
            )
        indexed[pdb_id] = cluster_id
    return indexed


def _select_pairs(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for record in records:
        grouped.setdefault(_uniprot_group(record), []).append(record)
    pairs: list[dict[str, Any]] = []
    for group_id in sorted(grouped):
        group = grouped[group_id]
        apo = [record for record in group if not record["likely_ligand_components"]]
        holo = [record for record in group if record["likely_ligand_components"]]
        if not apo or not holo:
            continue
        selected_apo = min(
            apo,
            key=lambda item: (
                float(item["resolution_angstrom"]),
                str(item["pdb_id"]).upper(),
            ),
        )
        selected_holo = min(
            holo,
            key=lambda item: (
                float(item["resolution_angstrom"]),
                -len(item["likely_ligand_components"]),
                str(item["pdb_id"]).upper(),
            ),
        )
        pairs.append(
            {
                "apo_structure_id": str(selected_apo["pdb_id"]).upper(),
                "holo_structure_id": str(selected_holo["pdb_id"]).upper(),
                "uniprot_group_id": group_id,
                "apo_release_date": selected_apo.get("release_date"),
                "holo_release_date": selected_holo.get("release_date"),
                "apo_resolution_angstrom": float(selected_apo["resolution_angstrom"]),
                "holo_resolution_angstrom": float(selected_holo["resolution_angstrom"]),
                "apo_candidate_count": len(apo),
                "holo_candidate_count": len(holo),
                "apo_record": selected_apo,
            }
        )
    return pairs


def _prior_sets(
    pair_payload: Mapping[str, Any], cohort_payload: Mapping[str, Any]
) -> tuple[set[tuple[str, str]], set[str], set[str], set[str]]:
    pair_keys: set[tuple[str, str]] = set()
    prior_apo: set[str] = set()
    prior_groups: set[str] = set()
    prior_clusters: set[str] = set()
    for pair in (
        _records(pair_payload, "pairs") if isinstance(pair_payload.get("pairs"), list) else []
    ):
        apo = _pdb_id(pair.get("apo_pdb_id"), "prior_pair.apo_pdb_id")
        holo = _pdb_id(pair.get("holo_pdb_id"), "prior_pair.holo_pdb_id")
        pair_keys.add((apo, holo))
        prior_apo.add(apo)
        if pair.get("uniprot_group"):
            prior_groups.add(str(pair["uniprot_group"]).strip().upper())
    cases = cohort_payload.get("cases", [])
    if isinstance(cases, list):
        for case in cases:
            if not isinstance(case, Mapping):
                continue
            if case.get("apo_structure_id"):
                prior_apo.add(_pdb_id(case["apo_structure_id"], "prior_case.apo_structure_id"))
            if case.get("holo_structure_id") and case.get("apo_structure_id"):
                pair_keys.add(
                    (
                        _pdb_id(case["apo_structure_id"], "prior_case.apo_structure_id"),
                        _pdb_id(case["holo_structure_id"], "prior_case.holo_structure_id"),
                    )
                )
            if case.get("uniprot_group_id"):
                prior_groups.add(str(case["uniprot_group_id"]).strip().upper())
            if case.get("sequence_cluster_id"):
                prior_clusters.add(str(case["sequence_cluster_id"]).strip())
    return pair_keys, prior_apo, prior_groups, prior_clusters


def _ri3_sets(payload: Mapping[str, Any]) -> tuple[set[str], set[str]]:
    structure_ids: set[str] = set()
    uniprot_ids: set[str] = set()
    for field in ("structures", "cases"):
        raw = payload.get(field)
        if not isinstance(raw, list):
            continue
        for item in raw:
            if not isinstance(item, Mapping):
                continue
            for key in ("structure_id", "apo_structure_id", "holo_structure_id"):
                if item.get(key):
                    structure_ids.add(str(item[key]).strip().upper())
            for key in ("uniprot_id", "family_id"):
                if item.get(key):
                    uniprot_ids.add(str(item[key]).strip().upper())
    return structure_ids, uniprot_ids


def _label_index(payload: Mapping[str, Any] | None) -> dict[tuple[str, str], dict[str, str]]:
    if payload is None:
        return {}
    labels: dict[tuple[str, str], dict[str, str]] = {}
    raw = payload.get("cases")
    if not isinstance(raw, list):
        return labels
    for case in raw:
        if not isinstance(case, Mapping) or not case.get("apo_structure_id"):
            continue
        apo = _pdb_id(case["apo_structure_id"], "label.apo_structure_id")
        holo = _pdb_id(case.get("holo_structure_id"), "label.holo_structure_id")
        source = str(case.get("label_source") or "").strip()
        quality = str(case.get("label_quality") or "").strip().casefold()
        nested = case.get("contact_label")
        if isinstance(nested, Mapping):
            source = source or str(nested.get("label_source") or "").strip()
            quality = quality or str(nested.get("quality") or "").strip().casefold()
        labels[(apo, holo)] = {
            "source": source,
            "quality": quality,
            "status": (
                "independent_exact"
                if source in ALLOWED_LABEL_SOURCES and quality == "exact"
                else "unavailable"
            ),
        }
    return labels


def _resource_status(record: Mapping[str, Any]) -> str:
    proxy = record.get("resource_proxy")
    if not isinstance(proxy, Mapping):
        return "review_required"
    status = str(proxy.get("status") or "review_required")
    return status if status in RESOURCE_STATUSES else "review_required"


def _case_id(family_id: str, pair: Mapping[str, Any], cluster_id: str | None) -> str:
    digest = _stable_hash(
        {
            "family_id": family_id,
            "apo_structure_id": pair["apo_structure_id"],
            "holo_structure_id": pair["holo_structure_id"],
            "uniprot_group_id": pair["uniprot_group_id"],
            "sequence_cluster_id": cluster_id,
        }
    )[:16]
    return f"{family_id}:{pair['apo_structure_id']}:{digest}"


def _candidate_rows(
    family_id: str,
    pairs: Sequence[Mapping[str, Any]],
    clusters: Mapping[str, str],
    prior_pair_payload: Mapping[str, Any],
    prior_cohort_payload: Mapping[str, Any],
    ri3_manifest_payload: Mapping[str, Any],
    independent_label_payload: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    prior_keys, prior_apo, prior_groups, prior_clusters = _prior_sets(
        prior_pair_payload, prior_cohort_payload
    )
    ri3_structures, ri3_uniprots = _ri3_sets(ri3_manifest_payload)
    labels = _label_index(independent_label_payload)
    rows: list[dict[str, Any]] = []
    for pair in pairs:
        apo = str(pair["apo_structure_id"])
        holo = str(pair["holo_structure_id"])
        cluster_apo = clusters.get(apo)
        cluster_holo = clusters.get(holo)
        if cluster_apo is None or cluster_holo is None:
            cluster_status = "missing"
            cluster_id = cluster_apo or cluster_holo
        elif cluster_apo != cluster_holo:
            cluster_status = "pair_cluster_mismatch"
            cluster_id = cluster_apo
        else:
            cluster_status = "ok"
            cluster_id = cluster_apo

        prior_pair_overlap = (
            (apo, holo) in prior_keys
            or apo in prior_apo
            or str(pair["uniprot_group_id"]).upper() in prior_groups
            or (cluster_id is not None and cluster_id in prior_clusters)
        )
        ri3_overlap = "none"
        if apo in ri3_structures or holo in ri3_structures:
            ri3_overlap = "structure_id"
        elif str(pair["uniprot_group_id"]).upper() in ri3_uniprots:
            ri3_overlap = "uniprot_id"

        label = labels.get((apo, holo))
        if label is not None:
            label_quality = label["status"]
        elif prior_pair_overlap:
            label_quality = "prior_diagnostic_not_new_eligible"
        else:
            label_quality = "not_materialized"

        resource_status = _resource_status(pair["apo_record"])
        case_id = _case_id(family_id, pair, cluster_id)
        reasons: list[str] = []
        if prior_pair_overlap:
            reasons.append("prior_pf00497_diagnostic_overlap")
        if ri3_overlap != "none":
            reasons.append(f"ri3_overlap:{ri3_overlap}")
        if cluster_status != "ok":
            reasons.append(f"sequence_cluster:{cluster_status}")
        if label_quality != "independent_exact":
            reasons.append(f"label:{label_quality}")
        if resource_status != "likely_within_static_atom_cap":
            reasons.append(f"resource:{resource_status}")
        rows.append(
            {
                "case_id": case_id,
                "apo_structure_id": apo,
                "holo_structure_id": holo,
                "uniprot_group_id": pair["uniprot_group_id"],
                "sequence_cluster_id": cluster_id,
                "sequence_cluster_status": cluster_status,
                "apo_release_date": pair.get("apo_release_date"),
                "holo_release_date": pair.get("holo_release_date"),
                "label_quality": label_quality,
                "resource_proxy_status": resource_status,
                "prior_ri3_overlap": ri3_overlap,
                "prior_pf00497_diagnostic_overlap": prior_pair_overlap,
                "metadata_eligible_for_new_selection": not prior_pair_overlap
                and ri3_overlap == "none"
                and cluster_status == "ok",
                "excluded_reasons": reasons,
            }
        )
    return sorted(rows, key=lambda row: str(row["case_id"]))


def _metadata_selection_pool(rows: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [
        row
        for row in rows
        if row["metadata_eligible_for_new_selection"]
        and row["resource_proxy_status"] == "likely_within_static_atom_cap"
    ]


def _allocate_splits(
    rows: Sequence[Mapping[str, Any]],
    *,
    catalog_id: str,
    validation_cutoff: date,
    temporal_cutoff: date,
) -> dict[str, Any]:
    if validation_cutoff >= temporal_cutoff:
        raise ValueError("validation cutoff must precede temporal cutoff")
    pool = sorted(
        _metadata_selection_pool(rows),
        key=lambda row: _stable_hash(
            {
                "catalog_id": catalog_id,
                "case_id": row["case_id"],
                "uniprot_group_id": row["uniprot_group_id"],
                "sequence_cluster_id": row["sequence_cluster_id"],
            }
        ),
    )
    buckets: dict[str, list[Mapping[str, Any]]] = {
        "development": [],
        "validation": [],
        "temporal": [],
        "overflow": [],
    }
    for row in pool:
        release = _parse_date(row.get("apo_release_date"), "candidate.apo_release_date")
        if release is None:
            buckets["overflow"].append(row)
        elif release < validation_cutoff:
            buckets["development"].append(row)
        elif release < temporal_cutoff:
            buckets["validation"].append(row)
        else:
            buckets["temporal"].append(row)

    assignments: list[dict[str, str]] = []
    selected_counts: dict[str, int] = {}
    for split in ("development", "validation", "temporal"):
        quota = TARGET_COUNTS[split]
        selected = buckets[split][:quota]
        selected_counts[split] = len(selected)
        assignments.extend({"case_id": str(row["case_id"]), "split": split} for row in selected)
        buckets["overflow"].extend(buckets[split][quota:])
    selected_case_ids = {item["case_id"] for item in assignments}
    for row in rows:
        if row["case_id"] in selected_case_ids:
            continue
        if row in pool:
            # A candidate in the eligible pool that was not selected is a
            # deterministic overflow; excluded rows remain visible below.
            assignments.append({"case_id": str(row["case_id"]), "split": "overflow"})
    selected_counts["overflow"] = sum(1 for item in assignments if item["split"] == "overflow")
    allocation = {
        "status": "sealed_metadata_only",
        "policy_id": "sequence_cluster_date_window_hash_v1",
        "catalog_id": catalog_id,
        "validation_cutoff": validation_cutoff.isoformat(),
        "temporal_cutoff": temporal_cutoff.isoformat(),
        "target_counts": TARGET_COUNTS,
        "counts": selected_counts,
        "assignments": sorted(assignments, key=lambda item: (item["split"], item["case_id"])),
    }
    allocation["allocation_sha256"] = _stable_hash(
        {key: value for key, value in allocation.items() if key != "allocation_sha256"}
    )
    return allocation


def assess_ranking_cohort_feasibility(
    inventory_payload: Mapping[str, Any],
    sequence_cluster_payload: Mapping[str, Any],
    *,
    prior_pair_payload: Mapping[str, Any],
    prior_cohort_payload: Mapping[str, Any],
    ri3_manifest_payload: Mapping[str, Any],
    independent_label_payload: Mapping[str, Any] | None = None,
    catalog_id: str = "pfam-pf00497-metadata-inventory-v1",
    validation_cutoff: str = DEFAULT_VALIDATION_CUTOFF,
    temporal_cutoff: str = DEFAULT_TEMPORAL_CUTOFF,
) -> dict[str, Any]:
    family_id, records = _strict_inventory_records(inventory_payload)
    clusters = _cluster_index(sequence_cluster_payload, family_id)
    validation_date = _parse_date(validation_cutoff, "validation_cutoff")
    temporal_date = _parse_date(temporal_cutoff, "temporal_cutoff")
    if validation_date is None or temporal_date is None:
        raise RankingCohortFeasibilityError("split cutoffs are required")
    pairs = _select_pairs(records)
    rows = _candidate_rows(
        family_id,
        pairs,
        clusters,
        prior_pair_payload,
        prior_cohort_payload,
        ri3_manifest_payload,
        independent_label_payload,
    )
    allocation = _allocate_splits(
        rows,
        catalog_id=catalog_id,
        validation_cutoff=validation_date,
        temporal_cutoff=temporal_date,
    )
    counts = allocation["counts"]
    new_metadata_rows = [row for row in rows if row["metadata_eligible_for_new_selection"]]
    new_labeled_rows = [
        row for row in new_metadata_rows if row["label_quality"] == "independent_exact"
    ]
    resource_counts = {
        status: sum(row["resource_proxy_status"] == status for row in rows)
        for status in sorted(RESOURCE_STATUSES)
    }
    assignment_by_case = {str(row["case_id"]): row for row in rows}
    labeled_counts = {
        split: sum(
            assignment_by_case[item["case_id"]]["label_quality"] == "independent_exact"
            for item in allocation["assignments"]
            if item["split"] == split
        )
        for split in ("development", "validation", "temporal")
    }
    capacity = {
        "metadata_pair_count": len(rows),
        "prior_exposed_pair_count": sum(row["prior_pf00497_diagnostic_overlap"] for row in rows),
        "ri3_overlap_pair_count": sum(row["prior_ri3_overlap"] != "none" for row in rows),
        "new_metadata_pair_count": len(new_metadata_rows),
        "new_labeled_case_count": len(new_labeled_rows),
        "new_resource_eligible_case_count": len(_metadata_selection_pool(rows)),
        "heldout_labeled_case_count": labeled_counts["validation"] + labeled_counts["temporal"],
        "resource_proxy_status_counts": resource_counts,
    }
    if all(
        counts[split] >= TARGET_COUNTS[split] and labeled_counts[split] >= TARGET_COUNTS[split]
        for split in TARGET_COUNTS
    ):
        decision = "PASS"
    elif labeled_counts["development"] >= TARGET_COUNTS["development"] and (
        labeled_counts["validation"] < TARGET_COUNTS["validation"]
        or labeled_counts["temporal"] < TARGET_COUNTS["temporal"]
    ):
        decision = "DIAGNOSTIC_ONLY"
    else:
        decision = "NO_GO"
    reasons: list[str] = []
    if capacity["prior_exposed_pair_count"]:
        reasons.append("existing PF00497 diagnostic pairs are excluded from policy selection")
    if capacity["new_metadata_pair_count"] < sum(TARGET_COUNTS.values()):
        reasons.append("new metadata pool is smaller than the 6+2+2 target")
    if capacity["new_labeled_case_count"] < TARGET_COUNTS["development"]:
        reasons.append("independent new labels do not support six development cases")
    if labeled_counts["validation"] < TARGET_COUNTS["validation"]:
        reasons.append("independent exact validation label reserve is insufficient")
    if labeled_counts["temporal"] < TARGET_COUNTS["temporal"]:
        reasons.append("independent exact temporal label reserve is insufficient")
    report: dict[str, Any] = {
        "schema_version": FEASIBILITY_SCHEMA_VERSION,
        "status": "metadata_only_feasibility",
        "decision": decision,
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "family_id": family_id,
        "catalog_id": catalog_id,
        "source": {
            "inventory_sha256": str(
                inventory_payload.get("inventory_sha256") or _stable_hash(inventory_payload)
            ),
            "sequence_cluster_report_sha256": _stable_hash(sequence_cluster_payload),
            "prior_pair_payload_sha256": _stable_hash(prior_pair_payload),
            "prior_cohort_payload_sha256": _stable_hash(prior_cohort_payload),
            "ri3_manifest_sha256": _stable_hash(ri3_manifest_payload),
            "independent_label_payload_sha256": (
                _stable_hash(independent_label_payload)
                if independent_label_payload is not None
                else None
            ),
        },
        "allocation_policy": {
            "id": allocation["policy_id"],
            "validation_cutoff": allocation["validation_cutoff"],
            "temporal_cutoff": allocation["temporal_cutoff"],
            "target_counts": TARGET_COUNTS,
            "selection_features": ["metadata_quality", "leakage", "label_status", "resource_proxy"],
            "ranking_outcome_used": False,
        },
        "capacity": capacity,
        "labeled_split_counts": labeled_counts,
        "candidates": rows,
        "split_allocation": allocation,
        "decision_reasons": reasons,
        "boundary": {
            "metadata_only": True,
            "coordinates_downloaded": False,
            "holo_coordinates_opened": False,
            "evaluator_started": False,
            "detector_started": False,
            "benchmark_started": False,
            "nma_started": False,
            "ml_training_started": False,
            "claims_authorized": False,
        },
        "next_gate": (
            "new_versioned_source_catalog_contract"
            if decision == "NO_GO"
            else "freeze_manifest_then_materialize_development_apo_only"
        ),
    }
    report["report_sha256"] = _stable_hash(
        {key: value for key, value in report.items() if key != "report_sha256"}
    )
    return report


def render_markdown(report: Mapping[str, Any]) -> str:
    capacity = report["capacity"]
    allocation = report["split_allocation"]
    lines = [
        "# Ranking cohort feasibility v1",
        "",
        f"Decision: **{report['decision']}**",
        "",
        "This is a metadata-only gate. It is not a detector result, benchmark, "
        "validation, or discovery claim.",
        "",
        "## Capacity",
        "",
        "| Quantity | Count |",
        "|---|---:|",
        f"| Strict metadata pairs | {capacity['metadata_pair_count']} |",
        f"| Prior-exposed PF00497 pairs excluded | {capacity['prior_exposed_pair_count']} |",
        f"| New metadata pairs | {capacity['new_metadata_pair_count']} |",
        f"| New independent exact labels | {capacity['new_labeled_case_count']} |",
        f"| New resource-eligible cases | {capacity['new_resource_eligible_case_count']} |",
        f"| Held-out labeled reserve | {capacity['heldout_labeled_case_count']} |",
        f"| Labeled split counts | {report['labeled_split_counts']} |",
        "",
        "## Pre-sealed allocation",
        "",
        f"Policy: `{allocation['policy_id']}`; validation cutoff "
        f"`{allocation['validation_cutoff']}`; temporal cutoff "
        f"`{allocation['temporal_cutoff']}`.",
        "",
        "| Split | Target | Sealed count |",
        "|---|---:|---:|",
    ]
    for split in ("development", "validation", "temporal"):
        lines.append(f"| {split} | {TARGET_COUNTS[split]} | {allocation['counts'][split]} |")
    lines.extend(
        [
            "",
            "## Candidate audit",
            "",
            "| Apo | Holo | Cluster | Label | Resource | Prior PF00497 | RI-3 |",
            "|---|---|---|---|---|---|---|",
        ]
    )
    for row in report["candidates"]:
        lines.append(
            f"| {row['apo_structure_id']} | {row['holo_structure_id']} | "
            f"{row['sequence_cluster_status']} | {row['label_quality']} | "
            f"{row['resource_proxy_status']} | "
            f"{'yes' if row['prior_pf00497_diagnostic_overlap'] else 'no'} | "
            f"{row['prior_ri3_overlap']} |"
        )
    lines.extend(["", "## Decision reasons", ""])
    lines.extend(f"- {reason}" for reason in report["decision_reasons"])
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "Coordinates, holo structures, evaluator, detector, benchmark, NMA, "
            "and ML were not started.",
            "",
            f"Report SHA-256: `{report['report_sha256']}`",
            "",
        ]
    )
    return "\n".join(lines)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RankingCohortFeasibilityError(f"cannot read JSON input: {path}") from exc
    if not isinstance(value, dict):
        raise RankingCohortFeasibilityError(f"JSON input must be an object: {path}")
    return value


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    _write_text(path, json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n")


def run_ranking_cohort_feasibility(
    *,
    inventory_path: Path = DEFAULT_INVENTORY,
    sequence_cluster_path: Path = DEFAULT_CLUSTERS,
    prior_pair_path: Path = DEFAULT_PRIOR_PAIRS,
    prior_cohort_path: Path = DEFAULT_PRIOR_COHORT,
    ri3_manifest_path: Path = DEFAULT_RI3_MANIFEST,
    independent_label_path: Path | None = None,
    output_path: Path = DEFAULT_OUTPUT,
    markdown_path: Path = DEFAULT_MARKDOWN,
    catalog_id: str = "pfam-pf00497-metadata-inventory-v1",
    validation_cutoff: str = DEFAULT_VALIDATION_CUTOFF,
    temporal_cutoff: str = DEFAULT_TEMPORAL_CUTOFF,
) -> dict[str, Any]:
    labels = _read_json(independent_label_path) if independent_label_path else None
    report = assess_ranking_cohort_feasibility(
        _read_json(inventory_path),
        _read_json(sequence_cluster_path),
        prior_pair_payload=_read_json(prior_pair_path),
        prior_cohort_payload=_read_json(prior_cohort_path),
        ri3_manifest_payload=_read_json(ri3_manifest_path),
        independent_label_payload=labels,
        catalog_id=catalog_id,
        validation_cutoff=validation_cutoff,
        temporal_cutoff=temporal_cutoff,
    )
    _write_json(output_path, report)
    _write_text(markdown_path, render_markdown(report))
    print(
        f"ranking cohort feasibility: decision={report['decision']} "
        f"new_metadata={report['capacity']['new_metadata_pair_count']} "
        f"new_labeled={report['capacity']['new_labeled_case_count']}"
    )
    print(f"feasibility report: {output_path}")
    print(f"feasibility markdown: {markdown_path}")
    print("coordinates/holo/evaluator/detector/benchmark/NMA/ML started: no")
    return report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--sequence-clusters", type=Path, default=DEFAULT_CLUSTERS)
    parser.add_argument("--prior-pairs", type=Path, default=DEFAULT_PRIOR_PAIRS)
    parser.add_argument("--prior-cohort", type=Path, default=DEFAULT_PRIOR_COHORT)
    parser.add_argument("--ri3-manifest", type=Path, default=DEFAULT_RI3_MANIFEST)
    parser.add_argument("--independent-labels", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--catalog-id", default="pfam-pf00497-metadata-inventory-v1")
    parser.add_argument("--validation-cutoff", default=DEFAULT_VALIDATION_CUTOFF)
    parser.add_argument("--temporal-cutoff", default=DEFAULT_TEMPORAL_CUTOFF)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        run_ranking_cohort_feasibility(
            inventory_path=args.inventory,
            sequence_cluster_path=args.sequence_clusters,
            prior_pair_path=args.prior_pairs,
            prior_cohort_path=args.prior_cohort,
            ri3_manifest_path=args.ri3_manifest,
            independent_label_path=args.independent_labels,
            output_path=args.output,
            markdown_path=args.markdown,
            catalog_id=args.catalog_id,
            validation_cutoff=args.validation_cutoff,
            temporal_cutoff=args.temporal_cutoff,
        )
    except (RankingCohortFeasibilityError, ValueError) as exc:
        print(f"ranking cohort feasibility error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
