"""
Train ML classifier from Atlas database.

Usage:
    python scripts/train_ml_model.py

Saves trained model to data/models/pocket_classifier.pkl
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import logging
import numpy as np

from src.database import AtlasDB
from src.ml.features import extract_batch, ALL_FEATURE_NAMES, normalize_features
from src.ml.dataset import build_dataset, LabelPolicy, SplitConfig, save_manifest
from src.ml.classifier import train_model, predict, ModelConfig, save_model
from src.ml.evaluation import evaluate_model, recall_at_k, precision_at_k

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def load_atlas_pockets(db_path: str = "data/atlas.db"):
    """Load all pockets from atlas with their PDB IDs."""
    pockets = []
    pdb_ids = []
    with AtlasDB(db_path) as db:
        rows = db.search_pockets(limit=100000)
        for r in rows:
            sc = {}
            try:
                import json
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
        logger.error("Not enough data to train (need >= 50)")
        return

    scores = np.array([p.get("bio_score", 0) for p in pockets])
    p75 = float(np.percentile(scores, 75))
    p30 = float(np.percentile(scores, 30))
    logger.info("Score distribution: P30=%.4f, P75=%.4f", p30, p75)

    logger.info("Building dataset...")
    ds = build_dataset(
        pockets, pdb_ids,
        label_policy=LabelPolicy(
            positive_min_bio_score=p75,
            negative_max_bio_score=p30,
            positive_require_druggable=True,
        ),
        split_config=SplitConfig(train_ratio=0.70, val_ratio=0.15, test_ratio=0.15, seed=42),
        exclude_uncertain=True,
    )

    logger.info("Train: %d, Val: %d, Test: %d",
                ds["X_train"].shape[0], ds["X_val"].shape[0], ds["X_test"].shape[0])
    logger.info("Positive: %d, Negative: %d",
                ds["manifest"].n_positive, ds["manifest"].n_negative)

    if ds["X_train"].shape[0] < 20 or ds["manifest"].n_positive < 5 or ds["manifest"].n_negative < 5:
        logger.error("Not enough labeled samples (need both classes)")
        return

    X_train, stats = normalize_features(ds["X_train"], method="standard")
    X_val, _ = normalize_features(ds["X_val"], method="standard", stats=stats)
    X_test, _ = normalize_features(ds["X_test"], method="standard", stats=stats)

    logger.info("Training Random Forest...")
    result = train_model(
        X_train, ds["y_train"],
        config=ModelConfig(model_type="random_forest", n_estimators=200, max_depth=15),
        X_val=X_val, y_val=ds["y_val"],
    )
    logger.info("Train accuracy: %.4f", result["train_accuracy"])

    pred = predict(result["model"], X_test)
    metrics = evaluate_model(ds["y_test"], pred["predictions"], pred["probabilities"])

    logger.info("Test Results:")
    logger.info("  Accuracy:  %.4f", metrics["accuracy"])
    logger.info("  Precision: %.4f", metrics["precision"])
    logger.info("  Recall:    %.4f", metrics["recall"])
    logger.info("  F1:        %.4f", metrics["f1"])
    logger.info("  ROC-AUC:   %s", metrics.get("roc_auc"))
    logger.info("  PR-AUC:    %s", metrics.get("pr_auc"))
    logger.info("  ECE:       %s", metrics.get("ece"))

    if pred["probabilities"] is not None:
        r5 = recall_at_k(ds["y_test"], pred["probabilities"], k=5)
        p5 = precision_at_k(ds["y_test"], pred["probabilities"], k=5)
        logger.info("  Recall@5:  %.4f", r5)
        logger.info("  Precision@5: %.4f", p5)

    model_dir = Path("data/models")
    model_dir.mkdir(parents=True, exist_ok=True)

    result["normalization_stats"] = stats
    save_model(result, model_dir / "pocket_classifier.pkl")

    save_manifest(ds["manifest"], model_dir / "dataset_manifest.json")

    if result.get("feature_importances"):
        logger.info("\nFeature Importances:")
        pairs = list(zip(ALL_FEATURE_NAMES, result["feature_importances"]))
        pairs.sort(key=lambda x: x[1], reverse=True)
        for name, imp in pairs[:10]:
            logger.info("  %-30s %.4f", name, imp)

    logger.info("\nModel saved to data/models/pocket_classifier.pkl")
    logger.info("Done!")


if __name__ == "__main__":
    main()
