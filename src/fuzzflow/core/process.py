"""Process wrapper for managing fuzzing processes"""

import asyncio
import signal
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Union

import psutil
from plumbum import local, ProcessExecutionError
from plumbum.commands import BaseCommand
from rich.console import Console

from .task import FuzzTask


console = Console()


class ProcessState(Enum):
    """Process lifecycle states"""
    CREATED = auto()
    RUNNING = auto()
    PAUSED = auto()
    TERMINATED = auto()
    FAILED = auto()


@dataclass
class ProcessMetrics:
    """Real-time process metrics"""
    pid: int
    cpu_percent: float = 0.0
    memory_mb: float = 0.0
    memory_percent: float = 0.0
    num_threads: int = 0
    io_read_bytes: int = 0
    io_write_bytes: int = 0
    timestamp: datetime = field(default_factory=datetime.now)


class FuzzProcess:
    """
    Wrapper around a fuzzing process with resource monitoring and control.

    This class provides:
    - Process lifecycle management (start, pause, resume, stop)
    - Resource monitoring (CPU, memory, I/O)
    - Signal forwarding
    - Output capture and streaming
    """

    def __init__(
        self,
        task: FuzzTask,
        stdout_callback: Optional[Callable[[str], None]] = None,
        stderr_callback: Optional[Callable[[str], None]] = None,
    ):
        self.task = task
        self.state = ProcessState.CREATED
        self.process: Optional[BaseCommand] = None
        self.psutil_process: Optional[psutil.Process] = None
        self.metrics_history: list[ProcessMetrics] = []

        # Callbacks for output handling
        self.stdout_callback = stdout_callback
        self.stderr_callback = stderr_callback

        # Process info
        self.pid: Optional[int] = None
        self.start_time: Optional[datetime] = None
        self.end_time: Optional[datetime] = None
        self.exit_code: Optional[int] = None

        # Output capture
        self.stdout_buffer: list[str] = []
        self.stderr_buffer: list[str] = []

        # Monitoring
        self._monitor_task: Optional[asyncio.Task] = None
        self._monitor_interval = 1.0  # seconds

    def start(self) -> None:
        """Start the fuzzing process"""
        if self.state != ProcessState.CREATED:
            raise RuntimeError(f"Cannot start process in state {self.state}")

        try:
            # Build command using plumbum
            cmd = local[self.task.command[0]]
            if len(self.task.command) > 1:
                cmd = cmd[self.task.command[1:]]

            # Set working directory if specified
            if self.task.output_dir:
                self.task.output_dir.mkdir(parents=True, exist_ok=True)
                cmd = cmd.with_cwd(str(self.task.output_dir))

            # Set environment variables from fuzzer config
            env = self.task.fuzzer_config.get("env", {})
            if env:
                cmd = cmd.with_env(**env)

            # Start process in background
            self.process = cmd.popen()
            self.pid = self.process.pid
            self.psutil_process = psutil.Process(self.pid)

            self.state = ProcessState.RUNNING
            self.start_time = datetime.now()

            console.log(f"[green]Started process[/green] {self.task.name} (PID: {self.pid})")

        except Exception as e:
            self.state = ProcessState.FAILED
            self.task.error_message = str(e)
            console.log(f"[red]Failed to start[/red] {self.task.name}: {e}")
            raise

    async def start_monitoring(self) -> None:
        """Start async monitoring of process metrics"""
        if self.state == ProcessState.RUNNING:
            self._monitor_task = asyncio.create_task(self._monitor_loop())

    async def _monitor_loop(self) -> None:
        """Monitor process metrics in a loop"""
        while self.state == ProcessState.RUNNING:
            try:
                metrics = self.collect_metrics()
                if metrics:
                    self.metrics_history.append(metrics)

                    # Update task metrics
                    self.task.metrics.update({
                        "cpu_percent": metrics.cpu_percent,
                        "memory_mb": metrics.memory_mb,
                        "memory_percent": metrics.memory_percent,
                    })

                await asyncio.sleep(self._monitor_interval)

            except psutil.NoSuchProcess:
                # Process has terminated
                self.state = ProcessState.TERMINATED
                break
            except Exception as e:
                console.log(f"[yellow]Monitoring error[/yellow] for {self.task.name}: {e}")

    def collect_metrics(self) -> Optional[ProcessMetrics]:
        """Collect current process metrics"""
        if not self.psutil_process or not self.psutil_process.is_running():
            return None

        try:
            with self.psutil_process.oneshot():
                memory_info = self.psutil_process.memory_info()
                io_counters = self.psutil_process.io_counters()

                return ProcessMetrics(
                    pid=self.pid,
                    cpu_percent=self.psutil_process.cpu_percent(),
                    memory_mb=memory_info.rss / (1024 * 1024),
                    memory_percent=self.psutil_process.memory_percent(),
                    num_threads=self.psutil_process.num_threads(),
                    io_read_bytes=io_counters.read_bytes if io_counters else 0,
                    io_write_bytes=io_counters.write_bytes if io_counters else 0,
                )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return None

    def pause(self) -> None:
        """Pause the process using SIGSTOP"""
        if self.state != ProcessState.RUNNING:
            return

        try:
            self.psutil_process.suspend()
            self.state = ProcessState.PAUSED
            console.log(f"[yellow]Paused[/yellow] {self.task.name}")
        except Exception as e:
            console.log(f"[red]Failed to pause[/red] {self.task.name}: {e}")

    def resume(self) -> None:
        """Resume the process using SIGCONT"""
        if self.state != ProcessState.PAUSED:
            return

        try:
            self.psutil_process.resume()
            self.state = ProcessState.RUNNING
            console.log(f"[green]Resumed[/green] {self.task.name}")
        except Exception as e:
            console.log(f"[red]Failed to resume[/red] {self.task.name}: {e}")

    def terminate(self, timeout: int = 10) -> None:
        """Gracefully terminate the process"""
        if self.state not in (ProcessState.RUNNING, ProcessState.PAUSED):
            return

        try:
            # Send SIGTERM
            self.psutil_process.terminate()

            # Wait for process to terminate
            try:
                self.exit_code = self.psutil_process.wait(timeout=timeout)
            except psutil.TimeoutExpired:
                # Force kill if not terminated
                self.psutil_process.kill()
                self.exit_code = self.psutil_process.wait()

            self.state = ProcessState.TERMINATED
            self.end_time = datetime.now()

            console.log(f"[red]Terminated[/red] {self.task.name} (exit code: {self.exit_code})")

        except Exception as e:
            console.log(f"[red]Failed to terminate[/red] {self.task.name}: {e}")
            self.state = ProcessState.FAILED

    def send_signal(self, sig: signal.Signals) -> None:
        """Send a signal to the process"""
        if self.psutil_process and self.psutil_process.is_running():
            self.psutil_process.send_signal(sig)

    @property
    def is_alive(self) -> bool:
        """Check if process is still running"""
        return (self.psutil_process is not None and 
                self.psutil_process.is_running() and
                self.state in (ProcessState.RUNNING, ProcessState.PAUSED))

    @property
    def runtime(self) -> Optional[float]:
        """Get process runtime in seconds"""
        if self.start_time:
            end = self.end_time or datetime.now()
            return (end - self.start_time).total_seconds()
        return None

    @property
    def current_metrics(self) -> Optional[ProcessMetrics]:
        """Get the most recent metrics"""
        return self.metrics_history[-1] if self.metrics_history else None

    def get_children(self) -> list[psutil.Process]:
        """Get all child processes"""
        if self.psutil_process and self.psutil_process.is_running():
            try:
                return self.psutil_process.children(recursive=True)
            except psutil.NoSuchProcess:
                pass
        return []

    def get_total_memory_mb(self) -> float:
        """Get total memory usage including children"""
        total = 0.0

        if self.psutil_process and self.psutil_process.is_running():
            try:
                # Parent process
                total += self.psutil_process.memory_info().rss / (1024 * 1024)

                # Child processes
                for child in self.get_children():
                    try:
                        total += child.memory_info().rss / (1024 * 1024)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass

            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        return total
