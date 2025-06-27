"""Fuzzing metrics collection and analysis"""

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Union

from prometheus_client import Counter, Gauge, Histogram
from rich.console import Console


console = Console()


class MetricType(Enum):
    """Types of fuzzing metrics"""
    COVERAGE = auto()
    CRASHES = auto()
    HANGS = auto()
    EXECUTIONS = auto()
    PATHS = auto()
    SPEED = auto()
    STABILITY = auto()


@dataclass
class FuzzingMetrics:
    """Container for fuzzing metrics"""
    timestamp: datetime = field(default_factory=datetime.now)

    # Coverage metrics
    coverage_percent: float = 0.0
    coverage_lines: int = 0
    coverage_branches: int = 0
    coverage_functions: int = 0

    # Execution metrics
    total_executions: int = 0
    executions_per_second: float = 0.0

    # Discovery metrics
    unique_crashes: int = 0
    unique_hangs: int = 0
    total_paths: int = 0
    new_paths_last_minute: int = 0

    # Corpus metrics
    corpus_size: int = 0
    corpus_favored: int = 0

    # Performance metrics
    stability_percent: float = 100.0
    bitmap_density: float = 0.0

    # Custom metrics (fuzzer-specific)
    custom: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "timestamp": self.timestamp.isoformat(),
            "coverage_percent": self.coverage_percent,
            "coverage_lines": self.coverage_lines,
            "total_executions": self.total_executions,
            "executions_per_second": self.executions_per_second,
            "unique_crashes": self.unique_crashes,
            "unique_hangs": self.unique_hangs,
            "total_paths": self.total_paths,
            "corpus_size": self.corpus_size,
            "stability_percent": self.stability_percent,
            **self.custom,
        }


class MetricProvider(Protocol):
    """Protocol for metric providers"""

    def collect_metrics(self) -> FuzzingMetrics:
        """Collect current metrics"""
        ...

    def is_stalled(self, threshold_seconds: int = 3600) -> bool:
        """Check if fuzzing has stalled"""
        ...


class AFLMetricProvider:
    """Metric provider for AFL++"""

    def __init__(self, stats_file: Path):
        self.stats_file = stats_file
        self.last_path_time = datetime.now()
        self.last_paths = 0

    def collect_metrics(self) -> FuzzingMetrics:
        """Parse AFL++ fuzzer_stats file"""
        metrics = FuzzingMetrics()

        if not self.stats_file.exists():
            return metrics

        try:
            stats = {}
            with open(self.stats_file, 'r') as f:
                for line in f:
                    if ':' in line:
                        key, value = line.strip().split(':', 1)
                        stats[key.strip()] = value.strip()

            # Parse metrics
            metrics.coverage_percent = float(stats.get('bitmap_cvg', '0').rstrip('%'))
            metrics.total_executions = int(stats.get('execs_done', '0'))
            metrics.executions_per_second = float(stats.get('execs_per_sec', '0'))
            metrics.unique_crashes = int(stats.get('unique_crashes', '0'))
            metrics.unique_hangs = int(stats.get('unique_hangs', '0'))
            metrics.total_paths = int(stats.get('paths_total', '0'))
            metrics.corpus_size = int(stats.get('corpus_count', '0'))
            metrics.corpus_favored = int(stats.get('corpus_favored', '0'))
            metrics.stability_percent = float(stats.get('stability', '100').rstrip('%'))

            # Calculate new paths
            if self.last_paths > 0:
                new_paths = metrics.total_paths - self.last_paths
                time_diff = (datetime.now() - self.last_path_time).total_seconds()
                if time_diff > 0:
                    metrics.new_paths_last_minute = int(new_paths * 60 / time_diff)

            self.last_paths = metrics.total_paths
            self.last_path_time = datetime.now()

        except Exception as e:
            console.log(f"[yellow]Failed to parse AFL stats:[/yellow] {e}")

        return metrics

    def is_stalled(self, threshold_seconds: int = 3600) -> bool:
        """Check if no new paths found recently"""
        return (datetime.now() - self.last_path_time).total_seconds() > threshold_seconds


