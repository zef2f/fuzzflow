"""Command-line interface for Fuzzflow"""

import asyncio
import json
import sys
from pathlib import Path
from typing import List, Optional

import typer
from rich import print
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from ..core import FuzzTask, TaskPriority
from ..orchestrator import Orchestrator, OrchestratorConfig
from ..ui.dashboard import FuzzflowDashboard
from .interactive import InteractiveTaskBuilder


app = typer.Typer(
    name="fuzzflow",
    help="Modern fuzzing orchestration framework",
    add_completion=True,
    rich_markup_mode="rich",
)
console = Console()


@app.command()
def run(
    config_file: Path = typer.Option(
        None,
        "--config", "-c",
        help="Configuration file (JSON/YAML)",
    ),
    tasks_file: Path = typer.Option(
        None,
        "--tasks", "-t",
        help="Tasks definition file",
    ),
    max_parallel: int = typer.Option(
        10,
        "--max-parallel", "-p",
        help="Maximum parallel fuzzing processes",
    ),
    memory_limit: Optional[int] = typer.Option(
        None,
        "--memory-limit", "-m",
        help="Total memory limit in MB",
    ),
    cpu_limit: Optional[int] = typer.Option(
        None,
        "--cpu-limit",
        help="CPU usage limit percentage",
    ),
    output_dir: Path = typer.Option(
        Path("fuzzflow_output"),
        "--output", "-o",
        help="Output directory",
    ),
    ui_mode: str = typer.Option(
        "auto",
        "--ui",
        help="UI mode: auto, tui, simple, none",
    ),
    debug: bool = typer.Option(
        False,
        "--debug",
        help="Enable debug logging",
    ),
):
    """Run fuzzing tasks"""

    # Load configuration
    config = OrchestratorConfig(
        max_parallel_tasks=max_parallel,
        memory_limit_mb=memory_limit,
        cpu_limit_percent=cpu_limit,
        output_dir=output_dir,
        enable_metrics=True,
        enable_prometheus=False,  # Can be enabled in config
    )

    if config_file and config_file.exists():
        # Load and merge config file
        with open(config_file) as f:
            if config_file.suffix == ".json":
                file_config = json.load(f)
            else:
                import yaml
                file_config = yaml.safe_load(f)

        # Merge with CLI options (CLI takes precedence)
        for key, value in file_config.items():
            if not getattr(config, key, None):
                setattr(config, key, value)

    # Load tasks
    tasks = []

    if tasks_file and tasks_file.exists():
        with open(tasks_file) as f:
            tasks_data = json.load(f) if tasks_file.suffix == ".json" else yaml.safe_load(f)

        for task_data in tasks_data.get("tasks", []):
            task = FuzzTask(**task_data)
            tasks.append(task)

    if not tasks:
        console.print("[yellow]No tasks loaded from file[/yellow]")
        if Confirm.ask("Would you like to create tasks interactively?"):
            tasks = create_tasks_interactive()
        else:
            console.print("[red]No tasks to run[/red]")
            raise typer.Exit(1)

    # Create orchestrator
    orchestrator = Orchestrator(config)

    # Submit tasks
    for task in tasks:
        orchestrator.submit_task(task)

    # Determine UI mode
    if ui_mode == "auto":
        ui_mode = "tui" if sys.stdout.isatty() else "simple"

    # Run with appropriate UI
    if ui_mode == "tui":
        # Run with Rich dashboard
        dashboard = FuzzflowDashboard(orchestrator)
        dashboard.run()
    elif ui_mode == "simple":
        # Run with simple progress display
        asyncio.run(run_simple_ui(orchestrator))
    else:
        # Run without UI
        asyncio.run(orchestrator.run())


@app.command()
def create(
    output_file: Path = typer.Option(
        Path("tasks.json"),
        "--output", "-o",
        help="Output file for tasks",
    ),
    interactive: bool = typer.Option(
        True,
        "--interactive", "-i",
        help="Interactive task creation",
    ),
):
    """Create fuzzing tasks"""

    if interactive:
        tasks = create_tasks_interactive()
    else:
        # Create from command line
        console.print("[yellow]Non-interactive mode not implemented yet[/yellow]")
        raise typer.Exit(1)

    # Save tasks
    tasks_data = {
        "version": "2.0",
        "tasks": [
            {
                "name": task.name,
                "command": task.command,
                "fuzzer_type": task.fuzzer_type,
                "priority": task.priority.name,
                "memory_limit_mb": task.memory_limit_mb,
                "cpu_cores": task.cpu_cores,
                "timeout_seconds": task.timeout_seconds,
                "fuzzer_config": task.fuzzer_config,
                "tags": task.tags,
            }
            for task in tasks
        ]
    }

    with open(output_file, "w") as f:
        json.dump(tasks_data, f, indent=2)

    console.print(f"[green]Saved {len(tasks)} tasks to {output_file}[/green]")


