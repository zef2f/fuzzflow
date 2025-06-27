"""Task scheduler with priority and resource-aware scheduling"""

import asyncio
import heapq
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional, Set, Tuple
from uuid import UUID

from rich.console import Console

from .manager import ProcessManager
from .task import FuzzTask, TaskPriority, TaskStatus


console = Console()


class SchedulingStrategy(ABC):
    """Abstract base class for scheduling strategies"""

    @abstractmethod
    def select_next_task(
        self, 
        pending_tasks: List[FuzzTask],
        running_tasks: List[FuzzTask],
        available_memory_mb: float,
        available_cores: int
    ) -> Optional[FuzzTask]:
        """Select the next task to run"""
        pass

    @abstractmethod
    def should_preempt(
        self,
        running_task: FuzzTask,
        pending_task: FuzzTask
    ) -> bool:
        """Determine if a running task should be preempted"""
        pass


class PrioritySchedulingStrategy(SchedulingStrategy):
    """Priority-based scheduling with optional preemption"""

    def __init__(self, enable_preemption: bool = False):
        self.enable_preemption = enable_preemption

    def select_next_task(
        self,
        pending_tasks: List[FuzzTask],
        running_tasks: List[FuzzTask],
        available_memory_mb: float,
        available_cores: int
    ) -> Optional[FuzzTask]:
        """Select highest priority task that fits in available resources"""
        # Sort by priority (descending) and creation time (ascending)
        candidates = sorted(
            pending_tasks,
            key=lambda t: (-t.priority.value, t.created_at)
        )

        for task in candidates:
            if task.can_run_with_resources(available_memory_mb, available_cores):
                return task

        return None

    def should_preempt(
        self,
        running_task: FuzzTask,
        pending_task: FuzzTask
    ) -> bool:
        """Preempt if pending task has significantly higher priority"""
        if not self.enable_preemption:
            return False

        # Only preempt if priority difference is significant
        priority_diff = pending_task.priority.value - running_task.priority.value
        return priority_diff >= 25  # At least one priority level higher


class FairShareSchedulingStrategy(SchedulingStrategy):
    """Fair share scheduling based on tag-based resource allocation"""

    def __init__(self):
        self.tag_runtime: Dict[str, float] = {}
        self.tag_shares: Dict[str, float] = {}  # Tag -> share percentage

    def set_shares(self, shares: Dict[str, float]) -> None:
        """Set resource share percentages for tags"""
        total = sum(shares.values())
        if total > 0:
            self.tag_shares = {tag: share/total for tag, share in shares.items()}

    def select_next_task(
        self,
        pending_tasks: List[FuzzTask],
        running_tasks: List[FuzzTask],
        available_memory_mb: float,
        available_cores: int
    ) -> Optional[FuzzTask]:
        """Select task from tag with lowest resource usage ratio"""
        # Calculate current usage ratios
        usage_ratios = {}
        for tag, target_share in self.tag_shares.items():
            current_usage = self.tag_runtime.get(tag, 0)
            total_usage = sum(self.tag_runtime.values())
            current_share = current_usage / total_usage if total_usage > 0 else 0
            usage_ratios[tag] = current_share / target_share if target_share > 0 else float('inf')

        # Sort tasks by their tag's usage ratio
        candidates = []
        for task in pending_tasks:
            if task.can_run_with_resources(available_memory_mb, available_cores):
                # Find the task's tag with lowest usage ratio
                min_ratio = float('inf')
                for tag in task.tags:
                    if tag in usage_ratios:
                        min_ratio = min(min_ratio, usage_ratios[tag])
                candidates.append((min_ratio, task))

        if candidates:
            candidates.sort(key=lambda x: x[0])
            return candidates[0][1]

        return None

    def should_preempt(self, running_task: FuzzTask, pending_task: FuzzTask) -> bool:
        """No preemption in fair share scheduling"""
        return False

    def update_runtime(self, task: FuzzTask, runtime: float) -> None:
        """Update runtime tracking for task's tags"""
        for tag in task.tags:
            self.tag_runtime[tag] = self.tag_runtime.get(tag, 0) + runtime


