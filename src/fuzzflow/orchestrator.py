"""Main orchestrator that coordinates all components"""

import asyncio
import signal
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set
from uuid import UUID

from rich.console import Console

from .adapters import get_adapter
from .core import (
    FuzzTask,
    ProcessManager,
    Scheduler,
    SchedulerConfig,
    SchedulingStrategy,
    PrioritySchedulingStrategy,
)
from .monitoring import (
    ResourceMonitor,
    MetricsCollector,
    ConstraintConfig,
    ConstraintEnforcer,
)


console = Console()


@dataclass
class OrchestratorConfig:
    """Configuration for the orchestrator"""
    # Core settings
    max_parallel_tasks: int = 10
    scheduling_strategy: str = "priority"  # priority, fairshare, adaptive
    scheduling_interval: float = 5.0

    # Resource limits
    memory_limit_mb: Optional[float] = None
    memory_percent_limit: float = 90.0
    cpu_limit_percent: Optional[float] = None
    per_task_memory_mb: Optional[float] = None
    per_task_cpu_percent: Optional[float] = None

    # Behavior
    enable_preemption: bool = False
    kill_on_resource_violation: bool = False
    auto_restart_failed: bool = False
    max_restart_attempts: int = 3

    # Output and logging
    output_dir: Path = field(default_factory=lambda: Path("fuzzflow_output"))
    log_level: str = "INFO"

    # Monitoring
    enable_metrics: bool = True
    enable_prometheus: bool = False
    prometheus_port: int = 9090
    metrics_interval: float = 10.0

    # Advanced
    enable_adaptive_scheduling: bool = False
    stall_detection_seconds: int = 3600
    efficiency_threshold: float = 30.0


