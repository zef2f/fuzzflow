"""Interactive task creation"""

from pathlib import Path
from typing import List, Optional

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.table import Table

from ..adapters import FuzzerRegistry
from ..core import FuzzTask, TaskPriority


console = Console()


class InteractiveTaskBuilder:
    """Interactive task builder using Rich prompts"""

    def __init__(self):
        self.tasks: List[FuzzTask] = []

    def build_tasks(self) -> List[FuzzTask]:
        """Build tasks interactively"""
        console.print(
            Panel.fit(
                "[bold cyan]Fuzzflow Interactive Task Creator[/bold cyan]\n"
                "Create fuzzing tasks by answering questions.\n"
                "Press Ctrl+C to cancel at any time.",
                border_style="cyan"
            )
        )

        while True:
            task = self.build_single_task()
            if task:
                self.tasks.append(task)
                console.print(f"\n[green]✓ Created task: {task.name}[/green]")

            if not Confirm.ask("\nCreate another task?", default=True):
                break

        return self.tasks

    def build_single_task(self) -> Optional[FuzzTask]:
        """Build a single task interactively"""
        console.print("\n[bold]Creating new fuzzing task[/bold]")

        # Basic information
        name = Prompt.ask("Task name")

        # Fuzzer selection
        fuzzer_type = self.select_fuzzer()

        # Command input
        console.print("\n[cyan]Enter the command to run:[/cyan]")
        console.print("[dim]You can enter multiple commands (one per line).[/dim]")
        console.print("[dim]Press Enter twice to finish.[/dim]")

        commands = []
        while True:
            cmd = Prompt.ask("Command" if not commands else "Command (or Enter to finish)")
            if not cmd:
                break
            commands.append(cmd)

        if not commands:
            console.print("[red]No commands entered, skipping task[/red]")
            return None

        # Build command
        if len(commands) == 1:
            # Parse single command
            import shlex
            command = shlex.split(commands[0])
        else:
            # Multiple commands - create a pipeline
            command = commands

        # Resource limits
        console.print("\n[cyan]Resource limits:[/cyan]")

        memory_limit = IntPrompt.ask(
            "Memory limit (MB)",
            default=0,
            show_default=False
        )
        memory_limit = memory_limit if memory_limit > 0 else None

        cpu_cores = IntPrompt.ask(
            "CPU cores",
            default=1
        )

        timeout = IntPrompt.ask(
            "Timeout (seconds, 0 for no timeout)",
            default=0
        )
        timeout = timeout if timeout > 0 else None

        # Priority
        priority = self.select_priority()

        # Tags
        tags_str = Prompt.ask(
            "Tags (comma-separated)",
            default=""
        )
        tags = [t.strip() for t in tags_str.split(",") if t.strip()]

        # Fuzzer-specific configuration
        fuzzer_config = self.get_fuzzer_config(fuzzer_type)

        # Create task
        task = FuzzTask(
            name=name,
            command=command,
            fuzzer_type=fuzzer_type,
            priority=priority,
            memory_limit_mb=memory_limit,
            cpu_cores=cpu_cores,
            timeout_seconds=timeout,
            fuzzer_config=fuzzer_config,
            tags=tags,
        )

        return task

    def select_fuzzer(self) -> str:
        """Select fuzzer type"""
        fuzzers = FuzzerRegistry.list_adapters()

        # Group similar fuzzers
        unique_fuzzers = []
        seen = set()

        for fuzzer in fuzzers:
            base_name = fuzzer.replace("+", "").lower()
            if base_name not in seen:
                unique_fuzzers.append(fuzzer)
                seen.add(base_name)

        console.print("\n[cyan]Available fuzzers:[/cyan]")
        for i, fuzzer in enumerate(unique_fuzzers, 1):
            console.print(f"  {i}. {fuzzer}")

        while True:
            choice = IntPrompt.ask(
                "Select fuzzer",
                choices=[str(i) for i in range(1, len(unique_fuzzers) + 1)]
            )
            return unique_fuzzers[choice - 1]

    def select_priority(self) -> TaskPriority:
        """Select task priority"""
        priorities = list(TaskPriority)

        console.print("\n[cyan]Task priority:[/cyan]")
        for i, priority in enumerate(priorities, 1):
            console.print(f"  {i}. {priority.name} ({priority.value})")

        choice = IntPrompt.ask(
            "Select priority",
            default=3,  # NORMAL
            choices=[str(i) for i in range(1, len(priorities) + 1)]
        )

        return priorities[choice - 1]

    def get_fuzzer_config(self, fuzzer_type: str) -> dict:
        """Get fuzzer-specific configuration"""
        config = {}

        console.print(f"\n[cyan]Configure {fuzzer_type}:[/cyan]")

        # Common options based on fuzzer type
        if "afl" in fuzzer_type.lower():
            if Confirm.ask("Use dictionary?", default=False):
                dict_path = Prompt.ask("Dictionary path")
                config["dictionary"] = dict_path

            if Confirm.ask("Skip deterministic mutations?", default=False):
                config["skip_deterministic"] = True

            if Confirm.ask("Configure for parallel fuzzing?", default=False):
                if Confirm.ask("Is this the master instance?", default=True):
                    config["is_master"] = True
                else:
                    fuzzer_id = Prompt.ask("Fuzzer ID")
                    config["fuzzer_id"] = fuzzer_id

        elif "libfuzzer" in fuzzer_type.lower():
            max_len = IntPrompt.ask(
                "Maximum input length",
                default=4096
            )
            config["max_len"] = max_len

            if Confirm.ask("Use dictionary?", default=False):
                dict_path = Prompt.ask("Dictionary path")
                config["dictionary"] = dict_path

            workers = IntPrompt.ask(
                "Number of workers",
                default=1
            )
            if workers > 1:
                config["workers"] = workers

        elif "honggfuzz" in fuzzer_type.lower():
            threads = IntPrompt.ask(
                "Number of threads",
                default=1
            )
            config["threads"] = threads

            if Confirm.ask("Save all crashes?", default=False):
                config["save_all_crashes"] = True

        # Custom configuration
        if Confirm.ask("\nAdd custom configuration?", default=False):
            console.print("[dim]Enter key=value pairs, one per line[/dim]")
            console.print("[dim]Press Enter twice to finish[/dim]")

            while True:
                entry = Prompt.ask("Config (key=value)")
                if not entry:
                    break

                if "=" in entry:
                    key, value = entry.split("=", 1)
                    # Try to parse value
                    try:
                        # Try as number
                        if "." in value:
                            value = float(value)
                        else:
                            value = int(value)
                    except ValueError:
                        # Try as boolean
                        if value.lower() in ("true", "yes", "on"):
                            value = True
                        elif value.lower() in ("false", "no", "off"):
                            value = False

                    config[key.strip()] = value

        return config