@dataclass
class SchedulerConfig:
    """Scheduler configuration"""
    max_concurrent_tasks: int = 10
    memory_limit_mb: Optional[float] = None
    cpu_limit_percent: Optional[float] = None
    scheduling_interval: float = 5.0  # seconds
    enable_preemption: bool = False
    cleanup_interval: float = 60.0  # seconds


class Scheduler:
    """
    Task scheduler that manages task execution with resource constraints.

    Features:
    - Multiple scheduling strategies
    - Resource-aware scheduling
    - Task dependencies
    - Automatic cleanup
    - Metrics collection
    """

    def __init__(
        self,
        process_manager: ProcessManager,
        strategy: Optional[SchedulingStrategy] = None,
        config: Optional[SchedulerConfig] = None
    ):
        self.process_manager = process_manager
        self.strategy = strategy or PrioritySchedulingStrategy()
        self.config = config or SchedulerConfig()

        # Task management
        self.pending_tasks: List[FuzzTask] = []
        self.running_tasks: Dict[UUID, FuzzTask] = {}
        self.completed_tasks: List[FuzzTask] = []
        self.task_dependencies: Dict[UUID, Set[UUID]] = {}

        # Scheduling state
        self._scheduler_task: Optional[asyncio.Task] = None
        self._cleanup_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()

        # Metrics
        self.tasks_scheduled = 0
        self.tasks_completed = 0
        self.tasks_failed = 0

        # Callbacks
        self.on_task_complete: Optional[Callable[[FuzzTask], None]] = None
        self.on_task_fail: Optional[Callable[[FuzzTask], None]] = None

    def submit_task(self, task: FuzzTask) -> None:
        """Submit a task for scheduling"""
        # Store dependencies
        if task.dependencies:
            self.task_dependencies[task.id] = set(task.dependencies)

        self.pending_tasks.append(task)
        console.log(f"[cyan]Submitted task[/cyan] {task.name} with priority {task.priority.name}")

    def submit_tasks(self, tasks: List[FuzzTask]) -> None:
        """Submit multiple tasks"""
        for task in tasks:
            self.submit_task(task)

    async def start(self) -> None:
        """Start the scheduler"""
        console.log("[green]Starting scheduler...[/green]")

        self._scheduler_task = asyncio.create_task(self._scheduler_loop())
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def stop(self) -> None:
        """Stop the scheduler"""
        console.log("[yellow]Stopping scheduler...[/yellow]")

        self._shutdown_event.set()

        if self._scheduler_task:
            await self._scheduler_task
        if self._cleanup_task:
            await self._cleanup_task

    async def _scheduler_loop(self) -> None:
        """Main scheduling loop"""
        while not self._shutdown_event.is_set():
            try:
                await self._schedule_tasks()
                await asyncio.sleep(self.config.scheduling_interval)
            except Exception as e:
                console.log(f"[red]Scheduler error:[/red] {e}")

    async def _schedule_tasks(self) -> None:
        """Schedule pending tasks based on resources and strategy"""
        # Update task states
        await self._update_task_states()

        # Check resource availability
        available_memory, available_cores = await self._get_available_resources()

        # Get tasks ready to run
        ready_tasks = self._get_ready_tasks()
        if not ready_tasks:
            return

        # Schedule tasks
        while ready_tasks and len(self.running_tasks) < self.config.max_concurrent_tasks:
            # Select next task
            task = self.strategy.select_next_task(
                ready_tasks,
                list(self.running_tasks.values()),
                available_memory,
                available_cores
            )

            if not task:
                break  # No suitable task found

            # Try to start the task
            success = await self.process_manager.start_task(task)
            if success:
                self.running_tasks[task.id] = task
                ready_tasks.remove(task)
                self.pending_tasks.remove(task)
                self.tasks_scheduled += 1

                # Update available resources
                if task.memory_limit_mb:
                    available_memory -= task.memory_limit_mb
                if task.cpu_cores:
                    available_cores -= task.cpu_cores
            else:
                # Failed to start, move to next task
                ready_tasks.remove(task)

    async def _update_task_states(self) -> None:
        """Update task states based on process states"""
        completed = []

        for task_id, task in list(self.running_tasks.items()):
            process = self.process_manager.get_process_by_task(task_id)

            if not process or not process.is_alive:
                # Task completed or failed
                completed.append(task_id)

                if process and process.exit_code == 0:
                    task.update_status(TaskStatus.COMPLETED)
                    self.tasks_completed += 1
                    if self.on_task_complete:
                        self.on_task_complete(task)
                else:
                    task.update_status(TaskStatus.FAILED)
                    self.tasks_failed += 1
                    if self.on_task_fail:
                        self.on_task_fail(task)

                self.completed_tasks.append(task)

        # Remove completed tasks
        for task_id in completed:
            del self.running_tasks[task_id]

            # Update dependencies
            for dep_id, deps in list(self.task_dependencies.items()):
                if task_id in deps:
                    deps.remove(task_id)
                    if not deps:
                        del self.task_dependencies[dep_id]

    def _get_ready_tasks(self) -> List[FuzzTask]:
        """Get tasks that are ready to run"""
        ready = []

        for task in self.pending_tasks:
            # Check if dependencies are satisfied
            deps = self.task_dependencies.get(task.id, set())
            if not deps and task.is_ready():
                ready.append(task)

        return ready

    async def _get_available_resources(self) -> Tuple[float, int]:
        """Get available system resources"""
        # Get current usage
        memory_used, cpu_used = await self.process_manager.monitor_resources()

        # Get system resources
        import psutil
        total_memory = psutil.virtual_memory().total / (1024 * 1024)
        total_cores = psutil.cpu_count()

        # Apply limits if configured
        if self.config.memory_limit_mb:
            total_memory = min(total_memory, self.config.memory_limit_mb)

        if self.config.cpu_limit_percent:
            total_cores = int(total_cores * self.config.cpu_limit_percent / 100)

        # Calculate available
        available_memory = total_memory - memory_used
        available_cores = total_cores  # Simplified for now

        return available_memory, available_cores

    async def _cleanup_loop(self) -> None:
        """Periodic cleanup of completed tasks"""
        while not self._shutdown_event.is_set():
            try:
                await self.process_manager.cleanup_terminated()

                # Limit completed tasks list size
                if len(self.completed_tasks) > 1000:
                    self.completed_tasks = self.completed_tasks[-500:]

                await asyncio.sleep(self.config.cleanup_interval)
            except Exception as e:
                console.log(f"[red]Cleanup error:[/red] {e}")

    def get_statistics(self) -> Dict[str, any]:
        """Get scheduler statistics"""
        return {
            "pending_tasks": len(self.pending_tasks),
            "running_tasks": len(self.running_tasks),
            "completed_tasks": len(self.completed_tasks),
            "tasks_scheduled": self.tasks_scheduled,
            "tasks_completed": self.tasks_completed,
            "tasks_failed": self.tasks_failed,
            "strategy": type(self.strategy).__name__,
        }

    def print_status(self) -> None:
        """Print scheduler status"""
        stats = self.get_statistics()

        console.print("\n[bold]Scheduler Status[/bold]")
        console.print(f"Strategy: {stats['strategy']}")
        console.print(f"Pending: {stats['pending_tasks']}")
        console.print(f"Running: {stats['running_tasks']}")
        console.print(f"Completed: {stats['completed_tasks']}")
        console.print(f"Success rate: {stats['tasks_completed']}/{stats['tasks_scheduled']}")