class LibFuzzerMetricProvider:
    """Metric provider for LibFuzzer"""

    def __init__(self, log_file: Path):
        self.log_file = log_file
        self.last_metrics = FuzzingMetrics()
        self.last_new_coverage_time = datetime.now()

    def collect_metrics(self) -> FuzzingMetrics:
        """Parse LibFuzzer output"""
        metrics = FuzzingMetrics()

        if not self.log_file.exists():
            return metrics

        try:
            # Parse last lines of log file
            with open(self.log_file, 'r') as f:
                lines = f.readlines()[-100:]  # Last 100 lines

            for line in reversed(lines):
                # Parse status line
                # Example: #12345 INITED cov: 1234 ft: 5678 corp: 42/1024Kb exec/s: 1000
                match = re.search(
                    r'#(\d+).*cov:\s*(\d+).*ft:\s*(\d+).*corp:\s*(\d+)/.*exec/s:\s*(\d+)',
                    line
                )
                if match:
                    metrics.total_executions = int(match.group(1))
                    metrics.coverage_branches = int(match.group(2))
                    metrics.total_paths = int(match.group(3))
                    metrics.corpus_size = int(match.group(4))
                    metrics.executions_per_second = float(match.group(5))
                    break

            # Check for crashes
            crash_count = sum(1 for line in lines if 'ERROR:' in line or 'SUMMARY:' in line)
            metrics.unique_crashes = crash_count

            # Update stall detection
            if metrics.coverage_branches > self.last_metrics.coverage_branches:
                self.last_new_coverage_time = datetime.now()

            self.last_metrics = metrics

        except Exception as e:
            console.log(f"[yellow]Failed to parse LibFuzzer log:[/yellow] {e}")

        return metrics

    def is_stalled(self, threshold_seconds: int = 3600) -> bool:
        """Check if no new coverage found recently"""
        return (datetime.now() - self.last_new_coverage_time).total_seconds() > threshold_seconds


