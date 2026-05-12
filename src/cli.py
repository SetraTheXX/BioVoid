"""
Bio-Void Hunter: Modern CLI Interface
========================================

Subcommand-based CLI using argparse (zero external deps).

Commands:
    analyze   - Run pipeline on a single protein
    batch     - Analyze multiple proteins
    serve     - Start the API server
    cache     - Manage analysis cache
    info      - Show project info and config
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .config import PATHS, PIPELINE, API

logger = logging.getLogger(__name__)


def _setup_logging(verbose: bool = False):
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-5s %(message)s",
        datefmt="%H:%M:%S",
    )


def cmd_analyze(args):
    """Run pipeline on a single protein."""
    _setup_logging(args.verbose)

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from main import BioVoidPipeline

    pipeline = BioVoidPipeline(
        pdb_id=args.pdb_id,
        n_frames=args.n_frames,
        verbose=args.verbose,
        output_dir=args.output,
        profile=args.profile,
        dock=args.dock,
    )
    report = pipeline.run()

    logger.info("PDB: %s | Cavities: %d | Druggable: %d | Time: %.1fs",
                report['pdb_id'], report['total_cavities'],
                report['druggable_cavities'], report['runtime_seconds'])


def cmd_batch(args):
    """Analyze multiple proteins."""
    _setup_logging(args.verbose)
    logger = logging.getLogger("biovoid.cli.batch")

    pdb_ids = [pid.strip().upper() for pid in args.pdb_ids.split(",")]
    logger.info("Batch analysis: %d proteins", len(pdb_ids))

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from main import BioVoidPipeline

    results = []
    for pdb_id in pdb_ids:
        try:
            pipeline = BioVoidPipeline(
                pdb_id=pdb_id,
                n_frames=args.n_frames,
                verbose=args.verbose,
                output_dir=args.output,
                profile=args.profile,
            )
            report = pipeline.run()
            results.append({"pdb_id": pdb_id, "status": "success", "report": report})
            logger.info("[OK] %s: %d cavities", pdb_id, report["total_cavities"])
        except Exception as e:
            results.append({"pdb_id": pdb_id, "status": "error", "error": str(e)})
            logger.error("[FAIL] %s: %s", pdb_id, e)

    succeeded = sum(1 for r in results if r["status"] == "success")
    logger.info("Batch complete: %d/%d succeeded", succeeded, len(results))


def cmd_serve(args):
    """Start the API server."""
    _setup_logging(args.verbose)

    try:
        import uvicorn
    except ImportError:
        logger.error("uvicorn is required: pip install uvicorn")
        sys.exit(1)

    uvicorn.run(
        "src.api.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="debug" if args.verbose else "info",
    )


def cmd_cache(args):
    """Manage analysis cache."""
    from .cache import AnalysisCache

    cache = AnalysisCache()

    if args.action == "stats":
        stats = cache.stats()
        for k, v in stats.items():
            logger.info("  %s: %s", k, v)

    elif args.action == "clear":
        count = cache.clear()
        logger.info("Cleared %d cache entries", count)

    elif args.action == "invalidate":
        if not args.pdb_id:
            logger.error("--pdb-id required for invalidate")
            sys.exit(1)
        cache.invalidate(args.pdb_id)
        logger.info("Invalidated cache for %s", args.pdb_id)


def cmd_alphafold(args):
    """Run AlphaFold ensemble analysis."""
    _setup_logging(args.verbose)
    from .alphafold_ensemble import run_alphafold_ensemble_pipeline, EnsembleConfig

    config = EnsembleConfig(
        n_frames_per_amplitude=args.frames_per_amp,
        profile=args.profile,
    )
    result = run_alphafold_ensemble_pipeline(
        uniprot_id=args.uniprot_id,
        config=config,
    )

    n_pockets = result["analysis"]["total_consensus_pockets"]
    n_frames = result["analysis"]["total_frames_analyzed"]
    logger.info("AlphaFold Ensemble: %s", args.uniprot_id)
    logger.info("Frames analyzed: %d", n_frames)
    logger.info("Consensus pockets: %d", n_pockets)

    for p in result["analysis"].get("consensus_pockets", [])[:5]:
        center = p.get("center", [0, 0, 0])
        logger.info("  Pocket #%d: score=%.3f center=[%.1f, %.1f, %.1f]",
                     p.get('id', 0), p.get('consensus_score', 0),
                     center[0], center[1], center[2])


def cmd_benchmark(args):
    """Run benchmark against known cryptic pockets."""
    _setup_logging(args.verbose)
    from .benchmark import (
        run_benchmark, format_benchmark_table, save_benchmark_report,
        KNOWN_CRYPTIC_POCKETS,
    )

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from main import BioVoidPipeline

    results_by_protein: dict[str, list] = {}

    for pdb_id in KNOWN_CRYPTIC_POCKETS:
        try:
            pipeline = BioVoidPipeline(
                pdb_id=pdb_id,
                n_frames=args.n_frames,
                profile=args.profile,
                use_cache=True,
            )
            report = pipeline.run()
            results_by_protein[pdb_id] = report.get("cavities", [])
        except Exception as e:
            logging.getLogger().error("Failed %s: %s", pdb_id, e)
            results_by_protein[pdb_id] = []

    summary = run_benchmark(results_by_protein, tolerance=args.tolerance)
    logger.info("\n%s", format_benchmark_table(summary))

    if args.output:
        save_benchmark_report(summary, args.output)


def cmd_info(args):
    """Show project configuration and info."""
    import src
    logger.info("Bio-Void Hunter v%s", src.__version__)
    logger.info("Data root: %s", PATHS.data_root)
    logger.info("Results dir: %s", PATHS.results)
    logger.info("Atlas DB: %s", PATHS.atlas_db)
    logger.info("Default frames: %d", PIPELINE.n_frames)
    logger.info("Default profile: %s", PIPELINE.profile)
    logger.info("API: %s:%d", API.host, API.port)


def main():
    parser = argparse.ArgumentParser(
        prog="biovoid",
        description="Bio-Void Hunter: Cryptic Pocket Discovery",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # analyze
    p_analyze = sub.add_parser("analyze", help="Analyze a single protein")
    p_analyze.add_argument("pdb_id", help="PDB ID (e.g. 1CBS)")
    p_analyze.add_argument("--n-frames", type=int, default=PIPELINE.n_frames)
    p_analyze.add_argument("--profile", default=PIPELINE.profile,
                           choices=list(PIPELINE.scoring_profiles))
    p_analyze.add_argument("--output", default=str(PATHS.results))
    p_analyze.add_argument("--dock", action="store_true")
    p_analyze.add_argument("-v", "--verbose", action="store_true")
    p_analyze.set_defaults(func=cmd_analyze)

    # batch
    p_batch = sub.add_parser("batch", help="Analyze multiple proteins")
    p_batch.add_argument("pdb_ids", help="Comma-separated PDB IDs")
    p_batch.add_argument("--n-frames", type=int, default=PIPELINE.n_frames)
    p_batch.add_argument("--profile", default=PIPELINE.profile)
    p_batch.add_argument("--output", default=str(PATHS.results))
    p_batch.add_argument("-v", "--verbose", action="store_true")
    p_batch.set_defaults(func=cmd_batch)

    # serve
    p_serve = sub.add_parser("serve", help="Start API server")
    p_serve.add_argument("--host", default=API.host)
    p_serve.add_argument("--port", type=int, default=API.port)
    p_serve.add_argument("--reload", action="store_true")
    p_serve.add_argument("-v", "--verbose", action="store_true")
    p_serve.set_defaults(func=cmd_serve)

    # cache
    p_cache = sub.add_parser("cache", help="Manage analysis cache")
    p_cache.add_argument("action", choices=["stats", "clear", "invalidate"])
    p_cache.add_argument("--pdb-id", default=None)
    p_cache.set_defaults(func=cmd_cache)

    # alphafold
    p_af = sub.add_parser("alphafold", help="AlphaFold ensemble analysis")
    p_af.add_argument("uniprot_id", help="UniProt ID (e.g. P04637)")
    p_af.add_argument("--frames-per-amp", type=int, default=10)
    p_af.add_argument("--profile", default=PIPELINE.profile)
    p_af.add_argument("-v", "--verbose", action="store_true")
    p_af.set_defaults(func=cmd_alphafold)

    # benchmark
    p_bench = sub.add_parser("benchmark", help="Run accuracy benchmark")
    p_bench.add_argument("--n-frames", type=int, default=20)
    p_bench.add_argument("--profile", default=PIPELINE.profile)
    p_bench.add_argument("--tolerance", type=float, default=8.0)
    p_bench.add_argument("--output", default=None, help="Save report JSON path")
    p_bench.add_argument("-v", "--verbose", action="store_true")
    p_bench.set_defaults(func=cmd_benchmark)

    # info
    p_info = sub.add_parser("info", help="Show project info")
    p_info.set_defaults(func=cmd_info)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
