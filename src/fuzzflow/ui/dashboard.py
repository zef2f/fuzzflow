"""Rich-based dashboard for Fuzzflow"""

from __future__ import annotations

import asyncio
import sys
import contextlib
from collections import deque
from datetime import datetime
from typing import Deque

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from ..orchestrator import Orchestrator


class FuzzflowDashboard:
    """Interactive dashboard implemented with Rich."""

    def __init__(self, orchestrator: Orchestrator) -> None:
        self.console = Console()
        self.orchestrator = orchestrator
        self.logs: Deque[str] = deque(maxlen=100)
        self._stop = asyncio.Event()

    # ------------------------------------------------------------------
    def add_log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.logs.append(f"[{timestamp}] {message}")

    # ------------------------------------------------------------------
    def _render_metrics(self) -> Panel:
        stats = self.orchestrator.get_statistics()
        table = Table.grid(padding=(0, 1))
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="magenta")
        table.add_row("Total Tasks", str(stats.get("total_tasks", 0)))
        table.add_row("Running", str(stats.get("running_tasks", 0)))
        table.add_row("Pending", str(stats.get("pending_tasks", 0)))
        table.add_row("Completed", str(stats.get("completed_tasks", 0)))
        table.add_row("Failed", str(stats.get("failed_tasks", 0)))
        return Panel(table, title="Metrics", border_style="blue")

    def _render_resources(self) -> Panel:
        usage = None
        if hasattr(self.orchestrator, "resource_monitor"):
            usage = self.orchestrator.resource_monitor.get_current_usage()
        table = Table.grid(padding=(0, 1))
        table.add_column("Resource", style="cyan")
        table.add_column("Usage", style="magenta")
        if usage:
            table.add_row(
                "Memory",
                f"{usage.memory_used_mb:.1f}/{usage.memory_total_mb:.1f} MB ({usage.memory_percent:.1f}%)",
            )
            table.add_row("CPU", f"{usage.cpu_percent:.1f}%")
        return Panel(table, title="Resources", border_style="blue")

    def _render_processes(self) -> Panel:
        table = Table(title="Active Processes", show_lines=False)
        table.add_column("Task", style="cyan", no_wrap=True)
        table.add_column("Status", style="magenta")
        table.add_column("CPU %", justify="right")
        table.add_column("Mem MB", justify="right")
        table.add_column("Runtime", justify="right")
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
        return Panel(table, border_style="blue")

    def _render_logs(self) -> Panel:
        text = "\n".join(self.logs)
        return Panel(text, title="Logs", border_style="blue")

    def _layout(self) -> Layout:
        layout = Layout()
        layout.split_column(
            Layout(name="top", size=8),
            Layout(name="middle", ratio=1),
            Layout(name="bottom", size=10),
        )
        layout["top"].split_row(Layout(self._render_metrics()), Layout(self._render_resources()))
        layout["middle"].update(self._render_processes())
        layout["bottom"].update(self._render_logs())
        return layout

    # ------------------------------------------------------------------
    async def _input_loop(self) -> None:
        loop = asyncio.get_running_loop()
        while not self._stop.is_set():
            cmd = await loop.run_in_executor(None, sys.stdin.readline)
            if not cmd:
                continue
            cmd = cmd.strip().lower()
            if cmd == "p":
                count = self.orchestrator.pause_all()
                self.add_log(f"Paused {count} processes")
            elif cmd == "r":
                count = self.orchestrator.resume_all()
                self.add_log(f"Resumed {count} processes")
            elif cmd == "s":
                count = await self.orchestrator.stop_all()
                self.add_log(f"Stopped {count} processes")
            elif cmd == "q":
                self._stop.set()

    async def _refresh_loop(self, live: Live) -> None:
        while not self._stop.is_set():
            live.update(self._layout())
            await asyncio.sleep(1)

    async def _run_orchestrator(self) -> None:
        self.add_log("Starting Fuzzflow orchestrator...")
        try:
            await self.orchestrator.start()
            self.add_log("Orchestrator started")
            while self.orchestrator.has_pending_tasks() and not self._stop.is_set():
                await asyncio.sleep(1)
            self.add_log("All tasks completed")
        except Exception as e:
            self.add_log(f"Error: {e}")
        finally:
            await self.orchestrator.stop()
            self._stop.set()

    # ------------------------------------------------------------------
    async def _run_async(self) -> None:
        with Live(self._layout(), console=self.console, screen=True, refresh_per_second=4) as live:
            refresh = asyncio.create_task(self._refresh_loop(live))
            inputs = asyncio.create_task(self._input_loop())
            orchestrator = asyncio.create_task(self._run_orchestrator())
            await self._stop.wait()
            for task in (refresh, inputs, orchestrator):
                task.cancel()
                with contextlib.suppress(Exception):
                    await task

    def run(self) -> None:
        """Run the dashboard."""
        asyncio.run(self._run_async())