class MetricsCollector:
    """
    Central metrics collection and analysis system.

    Features:
    - Multiple metric providers
    - Historical tracking
    - Prometheus export
    - Stall detection
    - Performance analysis
    """

    def __init__(
        self,
        history_size: int = 1000,
        enable_prometheus: bool = True
    ):
        self.history_size = history_size
        self.enable_prometheus = enable_prometheus

        # Metric providers by task ID
        self.providers: Dict[str, MetricProvider] = {}

        # Metrics history by task ID
        self.history: Dict[str, List[FuzzingMetrics]] = {}

        # Prometheus metrics
        if self.enable_prometheus:
            self._setup_prometheus_metrics()

    def _setup_prometheus_metrics(self):
        """Setup Prometheus metrics"""
        self.prom_coverage = Gauge(
            'fuzzflow_coverage_percent',
            'Code coverage percentage',
            ['task']
        )
        self.prom_crashes = Counter(
            'fuzzflow_crashes_total',
            'Total unique crashes found',
            ['task']
        )
        self.prom_executions = Counter(
            'fuzzflow_executions_total',
            'Total fuzzing executions',
            ['task']
        )
        self.prom_exec_rate = Gauge(
            'fuzzflow_executions_per_second',
            'Execution rate',
            ['task']
        )
        self.prom_paths = Gauge(
            'fuzzflow_paths_total',
            'Total execution paths discovered',
            ['task']
        )
        self.prom_corpus_size = Gauge(
            'fuzzflow_corpus_size',
            'Corpus size',
            ['task']
        )

    def register_provider(self, task_id: str, provider: MetricProvider) -> None:
        """Register a metric provider for a task"""
        self.providers[task_id] = provider
        self.history[task_id] = []
        console.log(f"[cyan]Registered metric provider[/cyan] for task {task_id}")

    def collect_metrics(self, task_id: str) -> Optional[FuzzingMetrics]:
        """Collect metrics for a specific task"""
        if task_id not in self.providers:
            return None

        try:
            metrics = self.providers[task_id].collect_metrics()

            # Add to history
            history = self.history[task_id]
            history.append(metrics)
            if len(history) > self.history_size:
                history.pop(0)

            # Update Prometheus
            if self.enable_prometheus:
                self._update_prometheus_metrics(task_id, metrics)

            return metrics

        except Exception as e:
            console.log(f"[red]Metrics collection error[/red] for {task_id}: {e}")
            return None

    def _update_prometheus_metrics(self, task_id: str, metrics: FuzzingMetrics) -> None:
        """Update Prometheus metrics"""
        self.prom_coverage.labels(task=task_id).set(metrics.coverage_percent)
        self.prom_crashes.labels(task=task_id)._value.set(metrics.unique_crashes)
        self.prom_executions.labels(task=task_id)._value.set(metrics.total_executions)
        self.prom_exec_rate.labels(task=task_id).set(metrics.executions_per_second)
        self.prom_paths.labels(task=task_id).set(metrics.total_paths)
        self.prom_corpus_size.labels(task=task_id).set(metrics.corpus_size)

    def is_task_stalled(self, task_id: str, threshold_seconds: int = 3600) -> bool:
        """Check if a task has stalled"""
        if task_id not in self.providers:
            return False

        return self.providers[task_id].is_stalled(threshold_seconds)

    def get_task_efficiency(self, task_id: str) -> float:
        """
        Calculate task efficiency score (0-100).

        Based on:
        - Execution speed relative to baseline
        - New path discovery rate
        - Crash discovery rate
        - Stability
        """
        history = self.history.get(task_id, [])
        if len(history) < 2:
            return 50.0  # Default middle score

        recent = history[-10:]  # Last 10 samples

        # Calculate components
        exec_score = min(100, (recent[-1].executions_per_second / 1000) * 50)

        # Path discovery rate
        if len(recent) > 1:
            path_rate = (recent[-1].total_paths - recent[0].total_paths) / len(recent)
            path_score = min(100, path_rate * 10)
        else:
            path_score = 0

        # Crash discovery (weighted heavily)
        crash_score = min(100, recent[-1].unique_crashes * 20)

        # Stability penalty
        stability_score = recent[-1].stability_percent

        # Weighted average
        efficiency = (
            exec_score * 0.2 +
            path_score * 0.3 +
            crash_score * 0.4 +
            stability_score * 0.1
        )

        return min(100, max(0, efficiency))

    def get_best_performers(self, n: int = 5) -> List[Tuple[str, float]]:
        """Get top N performing tasks by efficiency"""
        scores = []

        for task_id in self.history:
            efficiency = self.get_task_efficiency(task_id)
            scores.append((task_id, efficiency))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:n]

    def should_prioritize_task(self, task_id: str) -> bool:
        """Determine if a task should be prioritized"""
        history = self.history.get(task_id, [])
        if len(history) < 5:
            return True  # Give new tasks a chance

        recent = history[-5:]

        # Prioritize if finding new crashes
        if recent[-1].unique_crashes > recent[0].unique_crashes:
            return True

        # Prioritize if high path discovery rate
        path_rate = (recent[-1].total_paths - recent[0].total_paths) / len(recent)
        if path_rate > 10:  # More than 10 new paths per sample
            return True

        # De-prioritize if stalled
        if self.is_task_stalled(task_id, 1800):  # 30 minutes
            return False

        return True  # Default to neutral

    def export_metrics(self, task_id: str, output_file: Path) -> None:
        """Export metrics history to JSON"""
        history = self.history.get(task_id, [])

        data = {
            "task_id": task_id,
            "metrics": [m.to_dict() for m in history]
        }

        with open(output_file, 'w') as f:
            json.dump(data, f, indent=2)

        console.log(f"[green]Exported metrics[/green] for {task_id} to {output_file}")
