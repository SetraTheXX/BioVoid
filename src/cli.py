"""
Bio-Void Hunter: Modern CLI Interface
========================================

Subcommand-based CLI using argparse (zero external deps).

Commands:
    analyze   - Run pipeline on a single protein
    batch     - Analyze multiple proteins
    serve     - Start the API server
    cache     - Manage analysis cache
    alphafold - Run explicitly-enabled experimental AlphaFold ensemble evidence
    benchmark - Run the quarantined legacy benchmark (explicit opt-in)
    info      - Show project info and config
"""

from __future__ import annotations

import argparse
import logging
import math
import re
import sys
from pathlib import Path

from .config import API, PATHS, PIPELINE
from .resources import SAFE_16GB

logger = logging.getLogger(__name__)
_RCSB_ID_PATTERN = re.compile(r"^[A-Z0-9]{4}$")
_MAX_CLI_BATCH_SIZE = 10


def _normalize_pdb_id(value: str) -> str:
    """Normalize one RCSB identifier and reject malformed input."""
    normalized = value.strip().upper()
    if not _RCSB_ID_PATTERN.fullmatch(normalized):
        raise ValueError(
            f"PDB ID must contain exactly four alphanumeric characters; received: {value!r}"
        )
    return normalized


def _parse_pdb_id_arg(value: str) -> str:
    """Argparse adapter for a single RCSB identifier."""
    try:
        return _normalize_pdb_id(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _bounded_int_arg(value: str, *, name: str, maximum: int) -> int:
    """Parse a positive bounded integer before any work is started."""
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError(f"{name} must be an integer") from exc
    if not 1 <= parsed <= maximum:
        raise argparse.ArgumentTypeError(f"{name} must be in the range 1-{maximum}")
    return parsed


def _safe_n_frames_arg(value: str) -> int:
    return _bounded_int_arg(
        value,
        name="--n-frames",
        maximum=SAFE_16GB.max_samples_per_mode,
    )


def _legacy_n_frames_arg(value: str) -> int:
    """Keep the quarantined legacy benchmark's historical upper bound explicit."""
    return _bounded_int_arg(value, name="--n-frames", maximum=20)


def _positive_float_arg(value: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("--tolerance must be a number") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("--tolerance must be a finite number greater than zero")
    return parsed


def _port_arg(value: str) -> int:
    return _bounded_int_arg(value, name="--port", maximum=65535)


def _setup_logging(verbose: bool = False):
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-5s %(message)s",
        datefmt="%H:%M:%S",
    )


def cmd_analyze(args):
    """Run pipeline on a single protein."""
    _setup_logging(args.verbose)

    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from main import BioVoidPipeline

        pipeline = BioVoidPipeline(
            pdb_id=args.pdb_id,
            n_frames=args.n_frames,
            verbose=args.verbose,
            output_dir=args.output,
            profile=args.profile,
            dock=args.dock,
            use_ml=args.use_ml,
            multiframe=args.motion_aware,
            allow_experimental=args.allow_experimental,
        )
        report = pipeline.run()
    except Exception as exc:
        logger.error("Analysis failed for %s: %s", args.pdb_id, exc)
        return 1

    logger.info(
        "PDB: %s | Cavities: %d | Heuristic shortlist: %d | Time: %.1fs",
        report["pdb_id"],
        report["total_cavities"],
        report["heuristic_shortlist_cavities"],
        report["runtime_seconds"],
    )


def _parse_batch_pdb_ids(raw_pdb_ids: str) -> list[str]:
    """Normalize and validate the comma-separated RCSB IDs accepted by ``batch``."""
    pdb_ids = [pdb_id.strip().upper() for pdb_id in raw_pdb_ids.split(",")]
    invalid = [pdb_id or "<empty>" for pdb_id in pdb_ids if not _RCSB_ID_PATTERN.fullmatch(pdb_id)]
    if invalid:
        raise ValueError(
            "Batch input must contain only four alphanumeric characters per PDB ID; "
            f"invalid values: {', '.join(invalid)}"
        )
    if len(pdb_ids) > _MAX_CLI_BATCH_SIZE:
        raise ValueError(
            f"Batch input is limited to {_MAX_CLI_BATCH_SIZE} PDB IDs for the safe local CLI"
        )
    return pdb_ids


def cmd_batch(args):
    """Analyze multiple proteins."""
    _setup_logging(args.verbose)
    logger = logging.getLogger("biovoid.cli.batch")

    try:
        pdb_ids = _parse_batch_pdb_ids(args.pdb_ids)
    except ValueError as exc:
        logger.error("%s", exc)
        return 2

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
    return 0 if succeeded == len(results) else 1


def cmd_serve(args):
    """Start the API server."""
    _setup_logging(args.verbose)

    try:
        import uvicorn
    except ImportError:
        logger.error("uvicorn is required: pip install uvicorn")
        return 1

    try:
        uvicorn.run(
            "src.api.app:app",
            host=args.host,
            port=args.port,
            reload=args.reload,
            log_level="debug" if args.verbose else "info",
        )
    except Exception as exc:
        logger.error("API server failed: %s", exc)
        return 1
    return 0


def cmd_cache(args):
    """Manage analysis cache."""
    _setup_logging()
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
        count = cache.invalidate_source(args.pdb_id)
        logger.info("Invalidated %d cache entries for %s", count, args.pdb_id)


def cmd_alphafold(args):
    """Run AlphaFold ensemble analysis."""
    _setup_logging(args.verbose)

    if not getattr(args, "allow_experimental", False):
        logger.error(
            "AlphaFold ensemble analysis is experimental and disabled during recovery. "
            "Re-run with --allow-experimental only for an explicitly requested evidence run."
        )
        return 2

    try:
        from .alphafold_ensemble import EnsembleConfig, run_alphafold_ensemble_pipeline

        config = EnsembleConfig(
            n_frames_per_amplitude=args.frames_per_amp,
            profile=args.profile,
        )
        result = run_alphafold_ensemble_pipeline(
            uniprot_id=args.uniprot_id,
            config=config,
        )
    except Exception as exc:
        logger.error("AlphaFold ensemble failed for %s: %s", args.uniprot_id, exc)
        return 1

    analysis = result.get("analysis", {})
    n_pockets = analysis.get("total_consensus_pockets", len(analysis.get("consensus_pockets", [])))
    n_frames = analysis.get("total_frames_analyzed", 0)
    logger.info("AlphaFold Ensemble: %s", args.uniprot_id)
    logger.info("Frames analyzed: %d", n_frames)
    logger.info("Consensus pockets: %d", n_pockets)

    for p in result["analysis"].get("consensus_pockets", [])[:5]:
        center = p.get("center", [0, 0, 0])
        logger.info(
            "  Pocket #%d: score=%.3f center=[%.1f, %.1f, %.1f]",
            p.get("id", 0),
            p.get("consensus_score", 0),
            center[0],
            center[1],
            center[2],
        )
    return 0


def cmd_benchmark(args):
    """Run benchmark against known cryptic pockets."""
    _setup_logging(args.verbose)
    if not args.allow_legacy_benchmark:
        logger.error(
            "The historical score-weighted benchmark is quarantined during recovery. "
            "Use --allow-legacy-benchmark only for labelled legacy reproduction."
        )
        raise SystemExit(2)

    from .benchmark import (
        KNOWN_CRYPTIC_POCKETS,
        format_benchmark_table,
        run_benchmark,
        save_benchmark_report,
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

    summary = run_benchmark(
        results_by_protein,
        tolerance=args.tolerance,
        allow_legacy=True,
    )
    logger.info("\n%s", format_benchmark_table(summary))

    if args.output:
        save_benchmark_report(summary, args.output)


def cmd_info(args):
    """Show project configuration and info."""
    _setup_logging()
    import src

    logger.info("Bio-Void Hunter v%s", src.__version__)
    logger.info("Data root: %s", PATHS.data_root)
    logger.info("Results dir: %s", PATHS.results)
    logger.info("Atlas DB: %s", PATHS.atlas_db)
    logger.info("Default motion samples per mode: %d", PIPELINE.n_frames)
    logger.info("Default profile: %s", PIPELINE.profile)
    logger.info("API: %s:%d", API.host, API.port)


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="biovoid",
        description="BioVoid: local protein pocket analysis research prototype",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # analyze
    p_analyze = sub.add_parser("analyze", help="Analyze a single protein")
    p_analyze.add_argument("pdb_id", type=_parse_pdb_id_arg, help="PDB ID (e.g. 1CBS)")
    p_analyze.add_argument(
        "--n-frames",
        type=_safe_n_frames_arg,
        default=PIPELINE.n_frames,
        help=(
            "Independent samples per NMA mode (legacy option name; "
            f"safe-16gb max: {SAFE_16GB.max_samples_per_mode})"
        ),
    )
    p_analyze.add_argument(
        "--profile", default=PIPELINE.profile, choices=list(PIPELINE.scoring_profiles)
    )
    p_analyze.add_argument("--output", default=str(PATHS.runs))
    p_analyze.add_argument("--dock", action="store_true")
    p_analyze.add_argument("--use-ml", action="store_true")
    p_analyze.add_argument(
        "--motion-aware",
        action="store_true",
        help="Enable the experimental quality-gated motion ensemble",
    )
    p_analyze.add_argument(
        "--allow-experimental",
        action="store_true",
        help="Allow explicitly requested non-canonical experimental features",
    )
    p_analyze.add_argument("-v", "--verbose", action="store_true")
    p_analyze.set_defaults(func=cmd_analyze)

    # batch
    p_batch = sub.add_parser("batch", help="Analyze multiple proteins")
    p_batch.add_argument("pdb_ids", help="Comma-separated PDB IDs")
    p_batch.add_argument(
        "--n-frames",
        type=_safe_n_frames_arg,
        default=PIPELINE.n_frames,
        help=f"Independent samples per mode (safe-16gb max: {SAFE_16GB.max_samples_per_mode})",
    )
    p_batch.add_argument(
        "--profile", default=PIPELINE.profile, choices=list(PIPELINE.scoring_profiles)
    )
    p_batch.add_argument("--output", default=str(PATHS.results))
    p_batch.add_argument("-v", "--verbose", action="store_true")
    p_batch.set_defaults(func=cmd_batch)

    # serve
    p_serve = sub.add_parser("serve", help="Start API server")
    p_serve.add_argument("--host", default=API.host)
    p_serve.add_argument("--port", type=_port_arg, default=API.port)
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
    p_af.add_argument(
        "--frames-per-amp",
        type=_safe_n_frames_arg,
        default=PIPELINE.n_frames,
        help="Independent samples per mode and amplitude (1-8)",
    )
    p_af.add_argument(
        "--profile", default=PIPELINE.profile, choices=list(PIPELINE.scoring_profiles)
    )
    p_af.add_argument(
        "--allow-experimental",
        action="store_true",
        help="Allow this explicitly requested experimental motion evidence run",
    )
    p_af.add_argument("-v", "--verbose", action="store_true")
    p_af.set_defaults(func=cmd_alphafold)

    # benchmark
    p_bench = sub.add_parser("benchmark", help="Run accuracy benchmark")
    p_bench.add_argument("--n-frames", type=_legacy_n_frames_arg, default=20)
    p_bench.add_argument(
        "--profile", default=PIPELINE.profile, choices=list(PIPELINE.scoring_profiles)
    )
    p_bench.add_argument("--tolerance", type=_positive_float_arg, default=8.0)
    p_bench.add_argument("--output", default=None, help="Save report JSON path")
    p_bench.add_argument(
        "--allow-legacy-benchmark",
        action="store_true",
        help="Run the quarantined historical evaluator and label output non-validated",
    )
    p_bench.add_argument("-v", "--verbose", action="store_true")
    p_bench.set_defaults(func=cmd_benchmark)

    # info
    p_info = sub.add_parser("info", help="Show project info")
    p_info.set_defaults(func=cmd_info)

    args = parser.parse_args()
    result = args.func(args)
    return result if isinstance(result, int) else 0


if __name__ == "__main__":
    sys.exit(main())
