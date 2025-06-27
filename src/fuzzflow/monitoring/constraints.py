"""Resource constraints and enforcement"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional

import psutil
from rich.console import Console

from ..core.process import FuzzProcess
from ..core.task import FuzzTask


console = Console()


class ResourceConstraint(ABC):
    """Abstract base class for resource constraints"""

    @abstractmethod
    def check(self, process: FuzzProcess) -> bool:
        """Check if process violates constraint"""
        pass

    @abstractmethod
    def get_violation_message(self, process: FuzzProcess) -> str:
        """Get violation message for logging"""
        pass

    @abstractmethod
    def can_start_task(self, task: FuzzTask, current_usage: dict) -> bool:
        """Check if task can be started given current usage"""
        pass


class MemoryConstraint(ResourceConstraint):
    """Memory usage constraint"""

    def __init__(
        self,
        max_memory_mb: float,
        per_process_limit_mb: Optional[float] = None,
        include_children: bool = True
    ):
        self.max_memory_mb = max_memory_mb
        self.per_process_limit_mb = per_process_limit_mb
        self.include_children = include_children

    def check(self, process: FuzzProcess) -> bool:
        """Check if process exceeds memory limit"""
        if not process.is_alive:
            return False

        memory_mb = process.get_total_memory_mb() if self.include_children else 0

        if not self.include_children and process.current_metrics:
            memory_mb = process.current_metrics.memory_mb

        if self.per_process_limit_mb and memory_mb > self.per_process_limit_mb:
            return True

        return False

    def get_violation_message(self, process: FuzzProcess) -> str:
        """Get memory violation message"""
        memory_mb = process.get_total_memory_mb()
        return (
            f"Process {process.task.name} exceeded memory limit: "
            f"{memory_mb:.1f} MB > {self.per_process_limit_mb:.1f} MB"
        )

    def can_start_task(self, task: FuzzTask, current_usage: dict) -> bool:
        """Check if task can start within memory constraints"""
        current_memory = current_usage.get('memory_mb', 0)
        required_memory = task.memory_limit_mb or 512  # Default 512 MB

        return (current_memory + required_memory) <= self.max_memory_mb


class CPUConstraint(ResourceConstraint):
    """CPU usage constraint"""

    def __init__(
        self,
        max_cpu_percent: float,
        per_process_limit_percent: Optional[float] = None
    ):
        self.max_cpu_percent = max_cpu_percent
        self.per_process_limit_percent = per_process_limit_percent

    def check(self, process: FuzzProcess) -> bool:
        """Check if process exceeds CPU limit"""
        if not process.is_alive or not process.current_metrics:
            return False

        cpu_percent = process.current_metrics.cpu_percent

        if self.per_process_limit_percent and cpu_percent > self.per_process_limit_percent:
            return True

        return False

    def get_violation_message(self, process: FuzzProcess) -> str:
        """Get CPU violation message"""
        cpu_percent = process.current_metrics.cpu_percent if process.current_metrics else 0
        return (
            f"Process {process.task.name} exceeded CPU limit: "
            f"{cpu_percent:.1f}% > {self.per_process_limit_percent:.1f}%"
        )

    def can_start_task(self, task: FuzzTask, current_usage: dict) -> bool:
        """Check if task can start within CPU constraints"""
        current_cpu = current_usage.get('cpu_percent', 0)
        required_cores = task.cpu_cores or 1
        cpu_per_core = 100.0 / psutil.cpu_count()
        required_cpu = required_cores * cpu_per_core

        return (current_cpu + required_cpu) <= self.max_cpu_percent


class TimeConstraint(ResourceConstraint):
    """Time-based constraint"""

    def __init__(self, max_runtime_seconds: int):
        self.max_runtime_seconds = max_runtime_seconds

    def check(self, process: FuzzProcess) -> bool:
        """Check if process exceeded time limit"""
        if not process.is_alive or not process.runtime:
            return False

        return process.runtime > self.max_runtime_seconds

    def get_violation_message(self, process: FuzzProcess) -> str:
        """Get time violation message"""
        runtime = process.runtime or 0
        return (
            f"Process {process.task.name} exceeded time limit: "
            f"{runtime:.0f}s > {self.max_runtime_seconds}s"
        )

    def can_start_task(self, task: FuzzTask, current_usage: dict) -> bool:
        """Time constraints don't affect starting"""
        return True


