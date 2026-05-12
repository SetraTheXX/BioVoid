"""
Train and compare multiple ML classifiers for pocket druggability.

Usage:
    python scripts/train_multi_model.py

Trains RF, Gradient Boosting, and Logistic Regression models,
runs ablation study, and generates comparison report.
"""

import json
import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from src.database import AtlasDB
from src.ml.features import extract_batch, ALL_FEATURE_NAMES, normalize_features
from src.ml.dataset import build_dataset, LabelPolicy, SplitConfig, save_manifest
from src.ml.classifier import train_model, predict, ModelConfig, save_model
from src.ml.evaluation import evaluate_model, recall_at_k, precision_at_k, ablation_study

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def load_atlas_pockets(db_path: str = "data/atlas.db"):
    pockets = []
    pdb_ids = []
    with AtlasDB(db_path) as db:
        rows = db.search_pockets(limit=100000)
        for r in rows:
            sc = {}
            try:
                meta_raw = r.get("metadata_json", "{}")
                if meta_raw:
                    meta = json.loads(meta_raw) if isinstance(meta_raw, str) else meta_raw
                    sc = meta.get("score_components", {})
            except Exception:
                pass

            pocket = {
                "volume": float(r.get("volume", 0) or 0),
                "hydrophobic_ratio": float(r.get("hydrophobic_ratio", 0) or 0),
                "radius_geom": float(r.get("radius_geom", 0) or 0),
                "radius_clear": float(r.get("radius_clear", 0) or 0),
                "merged_vertices": int(r.get("merged_vertices", 0) or 0),
                "polar_atoms": int(r.get("polar_atoms", 0) or 0),
                "bio_score": float(r.get("bio_score", 0) or 0),
                "druggable": bool(r.get("druggable", False)),
                "druggability_class": r.get("druggability_class", "low"),
                "score_components": {
                    "volume_score": float(r.get("volume_score", 0) or 0),
                    "hydrophobicity_score": float(r.get("hydrophobicity_score", 0) or 0),
                    "enclosure_score": float(r.get("enclosure_score", 0) or 0),
                    "depth_score": float(r.get("depth_score", 0) or 0),
                    "sphericity": 0.0,
                    **sc,
                },
            }
            pockets.append(pocket)
            pdb_ids.append(r.get("pdb_id", "UNK"))

    return pockets, pdb_ids