@app.command()
def list_fuzzers():
    """List available fuzzer adapters"""
    from ..adapters import FuzzerRegistry

    table = Table(title="Available Fuzzers")
    table.add_column("Name", style="cyan")
    table.add_column("Aliases", style="green")
    table.add_column("Status", style="yellow")

    # Group by adapter class
    adapters = {}
    for name in FuzzerRegistry.list_adapters():
        adapter_class = FuzzerRegistry.get(name)
        class_name = adapter_class.__name__
        if class_name not in adapters:
            adapters[class_name] = []
        adapters[class_name].append(name)

    for adapter_name, aliases in adapters.items():
        main_name = adapter_name.replace("Adapter", "")
        table.add_row(
            main_name,
            ", ".join(aliases),
            "✓ Available"
        )

    console.print(table)


@app.command()
def status(
    orchestrator_url: str = typer.Option(
        "http://localhost:8080",
        "--url",
        help="Orchestrator API URL",
    ),
):
    """Check status of running orchestrator"""
    # This would connect to a running orchestrator via API
    console.print("[yellow]Status command requires running orchestrator with API enabled[/yellow]")
    raise typer.Exit(1)


@app.command()
def validate(
    config_file: Path = typer.Argument(..., help="Configuration file to validate"),
):
    """Validate configuration file"""

    if not config_file.exists():
        console.print(f"[red]File not found: {config_file}[/red]")
        raise typer.Exit(1)

    try:
        with open(config_file) as f:
            if config_file.suffix == ".json":
                data = json.load(f)
            else:
                import yaml
                data = yaml.safe_load(f)

        # Validate structure
        errors = []

        if "tasks" not in data:
            errors.append("Missing 'tasks' section")

        for i, task_data in enumerate(data.get("tasks", [])):
            if "name" not in task_data:
                errors.append(f"Task {i}: missing 'name'")
            if "command" not in task_data:
                errors.append(f"Task {i}: missing 'command'")
            if "fuzzer_type" not in task_data:
                errors.append(f"Task {i}: missing 'fuzzer_type'")

        if errors:
            console.print("[red]Validation errors:[/red]")
            for error in errors:
                console.print(f"  - {error}")
            raise typer.Exit(1)

        console.print(f"[green]✓ Configuration is valid[/green]")
        console.print(f"  Tasks: {len(data.get('tasks', []))}")

    except json.JSONDecodeError as e:
        console.print(f"[red]Invalid JSON: {e}[/red]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


def create_tasks_interactive() -> List[FuzzTask]:
    """Create tasks interactively"""
    builder = InteractiveTaskBuilder()
    return builder.build_tasks()


async def run_simple_ui(orchestrator: Orchestrator):
    """Run with simple console UI"""
    from rich.live import Live
    from rich.progress import Progress, SpinnerColumn, TextColumn

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:

        main_task = progress.add_task("Running fuzzing tasks...", total=None)

        # Start orchestrator
        await orchestrator.start()

        try:
            # Monitor until complete
            while orchestrator.has_pending_tasks():
                stats = orchestrator.get_statistics()
                progress.update(
                    main_task,
                    description=f"Running: {stats['running_tasks']}, "
                                f"Pending: {stats['pending_tasks']}, "
                                f"Completed: {stats['completed_tasks']}"
                )
                await asyncio.sleep(1)

            # Show final results
            console.print("\n[bold green]Fuzzing complete![/bold green]")

            stats = orchestrator.get_statistics()
            console.print(f"Total tasks: {stats['total_tasks']}")
            console.print(f"Successful: {stats['successful_tasks']}")
            console.print(f"Failed: {stats['failed_tasks']}")

        finally:
            await orchestrator.stop()


def main():
    """Main entry point"""
    app()
