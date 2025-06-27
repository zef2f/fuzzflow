"""System resource monitoring"""

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto
from typing import Callable, Dict, List, Optional, Tuple

import psutil
from prometheus_client import Gauge, Counter, Histogram
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table


console = Console()


class ResourceType(Enum):
    """Types of system resources"""
    MEMORY = auto()
    CPU = auto()
    DISK = auto()
    NETWORK = auto()
    GPU = auto()  # For future GPU fuzzing support


@dataclass
class ResourceUsage:
    """Resource usage snapshot"""
    timestamp: datetime
    memory_total_mb: float
    memory_used_mb: float
    memory_available_mb: float
    memory_percent: float
    cpu_percent: float
    cpu_per_core: List[float]
    disk_read_bytes: int
    disk_write_bytes: int
    network_sent_bytes: int
    network_recv_bytes: int

    @classmethod
    def capture(cls) -> "ResourceUsage":
        """Capture current system resources"""
        mem = psutil.virtual_memory()
        cpu_per_core = psutil.cpu_percent(percpu=True)
        disk_io = psutil.disk_io_counters()
        net_io = psutil.net_io_counters()

        return cls(
            timestamp=datetime.now(),
            memory_total_mb=mem.total / (1024 * 1024),
            memory_used_mb=mem.used / (1024 * 1024),
            memory_available_mb=mem.available / (1024 * 1024),
            memory_percent=mem.percent,
            cpu_percent=psutil.cpu_percent(),
            cpu_per_core=cpu_per_core,
            disk_read_bytes=disk_io.read_bytes if disk_io else 0,
            disk_write_bytes=disk_io.write_bytes if disk_io else 0,
            network_sent_bytes=net_io.bytes_sent if net_io else 0,
            network_recv_bytes=net_io.bytes_recv if net_io else 0,
        )


