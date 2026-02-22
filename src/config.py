"""
Bio-Void Hunter: Central Configuration
=======================================

Pipeline-level defaults and path constants.
Domain-specific constants (e.g. grid buffer, scoring thresholds)
remain in their respective modules.
"""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Paths:
    data_root: Path = Path("data")
    raw_pdb: Path = field(default_factory=lambda: Path("data/raw_pdb"))
    frames: Path = field(default_factory=lambda: Path("data/frames"))
    results: Path = field(default_factory=lambda: Path("data/results"))
    docking: Path = field(default_factory=lambda: Path("data/docking"))
    atlas_db: Path = field(default_factory=lambda: Path("data/atlas.db"))
    validation: Path = field(default_factory=lambda: Path("data/validation"))


@dataclass(frozen=True)
class PipelineDefaults:
    n_frames: int = 50
    n_modes: int = 10
    profile: str = "default"
    scoring_profiles: tuple = ("enzyme", "ppi", "gpcr", "default")
    dock: bool = False
    verbose: bool = False


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


PATHS = Paths()
PIPELINE = PipelineDefaults()
CRAWLER = CrawlerDefaults()
API = APIDefaults()