def main():
    logger.info("Loading atlas data...")
    pockets, pdb_ids = load_atlas_pockets()
    logger.info("Loaded %d pockets from %d proteins", len(pockets), len(set(pdb_ids)))

    if len(pockets) < 50:
        logger.error("Not enough data")
        return

    scores = np.array([p.get("bio_score", 0) for p in pockets])
    p75 = float(np.percentile(scores, 75))
    p30 = float(np.percentile(scores, 30))

    ds = build_dataset(
        pockets, pdb_ids,
        label_policy=LabelPolicy(
            positive_min_bio_score=p75,
            negative_max_bio_score=p30,
            positive_require_druggable=True,
        ),
        split_config=SplitConfig(seed=42),
        exclude_uncertain=True,
    )

    logger.info("Dataset: Train=%d, Val=%d, Test=%d | Pos=%d, Neg=%d",
                ds["X_train"].shape[0], ds["X_val"].shape[0], ds["X_test"].shape[0],
                ds["manifest"].n_positive, ds["manifest"].n_negative)

    X_train, stats = normalize_features(ds["X_train"], method="standard")
    X_val, _ = normalize_features(ds["X_val"], method="standard", stats=stats)
    X_test, _ = normalize_features(ds["X_test"], method="standard", stats=stats)

    models_config = [
        ("Random Forest", ModelConfig(model_type="random_forest", n_estimators=200, max_depth=15)),
        ("Gradient Boosting", ModelConfig(model_type="gradient_boosting", n_estimators=200, max_depth=8)),
        ("Logistic Regression", ModelConfig(model_type="logistic")),
    ]

    results = {}
    best_model_name = None
    best_pr_auc = -1.0

    for name, config in models_config:
        logger.info("\n--- Training %s ---", name)
        result = train_model(X_train, ds["y_train"], config=config, X_val=X_val, y_val=ds["y_val"])
        pred = predict(result["model"], X_test)
        metrics = evaluate_model(ds["y_test"], pred["predictions"], pred["probabilities"])

        logger.info("  Accuracy:  %.4f", metrics["accuracy"])
        logger.info("  Precision: %.4f", metrics["precision"])
        logger.info("  Recall:    %.4f", metrics["recall"])
        logger.info("  F1:        %.4f", metrics["f1"])
        logger.info("  PR-AUC:    %s", metrics.get("pr_auc"))
        logger.info("  ROC-AUC:   %s", metrics.get("roc_auc"))
        logger.info("  ECE:       %s", metrics.get("ece"))

        if pred["probabilities"] is not None:
            r5 = recall_at_k(ds["y_test"], pred["probabilities"], k=5)
            r10 = recall_at_k(ds["y_test"], pred["probabilities"], k=10)
            r20 = recall_at_k(ds["y_test"], pred["probabilities"], k=20)
            logger.info("  Recall@5: %.4f | @10: %.4f | @20: %.4f", r5, r10, r20)
            metrics["recall_at_5"] = r5
            metrics["recall_at_10"] = r10
            metrics["recall_at_20"] = r20

        if result.get("feature_importances"):
            pairs = sorted(zip(ALL_FEATURE_NAMES, result["feature_importances"]),
                          key=lambda x: x[1], reverse=True)
            logger.info("  Top features: %s", ", ".join(f"{n}={v:.3f}" for n, v in pairs[:5]))
            metrics["top_features"] = {n: round(v, 4) for n, v in pairs}

        results[name] = {
            "metrics": metrics,
            "train_accuracy": result["train_accuracy"],
            "model_result": result,
        }

        pr_auc = metrics.get("pr_auc", 0) or 0
        if pr_auc > best_pr_auc:
            best_pr_auc = pr_auc
            best_model_name = name

    logger.info("\n" + "=" * 60)
    logger.info("MODEL COMPARISON RESULTS")
    logger.info("=" * 60)

    comparison = []
    for name, data in results.items():
        m = data["metrics"]
        marker = " <-- BEST" if name == best_model_name else ""
        logger.info("%-22s | F1=%.4f | PR-AUC=%s | ECE=%s%s",
                    name, m["f1"], m.get("pr_auc"), m.get("ece"), marker)
        comparison.append({
            "model": name,
            "accuracy": m["accuracy"],
            "precision": m["precision"],
            "recall": m["recall"],
            "f1": m["f1"],
            "pr_auc": m.get("pr_auc"),
            "roc_auc": m.get("roc_auc"),
            "ece": m.get("ece"),
        })

    logger.info("\nBest model: %s (PR-AUC: %s)", best_model_name, best_pr_auc)

    model_dir = Path("data/models")
    model_dir.mkdir(parents=True, exist_ok=True)

    best_result = results[best_model_name]["model_result"]
    best_result["normalization_stats"] = stats
    best_result["model_name"] = best_model_name
    save_model(best_result, model_dir / "pocket_classifier.pkl")

    report = {
        "comparison": comparison,
        "best_model": best_model_name,
        "best_pr_auc": best_pr_auc,
        "dataset": {
            "total_samples": ds["manifest"].n_samples,
            "positive": ds["manifest"].n_positive,
            "negative": ds["manifest"].n_negative,
            "train_size": ds["manifest"].train_size,
            "test_size": ds["manifest"].test_size,
        },
        "feature_names": list(ALL_FEATURE_NAMES),
    }

    report_path = model_dir / "model_comparison_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    logger.info("Comparison report saved: %s", report_path)

    logger.info("\n--- Running Ablation Study (best model) ---")
    from sklearn.ensemble import RandomForestClassifier

    def train_fn(X, y):
        clf = RandomForestClassifier(n_estimators=100, max_depth=10, random_state=42,
                                     class_weight="balanced", n_jobs=-1)
        clf.fit(X, y)
        return clf

    ablation_results = ablation_study(
        train_fn, X_train, ds["y_train"], X_test, ds["y_test"],
        list(ALL_FEATURE_NAMES)
    )

    logger.info("\nAblation Results (feature importance by removal):")
    for r in ablation_results[:8]:
        logger.info("  %-35s delta_F1=%.4f  delta_PR-AUC=%.4f",
                    r["feature_removed"], r["delta_f1"], r["delta_pr_auc"])

    ablation_path = model_dir / "ablation_study.json"
    with open(ablation_path, "w") as f:
        json.dump(ablation_results, f, indent=2, default=str)
    logger.info("Ablation study saved: %s", ablation_path)

    save_manifest(ds["manifest"], model_dir / "dataset_manifest.json")
    logger.info("\nDone! All models trained and compared.")


if __name__ == "__main__":
    main()
