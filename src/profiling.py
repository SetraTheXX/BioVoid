"""
Bio-Void Hunter: Pipeline Profiling
=====================================

Lightweight timing and memory profiling for pipeline steps.
No external dependencies beyond stdlib.

Usage:
    with StepTimer("NMA simulation") as t:
        run_nma_simulation(...)
    print(t.report())

    profiler = PipelineProfiler()
    profiler.start("fetch")
    ...
    profiler.stop("fetch")
    print(profiler.summary())
"""

from __future__ import annotations

import logging
import time
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class StepTiming:
    """Timing data for a single pipeline step."""

    name: str
    start_time: float = 0.0
    end_time: float = 0.0
    elapsed_ms: float = 0.0
    success: bool = True
    error: str | None = None


class StepTimer:
    """Context manager for timing a single operation."""

    def __init__(self, name: str):
        self.name = name
        self.timing = StepTiming(name=name)

    def __enter__(self) -> StepTiming:
        self.timing.start_time = time.perf_counter()
        return self.timing

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.timing.end_time = time.perf_counter()
        self.timing.elapsed_ms = (self.timing.end_time - self.timing.start_time) * 1000.0
        if exc_type is not None:
            self.timing.success = False
            self.timing.error = str(exc_val)
        logger.debug(
            "[PROFILE] %s: %.1fms (success=%s)",
            self.name,
            self.timing.elapsed_ms,
            self.timing.success,
        )
        return False

    def report(self) -> str:
        status = "OK" if self.timing.success else f"FAIL: {self.timing.error}"
        return f"{self.name}: {self.timing.elapsed_ms:.1f}ms [{status}]"


class PipelineProfiler:
    """Accumulates timing data for all pipeline steps."""

    def __init__(self):
        self._timings: dict[str, StepTiming] = {}
        self._order: list[str] = []
        self._pipeline_start: float = 0.0

    def start_pipeline(self):
        self._pipeline_start = time.perf_counter()

    def start(self, step_name: str):
        timing = StepTiming(name=step_name, start_time=time.perf_counter())
        self._timings[step_name] = timing
        if step_name not in self._order:
            self._order.append(step_name)

    def stop(self, step_name: str, success: bool = True, error: str | None = None):
        timing = self._timings.get(step_name)
        if timing is None:
            return
        timing.end_time = time.perf_counter()
        timing.elapsed_ms = (timing.end_time - timing.start_time) * 1000.0
        timing.success = success
        timing.error = error

    @contextmanager
    def step(self, name: str) -> Generator[StepTiming, None, None]:
        self.start(name)
        timing = self._timings[name]
        try:
            yield timing
        except Exception as e:
            self.stop(name, success=False, error=str(e))
            raise
        else:
            self.stop(name)

    def summary(self) -> dict[str, Any]:
        total_ms = sum(t.elapsed_ms for t in self._timings.values())
        pipeline_elapsed = 0.0
        if self._pipeline_start > 0:
            pipeline_elapsed = (time.perf_counter() - self._pipeline_start) * 1000.0

        steps = []
        for name in self._order:
            t = self._timings[name]
            pct = (t.elapsed_ms / total_ms * 100.0) if total_ms > 0 else 0.0
            steps.append(
                {
                    "name": name,
                    "elapsed_ms": round(t.elapsed_ms, 1),
                    "pct_of_total": round(pct, 1),
                    "success": t.success,
                    "error": t.error,
                }
            )

        bottleneck = max(steps, key=lambda s: s["elapsed_ms"]) if steps else None

        return {
            "total_step_ms": round(total_ms, 1),
            "pipeline_elapsed_ms": round(pipeline_elapsed, 1),
            "n_steps": len(steps),
            "steps": steps,
            "bottleneck": bottleneck["name"] if bottleneck else None,
        }

    def format_table(self) -> str:
        s = self.summary()
        lines = [
            f"{'Step':<25} {'Time (ms)':>10} {'%':>6} {'Status':>8}",
            "-" * 55,
        ]
        for step in s["steps"]:
            status = "OK" if step["success"] else "FAIL"
            lines.append(
                f"{step['name']:<25} {step['elapsed_ms']:>10.1f} "
                f"{step['pct_of_total']:>5.1f}% {status:>8}"
            )
        lines.append("-" * 55)
        lines.append(f"{'TOTAL':<25} {s['total_step_ms']:>10.1f}   100%")
        if s["bottleneck"]:
            lines.append(f"Bottleneck: {s['bottleneck']}")
        return "\n".join(lines)
