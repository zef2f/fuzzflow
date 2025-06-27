"""Task representation for fuzzing jobs"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from uuid import UUID, uuid4


class TaskStatus(Enum):
    """Task lifecycle states"""
    PENDING = auto()
    SCHEDULED = auto()
    RUNNING = auto()
    PAUSED = auto()
    COMPLETED = auto()
    FAILED = auto()
    CANCELLED = auto()


class TaskPriority(Enum):
    """Task priority levels"""
    CRITICAL = 100
    HIGH = 75
    NORMAL = 50
    LOW = 25
    IDLE = 0


@dataclass
class FuzzTask:
    """
    Represents a fuzzing task that can be scheduled and executed.

    This is the core abstraction for any fuzzing job in the system.
    It's designed to be fuzzer-agnostic and extensible.
    """

    # Required fields
    name: str
    command: Union[str, List[str]]  # Command to execute
    fuzzer_type: str  # afl++, libfuzzer, honggfuzz, etc.

    # Optional fields with defaults
    id: UUID = field(default_factory=uuid4)
    priority: TaskPriority = TaskPriority.NORMAL
    status: TaskStatus = TaskStatus.PENDING

    # Resource requirements
    memory_limit_mb: Optional[int] = None
    cpu_cores: Optional[int] = None
    timeout_seconds: Optional[int] = None

    # Paths
    input_dir: Optional[Path] = None
    output_dir: Optional[Path] = None
    corpus_dir: Optional[Path] = None

    # Metadata
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # Fuzzer-specific configuration
    fuzzer_config: Dict[str, Any] = field(default_factory=dict)

    # Metrics and results
    metrics: Dict[str, Any] = field(default_factory=dict)
    exit_code: Optional[int] = None
    error_message: Optional[str] = None

    # Scheduling hints
    dependencies: List[UUID] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)

    def __post_init__(self):
        """Validate and normalize task data"""
        if isinstance(self.command, str):
            # Convert string command to list for consistency
            import shlex
            self.command = shlex.split(self.command)

        # Ensure paths are Path objects
        if self.input_dir and not isinstance(self.input_dir, Path):
            self.input_dir = Path(self.input_dir)
        if self.output_dir and not isinstance(self.output_dir, Path):
            self.output_dir = Path(self.output_dir)
        if self.corpus_dir and not isinstance(self.corpus_dir, Path):
            self.corpus_dir = Path(self.corpus_dir)

    def is_ready(self) -> bool:
        """Check if task is ready to run (no pending dependencies)"""
        return self.status == TaskStatus.PENDING and not self.dependencies

    def can_run_with_resources(self, available_memory_mb: int, available_cores: int) -> bool:
        """Check if task can run with available resources"""
        memory_ok = (self.memory_limit_mb is None or
                    available_memory_mb >= self.memory_limit_mb)
        cpu_ok = (self.cpu_cores is None or
                 available_cores >= self.cpu_cores)
        return memory_ok and cpu_ok

    def update_status(self, new_status: TaskStatus) -> None:
        """Update task status with timestamp tracking"""
        self.status = new_status

        if new_status == TaskStatus.RUNNING:
            self.started_at = datetime.now()
        elif new_status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
            self.completed_at = datetime.now()

    @property
    def duration(self) -> Optional[float]:
        """Get task execution duration in seconds"""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        elif self.started_at:
            return (datetime.now() - self.started_at).total_seconds()
        return None

    def to_dict(self) -> Dict[str, Any]:
        """Convert task to dictionary for serialization"""
        return {
            "id": str(self.id),
            "name": self.name,
            "command": self.command,
            "fuzzer_type": self.fuzzer_type,
            "priority": self.priority.name,
            "status": self.status.name,
            "memory_limit_mb": self.memory_limit_mb,
            "cpu_cores": self.cpu_cores,
            "timeout_seconds": self.timeout_seconds,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration": self.duration,
            "metrics": self.metrics,
            "exit_code": self.exit_code,
            "tags": self.tags,
        }