class Orchestrator:
    """
    Main orchestrator that coordinates all Fuzzflow components.

    This is the high-level interface that:
    - Manages the lifecycle of fuzzing campaigns
    - Coordinates between scheduler, process manager, and monitors
    - Handles resource constraints and optimization
    - Provides unified API for UI and CLI
    """

    def __init__(self, config: Optional[OrchestratorConfig] = None):
        self.config = config or OrchestratorConfig()

        # Ensure output directory exists
        self.config.output_dir.mkdir(parents=True, exist_ok=True)

        # Core components
        self.process_manager = ProcessManager(
            max_processes=self.config.max_parallel_tasks
        )

        # Scheduling
        strategy = self._create_scheduling_strategy()
        scheduler_config = SchedulerConfig(
            max_concurrent_tasks=self.config.max_parallel_tasks,
            memory_limit_mb=self.config.memory_limit_mb,
            cpu_limit_percent=self.config.cpu_limit_percent,
            scheduling_interval=self.config.scheduling_interval,
            enable_preemption=self.config.enable_preemption,
        )
        self.scheduler = Scheduler(
            self.process_manager,
            strategy,
            scheduler_config
        )

        # Monitoring
        self.resource_monitor = ResourceMonitor(
            enable_prometheus=self.config.enable_prometheus
        )

        self.metrics_collector = MetricsCollector(
            enable_prometheus=self.config.enable_prometheus
        )

        # Constraints
        constraint_config = ConstraintConfig(
            max_total_memory_mb=self.config.memory_limit_mb,
            max_memory_percent=self.config.memory_percent_limit,
            per_process_memory_mb=self.config.per_task_memory_mb,
            max_total_cpu_percent=self.config.cpu_limit_percent,
            per_process_cpu_percent=self.config.per_task_cpu_percent,
            kill_on_violation=self.config.kill_on_resource_violation,
        )
        self.constraint_enforcer = ConstraintEnforcer(
            constraint_config.build_constraints(),
            kill_on_violation=self.config.kill_on_resource_violation
        )

        # State tracking
        self.start_time: Optional[datetime] = None
        self.end_time: Optional[datetime] = None
        self._monitoring_task: Optional[asyncio.Task] = None
        self._adaptation_task: Optional[asyncio.Task] = None

        # Task tracking for restart
        self.task_restart_counts: Dict[UUID, int] = {}

        # Setup callbacks
        self._setup_callbacks()

        # Fuzzer adapters cache
        self._adapters: Dict[str, Any] = {}

    def _create_scheduling_strategy(self) -> SchedulingStrategy:
        """Create scheduling strategy based on config"""
        if self.config.scheduling_strategy == "priority":
            return PrioritySchedulingStrategy(
                enable_preemption=self.config.enable_preemption
            )
        # Add more strategies as implemented
        return PrioritySchedulingStrategy()

    def _setup_callbacks(self):
        """Setup component callbacks"""
        # Scheduler callbacks
        self.scheduler.on_task_complete = self._on_task_complete
        self.scheduler.on_task_fail = self._on_task_fail

        # Resource monitor callbacks
        self.resource_monitor.add_alert_callback(self._on_resource_alert)

    def submit_task(self, task: FuzzTask) -> None:
        """Submit a task for execution"""
        # Prepare task
        self._prepare_task(task)

        # Submit to scheduler
        self.scheduler.submit_task(task)

        console.log(f"[cyan]Submitted task[/cyan] {task.name}")

    def submit_tasks(self, tasks: List[FuzzTask]) -> None:
        """Submit multiple tasks"""
        for task in tasks:
            self.submit_task(task)

    def _prepare_task(self, task: FuzzTask) -> None:
        """Prepare task for execution"""
        # Create task output directory
        task_dir = self.config.output_dir / task.name
        task_dir.mkdir(exist_ok=True)

        # Set output directory if not specified
        if not task.output_dir:
            task.output_dir = task_dir

        # Get fuzzer adapter
        adapter = self._get_adapter(task.fuzzer_type)

        # Validate setup
        binary_path = Path(task.command[0])
        is_valid, error = adapter.validate_setup(binary_path, task_dir)

        if not is_valid:
            raise ValueError(f"Invalid setup for {task.name}: {error}")

        # Prepare corpus if needed
        if task.input_dir:
            corpus_dir = task_dir / "corpus"
            adapter.prepare_corpus(task.input_dir, corpus_dir, task)
            task.corpus_dir = corpus_dir

        # Update command with adapter
        full_command = adapter.build_command(task, binary_path, task_dir)
        task.command = full_command

        # Set environment
        task.fuzzer_config["env"] = adapter.get_environment(task)

        # Register metric provider
        provider = adapter.get_metric_provider(task_dir, task)
        self.metrics_collector.register_provider(str(task.id), provider)

    def _get_adapter(self, fuzzer_type: str):
        """Get or create fuzzer adapter"""
        if fuzzer_type not in self._adapters:
            self._adapters[fuzzer_type] = get_adapter(fuzzer_type)
        return self._adapters[fuzzer_type]

    async def start(self) -> None:
        """Start the orchestrator"""
        console.log("[green]Starting Fuzzflow orchestrator...[/green]")

        self.start_time = datetime.now()

        # Start components
        await self.resource_monitor.start()
        await self.scheduler.start()

        # Start monitoring
        self._monitoring_task = asyncio.create_task(self._monitoring_loop())

        # Start adaptation if enabled
        if self.config.enable_adaptive_scheduling:
            self._adaptation_task = asyncio.create_task(self._adaptation_loop())

        console.log("[green]Orchestrator started[/green]")

    async def stop(self) -> None:
        """Stop the orchestrator"""
        console.log("[yellow]Stopping orchestrator...[/yellow]")

        self.end_time = datetime.now()

        # Stop components
        await self.scheduler.stop()
        await self.resource_monitor.stop()

        # Cancel tasks
        if self._monitoring_task:
            self._monitoring_task.cancel()
        if self._adaptation_task:
            self._adaptation_task.cancel()

        # Shutdown process manager
        await self.process_manager.shutdown()

        console.log("[green]Orchestrator stopped[/green]")

    async def _monitoring_loop(self) -> None:
        """Main monitoring loop"""
        while True:
            try:
                # Monitor resources
                await self._check_resources()

                # Collect metrics
                await self._collect_metrics()

                # Check for stalled tasks
                if self.config.enable_adaptive_scheduling:
                    await self._check_stalled_tasks()

                await asyncio.sleep(self.config.metrics_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                console.log(f"[red]Monitoring error:[/red] {e}")

    async def _check_resources(self) -> None:
        """Check resource constraints"""
        # Check each running process
        for process in self.process_manager.get_running_processes():
            self.constraint_enforcer.check_process(process)

    async def _collect_metrics(self) -> None:
        """Collect metrics from all tasks"""
        for task_id, process in self.process_manager.processes.items():
            if process.is_alive:
                self.metrics_collector.collect_metrics(str(task_id))

    async def _check_stalled_tasks(self) -> None:
        """Check for stalled tasks and handle them"""
        for task_id, process in list(self.process_manager.processes.items()):
            if process.is_alive:
                str_id = str(task_id)

                # Check if stalled
                if self.metrics_collector.is_task_stalled(
                    str_id,
                    self.config.stall_detection_seconds
                ):
                    console.log(
                        f"[yellow]Task {process.task.name} appears stalled[/yellow]"
                    )

                    # Check efficiency
                    efficiency = self.metrics_collector.get_task_efficiency(str_id)
                    if efficiency < self.config.efficiency_threshold:
                        console.log(
                            f"[yellow]Task {process.task.name} has low efficiency "
                            f"({efficiency:.1f}%)[/yellow]"
                        )

                        # Consider stopping the task
                        # This is where adaptive scheduling logic would go

    async def _adaptation_loop(self) -> None:
        """Adaptive scheduling loop"""
        while True:
            try:
                # Get best performers
                best = self.metrics_collector.get_best_performers(5)

                # Adjust priorities based on performance
                for task_id, efficiency in best:
                    # This is where we'd implement adaptive priority adjustment
                    pass

                await asyncio.sleep(60)  # Adapt every minute

            except asyncio.CancelledError:
                break
            except Exception as e:
                console.log(f"[red]Adaptation error:[/red] {e}")

    def _on_task_complete(self, task: FuzzTask) -> None:
        """Handle task completion"""
        console.log(f"[green]Task completed:[/green] {task.name}")

        # Process results
        adapter = self._get_adapter(task.fuzzer_type)
        results = adapter.post_process_results(task.output_dir, task)

        # Log results
        console.log(f"  Crashes found: {len(results.get('crashes', []))}")
        console.log(f"  Final corpus size: {results.get('corpus_size', 0)}")

    def _on_task_fail(self, task: FuzzTask) -> None:
        """Handle task failure"""
        console.log(f"[red]Task failed:[/red] {task.name}")

        # Check if we should restart
        if self.config.auto_restart_failed:
            restart_count = self.task_restart_counts.get(task.id, 0)

            if restart_count < self.config.max_restart_attempts:
                console.log(
                    f"[yellow]Restarting task[/yellow] {task.name} "
                    f"(attempt {restart_count + 1}/{self.config.max_restart_attempts})"
                )

                # Reset task status
                task.status = TaskStatus.PENDING
                task.error_message = None

                # Increment restart count
                self.task_restart_counts[task.id] = restart_count + 1

                # Resubmit
                self.scheduler.submit_task(task)

    def _on_resource_alert(self, resource_type, value: float) -> None:
        """Handle resource alerts"""
        console.log(
            f"[red]Resource alert:[/red] {resource_type.name} at {value:.1f}%"
        )

        # Could implement automatic task pausing/stopping here

    def pause_all(self) -> int:
        """Pause all running tasks"""
        count = 0
        for task_id in list(self.process_manager.running_tasks.keys()):
            if self.process_manager.pause_task(task_id):
                count += 1
        return count

    def resume_all(self) -> int:
        """Resume all paused tasks"""
        count = 0
        for process in self.process_manager.get_paused_processes():
            if self.process_manager.resume_task(process.task.id):
                count += 1
        return count

    async def stop_all(self) -> int:
        """Stop all running tasks"""
        count = 0
        for task_id in list(self.process_manager.running_tasks.keys()):
            if self.process_manager.stop_task(task_id):
                count += 1
        return count

    def has_pending_tasks(self) -> bool:
        """Check if there are pending or running tasks"""
        return (
            len(self.scheduler.pending_tasks) > 0 or
            len(self.scheduler.running_tasks) > 0
        )

    def get_statistics(self) -> dict:
        """Get orchestrator statistics"""
        stats = {
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "runtime": self.runtime,
            "total_tasks": (
                len(self.scheduler.pending_tasks) +
                len(self.scheduler.running_tasks) +
                len(self.scheduler.completed_tasks)
            ),
            "pending_tasks": len(self.scheduler.pending_tasks),
            "running_tasks": len(self.scheduler.running_tasks),
            "completed_tasks": len(self.scheduler.completed_tasks),
            "successful_tasks": self.scheduler.tasks_completed,
            "failed_tasks": self.scheduler.tasks_failed,
        }

        # Add resource stats
        if self.resource_monitor:
            current = self.resource_monitor.get_current_usage()
            if current:
                stats["memory_usage_mb"] = current.memory_used_mb
                stats["memory_percent"] = current.memory_percent
                stats["cpu_percent"] = current.cpu_percent

        return stats

    @property
    def runtime(self) -> Optional[float]:
        """Get orchestrator runtime in seconds"""
        if self.start_time:
            end = self.end_time or datetime.now()
            return (end - self.start_time).total_seconds()
        return None
