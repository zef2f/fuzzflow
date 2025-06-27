"""Process manager for handling multiple fuzzing processes"""

import asyncio
import signal
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple
from uuid import UUID

from rich.console import Console
from rich.table import Table

from .process import FuzzProcess, ProcessState
from .task import FuzzTask, TaskStatus


console = Console()


class ProcessManager:
    """
    Manages the lifecycle of multiple fuzzing processes.

    Features:
    - Process pool management
    - Resource tracking
    - Signal forwarding
    - Process monitoring
    - Graceful shutdown
    """

    def __init__(self, max_processes: int = 10):
        self.max_processes = max_processes
        self.processes: Dict[UUID, FuzzProcess] = {}
        self.active_pids: Dict[int, UUID] = {}  # PID -> Task ID mapping

        # Resource tracking
        self.total_memory_mb = 0.0
        self.total_cpu_percent = 0.0

        # Event loop integration
        self._monitor_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()

        # Setup signal handlers
        self._setup_signal_handlers()

    def _setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown"""
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, self._signal_handler)

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        console.log(f"[yellow]Received signal {signum}, initiating shutdown...[/yellow]")
        asyncio.create_task(self.shutdown())

    async def start_task(self, task: FuzzTask) -> bool:
        """
        Start a new fuzzing task if resources allow.

        Returns True if started successfully, False otherwise.
        """
        # Check if we can start a new process
        if len(self.get_running_processes()) >= self.max_processes:
            console.log(f"[yellow]Max processes reached[/yellow], queuing {task.name}")
            return False

        # Create and start process
        process = FuzzProcess(task)

        try:
            process.start()
            task.update_status(TaskStatus.RUNNING)

            # Register process
            self.processes[task.id] = process
            self.active_pids[process.pid] = task.id

            # Start monitoring
            await process.start_monitoring()

            return True

        except Exception as e:
            task.update_status(TaskStatus.FAILED)
            task.error_message = str(e)
            console.log(f"[red]Failed to start task[/red] {task.name}: {e}")
            return False

    def pause_task(self, task_id: UUID) -> bool:
        """Pause a running task"""
        if task_id in self.processes:
            process = self.processes[task_id]
            process.pause()
            process.task.update_status(TaskStatus.PAUSED)
            return True
        return False

    def resume_task(self, task_id: UUID) -> bool:
        """Resume a paused task"""
        if task_id in self.processes:
            process = self.processes[task_id]
            process.resume()
            process.task.update_status(TaskStatus.RUNNING)
            return True
        return False

    def stop_task(self, task_id: UUID, timeout: int = 10) -> bool:
        """Stop a running task"""
        if task_id in self.processes:
            process = self.processes[task_id]
            process.terminate(timeout)

            # Update task status
            if process.exit_code == 0:
                process.task.update_status(TaskStatus.COMPLETED)
            else:
                process.task.update_status(TaskStatus.FAILED)

            # Cleanup
            if process.pid in self.active_pids:
                del self.active_pids[process.pid]

            return True
        return False

    def get_running_processes(self) -> List[FuzzProcess]:
        """Get all running processes"""
        return [p for p in self.processes.values()
                if p.state == ProcessState.RUNNING]

    def get_paused_processes(self) -> List[FuzzProcess]:
        """Get all paused processes"""
        return [p for p in self.processes.values()
                if p.state == ProcessState.PAUSED]

    def get_process_by_task(self, task_id: UUID) -> Optional[FuzzProcess]:
        """Get process by task ID"""
        return self.processes.get(task_id)

    def get_process_by_pid(self, pid: int) -> Optional[FuzzProcess]:
        """Get process by PID"""
        task_id = self.active_pids.get(pid)
        return self.processes.get(task_id) if task_id else None

    async def monitor_resources(self) -> Tuple[float, float]:
        """
        Monitor total resource usage across all processes.

        Returns: (total_memory_mb, total_cpu_percent)
        """
        total_memory = 0.0
        total_cpu = 0.0

        for process in self.get_running_processes():
            memory = process.get_total_memory_mb()
            total_memory += memory

            metrics = process.current_metrics
            if metrics:
                total_cpu += metrics.cpu_percent

        self.total_memory_mb = total_memory
        self.total_cpu_percent = total_cpu

        return total_memory, total_cpu

    def get_statistics(self) -> Dict[str, any]:
        """Get manager statistics"""
        running = self.get_running_processes()
        paused = self.get_paused_processes()

        return {
            "total_processes": len(self.processes),
            "running": len(running),
            "paused": len(paused),
            "terminated": len([p for p in self.processes.values() 
                             if p.state == ProcessState.TERMINATED]),
            "failed": len([p for p in self.processes.values() 
                         if p.state == ProcessState.FAILED]),
            "total_memory_mb": self.total_memory_mb,
            "total_cpu_percent": self.total_cpu_percent,
            "max_processes": self.max_processes,
        }

    def print_status(self) -> None:
        """Print current status table"""
        table = Table(title="Process Manager Status")
        table.add_column("Task", style="cyan")
        table.add_column("PID", style="magenta")
        table.add_column("State", style="green")
        table.add_column("CPU %", style="yellow")
        table.add_column("Memory MB", style="blue")
        table.add_column("Runtime", style="white")

        for process in self.processes.values():
            metrics = process.current_metrics

            table.add_row(
                process.task.name,
                str(process.pid) if process.pid else "-",
                process.state.name,
                f"{metrics.cpu_percent:.1f}" if metrics else "-",
                f"{metrics.memory_mb:.1f}" if metrics else "-",
                f"{process.runtime:.1f}s" if process.runtime else "-",
            )

        console.print(table)

    async def cleanup_terminated(self) -> None:
        """Clean up terminated processes"""
        to_remove = []

        for task_id, process in self.processes.items():
            if process.state in (ProcessState.TERMINATED, ProcessState.FAILED):
                if not process.is_alive:
                    to_remove.append(task_id)

        for task_id in to_remove:
            process = self.processes[task_id]
            if process.pid in self.active_pids:
                del self.active_pids[process.pid]
            del self.processes[task_id]

            console.log(f"[dim]Cleaned up process[/dim] {process.task.name}")

    async def shutdown(self, timeout: int = 30) -> None:
        """Gracefully shutdown all processes"""
        console.log("[yellow]Shutting down all processes...[/yellow]")

        # Stop accepting new tasks
        self._shutdown_event.set()

        # Terminate all running processes
        tasks = []
        for process in self.processes.values():
            if process.is_alive:
                tasks.append(
                    asyncio.create_task(
                        asyncio.to_thread(process.terminate, timeout)
                    )
                )

        # Wait for all terminations
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        # Final cleanup
        await self.cleanup_terminated()

        console.log("[green]Shutdown complete[/green]")

    async def __aenter__(self):
        """Async context manager entry"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.shutdown()
