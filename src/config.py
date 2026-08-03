"""
Bio-Void Hunter: Central Configuration
=======================================

Pipeline-level defaults and path constants.
Domain-specific constants (e.g. grid buffer, scoring thresholds)
remain in their respective modules.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import TypedDict


class CavityDict(TypedDict, total=False):
    """Typed dictionary for cavity data structures."""

    id: int
    center: list[float]
    volume: float
    radius_geom: float
    radius_clear: float
    merged_vertices: int
    vertices: list
    hydrophobic_ratio: float
    polar_atoms: int
    druggable: bool
    bio_score: float
    druggability_class: str
    score_components: dict
    profile_used: str
    pocket_fit_score: float
    ml_score: float
    ml_rank: int
    rank: int


@dataclass(frozen=True)
class Paths:
    data_root: Path = Path("data")
    raw_pdb: Path = field(default_factory=lambda: Path("data/raw_pdb"))
    validation: Path = field(default_factory=lambda: Path("data/validation"))
    legacy_frames: Path = field(default_factory=lambda: Path("data/frames"))
    legacy_results: Path = field(default_factory=lambda: Path("data/results"))
    legacy_docking: Path = field(default_factory=lambda: Path("data/docking"))
    legacy_cache: Path = field(default_factory=lambda: Path("data/.cache"))
    legacy_atlas_db: Path = field(default_factory=lambda: Path("data/atlas.db"))
    models: Path = field(default_factory=lambda: Path("data/models"))
    runtime_root: Path = field(default_factory=lambda: Path("data/runtime"))
    runs: Path = field(default_factory=lambda: Path("data/runtime/runs"))
    frames: Path = field(default_factory=lambda: Path("data/runtime/frames"))
    results: Path = field(default_factory=lambda: Path("data/runtime/results"))
    docking: Path = field(default_factory=lambda: Path("data/runtime/docking"))
    cache: Path = field(default_factory=lambda: Path("data/runtime/cache-v2"))
    atlas_db: Path = field(default_factory=lambda: Path("data/runtime/atlas-recovery-v1.sqlite"))


@dataclass(frozen=True)
class PipelineDefaults:
    # Independent non-reference samples per mode for the experimental motion layer.
    n_frames: int = 4
    n_modes: int = 10
    profile: str = "default"
    scoring_profiles: tuple = ("enzyme", "ppi", "gpcr", "default")
    alphafold_amplitudes: tuple = (2.0, 3.0, 5.0)
    dock: bool = False
    use_ml: bool = False
    multiframe: bool = False
    verbose: bool = False


@dataclass(frozen=True)
class RecoveryPolicy:
    mode: str = "recovery"
    canonical_static_ready: bool = True
    motion_aware: str = "experimental_default_off"
    ml_reranking: str = "experimental_default_off"
    docking: str = "experimental_default_off"
    legacy_benchmark: str = "disabled"
    bulk_crawler: str = "disabled"
    result_validation_status: str = "recovery_unvalidated"


@dataclass(frozen=True)
class CrawlerDefaults:
    max_workers: int = 4
    download_workers: int = 20
    timeout_per_protein: int = 120
    checkpoint_interval: int = 100
    batch_size: int = 50


@dataclass(frozen=True)
class APIDefaults:
    host: str = "127.0.0.1"
    port: int = 8000
    rate_limit_per_minute: int = 30


@dataclass(frozen=True)
class LoggingDefaults:
    level: str = "INFO"
    format: str = "json"
    log_file: str = ""


def _env_override(env_key: str, default: str) -> str:
    import os

    return os.environ.get(env_key, default)


PATHS = Paths()
PIPELINE = PipelineDefaults()
RECOVERY = RecoveryPolicy()
CRAWLER = CrawlerDefaults()
API = APIDefaults()
LOGGING = LoggingDefaults(
    level=_env_override("BIOVOID_LOG_LEVEL", "INFO"),
    format=_env_override("BIOVOID_LOG_FORMAT", "json"),
    log_file=_env_override("BIOVOID_LOG_FILE", ""),
)
