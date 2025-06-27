"""Textual-based TUI dashboard for Fuzzflow"""

import asyncio
from datetime import datetime
from typing import Optional

from rich.table import Table
from textual import events
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Label,
    ProgressBar,
    Static,
)

from ..orchestrator import Orchestrator


class MetricsPanel(Static):
    """Panel showing fuzzing metrics"""

    def __init__(self, orchestrator: Orchestrator):
        super().__init__()
        self.orchestrator = orchestrator

    def compose(self) -> ComposeResult:
        yield Label("Fuzzing Metrics", classes="panel-title")

    def on_mount(self) -> None:
        self.set_interval(1.0, self.update_metrics)

    def update_metrics(self) -> None:
        """Update metrics display"""
        stats = self.orchestrator.get_statistics()

        table = Table(show_header=False, box=None)
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="white")

        table.add_row("Total Tasks", str(stats.get("total_tasks", 0)))
        table.add_row("Running", str(stats.get("running_tasks", 0)))
        table.add_row("Pending", str(stats.get("pending_tasks", 0)))
        table.add_row("Completed", str(stats.get("completed_tasks", 0)))
        table.add_row("Failed", str(stats.get("failed_tasks", 0)))

        self.update(table)


class ResourcePanel(Static):
    """Panel showing resource usage"""

    def __init__(self, orchestrator: Orchestrator):
        super().__init__()
        self.orchestrator = orchestrator

    def compose(self) -> ComposeResult:
        yield Label("System Resources", classes="panel-title")

    def on_mount(self) -> None:
        self.set_interval(1.0, self.update_resources)

    def update_resources(self) -> None:
        """Update resource display"""
        if hasattr(self.orchestrator, 'resource_monitor'):
            usage = self.orchestrator.resource_monitor.get_current_usage()
            if usage:
                table = Table(show_header=False, box=None)
                table.add_column("Resource", style="cyan")
                table.add_column("Usage", style="white")

                table.add_row(
                    "Memory",
                    f"{usage.memory_used_mb:.1f} / {usage.memory_total_mb:.1f} MB "
                    f"({usage.memory_percent:.1f}%)"
                )
                table.add_row("CPU", f"{usage.cpu_percent:.1f}%")

                self.update(table)


class ProcessList(Static):
    """List of running processes"""

    def __init__(self, orchestrator: Orchestrator):
        super().__init__()
        self.orchestrator = orchestrator

    def compose(self) -> ComposeResult:
        yield Label("Active Processes", classes="panel-title")
        yield DataTable()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("Task", "Status", "CPU %", "Memory MB", "Runtime")
        self.set_interval(1.0, self.update_processes)

    def update_processes(self) -> None:
        """Update process list"""
        table = self.query_one(DataTable)
        table.clear()

        for process in self.orchestrator.process_manager.processes.values():
            if process.is_alive:
                metrics = process.current_metrics
                table.add_row(
                    process.task.name,
                    process.state.name,
                    f"{metrics.cpu_percent:.1f}" if metrics else "-",
                    f"{metrics.memory_mb:.1f}" if metrics else "-",
                    f"{process.runtime:.0f}s" if process.runtime else "-",
                )


class LogPanel(Static):
    """Log output panel"""

    def __init__(self):
        super().__init__()
        self.logs = []
        self.max_logs = 100

    def add_log(self, message: str) -> None:
        """Add log message"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.logs.append(f"[{timestamp}] {message}")

        if len(self.logs) > self.max_logs:
            self.logs.pop(0)

        self.update("\n".join(self.logs[-20:]))  # Show last 20 logs


class FuzzflowDashboard(App):
    """Main dashboard application"""

    CSS = """
    .panel-title {
        background: $primary;
        color: $text;
        padding: 1;
        text-align: center;
        text-style: bold;
    }

    MetricsPanel {
        border: solid $primary;
        height: 10;
    }

    ResourcePanel {
        border: solid $primary;
        height: 8;
    }

    ProcessList {
        border: solid $primary;
    }

    LogPanel {
        border: solid $primary;
        height: 15;
    }

    #sidebar {
        width: 40;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("p", "pause_all", "Pause All"),
        ("r", "resume_all", "Resume All"),
        ("s", "stop_all", "Stop All"),
    ]

    def __init__(self, orchestrator: Orchestrator):
        super().__init__()
        self.orchestrator = orchestrator
        self.log_panel = LogPanel()

    def compose(self) -> ComposeResult:
        yield Header()

        with Horizontal():
            with Vertical(id="sidebar"):
                yield MetricsPanel(self.orchestrator)
                yield ResourcePanel(self.orchestrator)

                with Horizontal():
                    yield Button("Pause All", id="pause-btn", variant="warning")
                    yield Button("Stop All", id="stop-btn", variant="error")

            with Vertical():
                yield ProcessList(self.orchestrator)
                yield self.log_panel

        yield Footer()

    async def on_mount(self) -> None:
        """Start orchestrator when dashboard mounts"""
        self.log_panel.add_log("Starting Fuzzflow orchestrator...")

        # Start orchestrator in background
        asyncio.create_task(self.run_orchestrator())

    async def run_orchestrator(self) -> None:
        """Run orchestrator"""
        try:
            await self.orchestrator.start()
            self.log_panel.add_log("Orchestrator started successfully")

            # Wait for completion
            while self.orchestrator.has_pending_tasks():
                await asyncio.sleep(1)

            self.log_panel.add_log("All tasks completed")

        except Exception as e:
            self.log_panel.add_log(f"Error: {e}")
        finally:
            await self.orchestrator.stop()

    def action_quit(self) -> None:
        """Quit application"""
        asyncio.create_task(self.shutdown())

    async def shutdown(self) -> None:
        """Shutdown orchestrator and exit"""
        self.log_panel.add_log("Shutting down...")
        await self.orchestrator.stop()
        self.exit()

    def action_pause_all(self) -> None:
        """Pause all processes"""
        count = self.orchestrator.pause_all()
        self.log_panel.add_log(f"Paused {count} processes")

    def action_resume_all(self) -> None:
        """Resume all processes"""
        count = self.orchestrator.resume_all()
        self.log_panel.add_log(f"Resumed {count} processes")

    def action_stop_all(self) -> None:
        """Stop all processes"""
        asyncio.create_task(self._stop_all())

    async def _stop_all(self) -> None:
        """Stop all processes async"""
        self.log_panel.add_log("Stopping all processes...")
        count = await self.orchestrator.stop_all()
        self.log_panel.add_log(f"Stopped {count} processes")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press"""
        if event.button.id == "pause-btn":
            self.action_pause_all()
        elif event.button.id == "stop-btn":
            self.action_stop_all()