class ResourceMonitor:
    """
    Advanced resource monitoring with alerts and predictions.

    Features:
    - Real-time resource tracking
    - Historical data with sliding window
    - Resource usage predictions
    - Alert thresholds
    - Prometheus metrics export
    """

    def __init__(
        self,
        history_size: int = 300,  # 5 minutes at 1Hz
        sample_interval: float = 1.0,
        enable_prometheus: bool = True
    ):
        self.history_size = history_size
        self.sample_interval = sample_interval
        self.enable_prometheus = enable_prometheus

        # Resource history
        self.history: List[ResourceUsage] = []
        self.start_time = datetime.now()

        # Monitoring state
        self._monitor_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()

        # Alert thresholds
        self.thresholds: Dict[ResourceType, float] = {
            ResourceType.MEMORY: 90.0,  # percent
            ResourceType.CPU: 95.0,     # percent
            ResourceType.DISK: 95.0,    # percent
        }

        # Alert callbacks
        self.alert_callbacks: List[Callable[[ResourceType, float], None]] = []

        # Prometheus metrics
        if self.enable_prometheus:
            self._setup_prometheus_metrics()

    def _setup_prometheus_metrics(self):
        """Setup Prometheus metrics"""
        self.prom_memory_usage = Gauge(
            'fuzzflow_memory_usage_mb',
            'Memory usage in MB'
        )
        self.prom_memory_percent = Gauge(
            'fuzzflow_memory_percent',
            'Memory usage percentage'
        )
        self.prom_cpu_percent = Gauge(
            'fuzzflow_cpu_percent',
            'CPU usage percentage'
        )
        self.prom_cpu_per_core = Gauge(
            'fuzzflow_cpu_core_percent',
            'CPU usage per core',
            ['core']
        )
        self.prom_disk_read_rate = Gauge(
            'fuzzflow_disk_read_mbps',
            'Disk read rate in MB/s'
        )
        self.prom_disk_write_rate = Gauge(
            'fuzzflow_disk_write_mbps',
            'Disk write rate in MB/s'
        )
        self.prom_network_sent_rate = Gauge(
            'fuzzflow_network_sent_mbps',
            'Network sent rate in MB/s'
        )
        self.prom_network_recv_rate = Gauge(
            'fuzzflow_network_recv_mbps',
            'Network receive rate in MB/s'
        )

    async def start(self) -> None:
        """Start resource monitoring"""
        console.log("[green]Starting resource monitor...[/green]")
        self._monitor_task = asyncio.create_task(self._monitor_loop())

    async def stop(self) -> None:
        """Stop resource monitoring"""
        console.log("[yellow]Stopping resource monitor...[/yellow]")
        self._shutdown_event.set()

        if self._monitor_task:
            await self._monitor_task

    async def _monitor_loop(self) -> None:
        """Main monitoring loop"""
        last_usage = None

        while not self._shutdown_event.is_set():
            try:
                # Capture resources
                usage = ResourceUsage.capture()
                self._add_to_history(usage)

                # Update Prometheus metrics
                if self.enable_prometheus:
                    self._update_prometheus_metrics(usage, last_usage)

                # Check thresholds
                self._check_thresholds(usage)

                last_usage = usage
                await asyncio.sleep(self.sample_interval)

            except Exception as e:
                console.log(f"[red]Monitor error:[/red] {e}")

    def _add_to_history(self, usage: ResourceUsage) -> None:
        """Add usage to history with size limit"""
        self.history.append(usage)
        if len(self.history) > self.history_size:
            self.history.pop(0)

    def _update_prometheus_metrics(
        self,
        usage: ResourceUsage,
        last_usage: Optional[ResourceUsage]
    ) -> None:
        """Update Prometheus metrics"""
        # Memory metrics
        self.prom_memory_usage.set(usage.memory_used_mb)
        self.prom_memory_percent.set(usage.memory_percent)

        # CPU metrics
        self.prom_cpu_percent.set(usage.cpu_percent)
        for i, percent in enumerate(usage.cpu_per_core):
            self.prom_cpu_per_core.labels(core=str(i)).set(percent)

        # Calculate rates if we have previous data
        if last_usage:
            time_delta = (usage.timestamp - last_usage.timestamp).total_seconds()
            if time_delta > 0:
                # Disk rates (MB/s)
                disk_read_rate = (usage.disk_read_bytes - last_usage.disk_read_bytes) / (1024 * 1024 * time_delta)
                disk_write_rate = (usage.disk_write_bytes - last_usage.disk_write_bytes) / (1024 * 1024 * time_delta)
                self.prom_disk_read_rate.set(max(0, disk_read_rate))
                self.prom_disk_write_rate.set(max(0, disk_write_rate))

                # Network rates (MB/s)
                net_sent_rate = (usage.network_sent_bytes - last_usage.network_sent_bytes) / (1024 * 1024 * time_delta)
                net_recv_rate = (usage.network_recv_bytes - last_usage.network_recv_bytes) / (1024 * 1024 * time_delta)
                self.prom_network_sent_rate.set(max(0, net_sent_rate))
                self.prom_network_recv_rate.set(max(0, net_recv_rate))

    def _check_thresholds(self, usage: ResourceUsage) -> None:
        """Check resource usage against thresholds"""
        # Memory threshold
        if usage.memory_percent > self.thresholds[ResourceType.MEMORY]:
            self._trigger_alert(ResourceType.MEMORY, usage.memory_percent)

        # CPU threshold
        if usage.cpu_percent > self.thresholds[ResourceType.CPU]:
            self._trigger_alert(ResourceType.CPU, usage.cpu_percent)

    def _trigger_alert(self, resource_type: ResourceType, value: float) -> None:
        """Trigger resource alert"""
        console.log(
            f"[red]ALERT:[/red] {resource_type.name} usage at {value:.1f}% "
            f"(threshold: {self.thresholds[resource_type]:.1f}%)"
        )

        for callback in self.alert_callbacks:
            try:
                callback(resource_type, value)
            except Exception as e:
                console.log(f"[red]Alert callback error:[/red] {e}")

    def add_alert_callback(self, callback: Callable[[ResourceType, float], None]) -> None:
        """Add alert callback"""
        self.alert_callbacks.append(callback)

    def set_threshold(self, resource_type: ResourceType, threshold: float) -> None:
        """Set alert threshold for resource type"""
        self.thresholds[resource_type] = threshold

    def get_current_usage(self) -> Optional[ResourceUsage]:
        """Get most recent resource usage"""
        return self.history[-1] if self.history else None

    def get_average_usage(self, seconds: int = 60) -> Optional[Dict[str, float]]:
        """Get average usage over time period"""
        if not self.history:
            return None

        cutoff_time = datetime.now() - timedelta(seconds=seconds)
        recent = [u for u in self.history if u.timestamp >= cutoff_time]

        if not recent:
            return None

        return {
            "memory_mb": sum(u.memory_used_mb for u in recent) / len(recent),
            "memory_percent": sum(u.memory_percent for u in recent) / len(recent),
            "cpu_percent": sum(u.cpu_percent for u in recent) / len(recent),
        }

    def predict_memory_exhaustion(self) -> Optional[float]:
        """
        Predict time until memory exhaustion based on current trend.
        Returns: Seconds until exhaustion, or None if decreasing/stable
        """
        if len(self.history) < 10:
            return None

        # Simple linear regression on recent memory usage
        recent = self.history[-30:]  # Last 30 seconds
        if len(recent) < 2:
            return None

        # Calculate slope
        x_vals = [(u.timestamp - recent[0].timestamp).total_seconds() for u in recent]
        y_vals = [u.memory_used_mb for u in recent]

        n = len(x_vals)
        if n < 2:
            return None

        # Linear regression
        x_mean = sum(x_vals) / n
        y_mean = sum(y_vals) / n

        numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_vals, y_vals))
        denominator = sum((x - x_mean) ** 2 for x in x_vals)

        if denominator == 0:
            return None

        slope = numerator / denominator  # MB per second

        if slope <= 0:
            return None  # Memory usage is decreasing or stable

        # Calculate time to exhaustion
        current = recent[-1]
        remaining_mb = current.memory_total_mb - current.memory_used_mb
        seconds_to_exhaustion = remaining_mb / slope

        # Only return if exhaustion is predicted within reasonable time
        if 0 < seconds_to_exhaustion < 3600:  # Within 1 hour
            return seconds_to_exhaustion

        return None

    def get_resource_summary(self) -> str:
        """Get formatted resource summary"""
        current = self.get_current_usage()
        if not current:
            return "No resource data available"

        return (
            f"Memory: {current.memory_used_mb:.1f}/{current.memory_total_mb:.1f} MB "
            f"({current.memory_percent:.1f}%) | "
            f"CPU: {current.cpu_percent:.1f}%"
        )

    def create_status_table(self) -> Table:
        """Create rich table with resource status"""
        table = Table(title="System Resources")
        table.add_column("Resource", style="cyan")
        table.add_column("Current", style="green")
        table.add_column("Average (1m)", style="yellow")
        table.add_column("Peak (5m)", style="red")

        current = self.get_current_usage()
        avg = self.get_average_usage(60)

        if current:
            # Memory row
            table.add_row(
                "Memory",
                f"{current.memory_used_mb:.1f} MB ({current.memory_percent:.1f}%)",
                f"{avg['memory_mb']:.1f} MB" if avg else "-",
                f"{max(u.memory_used_mb for u in self.history):.1f} MB" if self.history else "-"
            )

            # CPU row
            table.add_row(
                "CPU",
                f"{current.cpu_percent:.1f}%",
                f"{avg['cpu_percent']:.1f}%" if avg else "-",
                f"{max(u.cpu_percent for u in self.history):.1f}%" if self.history else "-"
            )

        return table