class CompositeConstraint(ResourceConstraint):
    """Composite constraint combining multiple constraints"""

    def __init__(self, constraints: List[ResourceConstraint]):
        self.constraints = constraints

    def check(self, process: FuzzProcess) -> bool:
        """Check if any constraint is violated"""
        return any(c.check(process) for c in self.constraints)

    def get_violation_message(self, process: FuzzProcess) -> str:
        """Get all violation messages"""
        messages = []
        for constraint in self.constraints:
            if constraint.check(process):
                messages.append(constraint.get_violation_message(process))
        return " | ".join(messages)

    def can_start_task(self, task: FuzzTask, current_usage: dict) -> bool:
        """Check if all constraints allow starting"""
        return all(c.can_start_task(task, current_usage) for c in self.constraints)


@dataclass
class ConstraintConfig:
    """Configuration for resource constraints"""
    # Memory constraints
    max_total_memory_mb: Optional[float] = None
    max_memory_percent: Optional[float] = 90.0
    per_process_memory_mb: Optional[float] = None

    # CPU constraints
    max_total_cpu_percent: Optional[float] = None
    per_process_cpu_percent: Optional[float] = None

    # Time constraints
    max_runtime_seconds: Optional[int] = None

    # Behavior
    enforce_hard_limits: bool = True
    kill_on_violation: bool = False

    def build_constraints(self) -> CompositeConstraint:
        """Build composite constraint from config"""
        constraints = []

        # Memory constraint
        if self.max_total_memory_mb or self.max_memory_percent:
            if not self.max_total_memory_mb:
                # Calculate from percentage
                total_mem = psutil.virtual_memory().total / (1024 * 1024)
                self.max_total_memory_mb = total_mem * (self.max_memory_percent / 100)

            constraints.append(
                MemoryConstraint(
                    max_memory_mb=self.max_total_memory_mb,
                    per_process_limit_mb=self.per_process_memory_mb
                )
            )

        # CPU constraint
        if self.max_total_cpu_percent:
            constraints.append(
                CPUConstraint(
                    max_cpu_percent=self.max_total_cpu_percent,
                    per_process_limit_percent=self.per_process_cpu_percent
                )
            )

        # Time constraint
        if self.max_runtime_seconds:
            constraints.append(TimeConstraint(self.max_runtime_seconds))

        return CompositeConstraint(constraints)


class ConstraintEnforcer:
    """Enforces resource constraints on running processes"""

    def __init__(
        self,
        constraint: ResourceConstraint,
        kill_on_violation: bool = False
    ):
        self.constraint = constraint
        self.kill_on_violation = kill_on_violation
        self.violations: dict[str, int] = {}  # task_id -> violation count

    def check_process(self, process: FuzzProcess) -> bool:
        """
        Check process against constraints.

        Returns True if process violates constraints.
        """
        if self.constraint.check(process):
            task_id = str(process.task.id)
            self.violations[task_id] = self.violations.get(task_id, 0) + 1

            message = self.constraint.get_violation_message(process)
            console.log(f"[yellow]Constraint violation:[/yellow] {message}")

            if self.kill_on_violation:
                console.log(f"[red]Terminating process[/red] {process.task.name}")
                process.terminate()

            return True

        return False

    def can_start_task(self, task: FuzzTask, current_usage: dict) -> bool:
        """Check if task can be started"""
        return self.constraint.can_start_task(task, current_usage)

    def get_violation_count(self, task_id: str) -> int:
        """Get violation count for task"""
        return self.violations.get(task_id, 0)

    def reset_violations(self, task_id: str) -> None:
        """Reset violation count for task"""
        if task_id in self.violations:
            del self.violations[task_id]
