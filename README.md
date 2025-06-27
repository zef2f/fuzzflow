# Fuzzflow 2.0

A modern, extensible fuzzing orchestration framework designed for managing complex fuzzing campaigns with multiple fuzzers, intelligent scheduling, and resource management.

## Features

- **Multi-Fuzzer Support**: Built-in adapters for AFL++, LibFuzzer, and Honggfuzz
- **Intelligent Scheduling**: Priority-based, fair-share, and adaptive scheduling strategies
- **Resource Management**: Memory and CPU constraints with automatic enforcement
- **Real-time Monitoring**: Compact interactive dashboard powered by Rich
- **Metrics Collection**: Prometheus integration and efficiency tracking
- **Extensible Architecture**: Easy to add new fuzzers and strategies

## Quick Start

### CLI Usage

```bash
# Create tasks interactively
fuzzflow create -o tasks.json

# Run fuzzing campaign
fuzzflow run -t tasks.json -p 10 -m 8192

# Run with config file
fuzzflow run -c config.json
```

### Library Usage

```python
import asyncio
from fuzzflow import Orchestrator, OrchestratorConfig, FuzzTask

async def main():
    config = OrchestratorConfig(max_parallel_tasks=5)
    orchestrator = Orchestrator(config)

    task = FuzzTask(
        name="my_fuzzer",
        command=["./target", "@@"],
        fuzzer_type="afl++",
    )

    orchestrator.submit_task(task)
    await orchestrator.start()

    # Wait for completion
    while orchestrator.has_pending_tasks():
        await asyncio.sleep(10)

    await orchestrator.stop()

asyncio.run(main())
```

## Architecture

Fuzzflow 2.0 is built with a modular architecture:

- **Core**: Task management, process control, and scheduling
- **Adapters**: Fuzzer-specific implementations
- **Monitoring**: Resource tracking and metrics collection
- **UI**: CLI and TUI interfaces

## Extending Fuzzflow

### Adding a New Fuzzer

```python
from fuzzflow.adapters import FuzzerAdapter, FuzzerCapabilities

class MyFuzzerAdapter(FuzzerAdapter):
    def get_capabilities(self) -> FuzzerCapabilities:
        return FuzzerCapabilities(
            supports_coverage_guided=True,
            # ... other capabilities
        )

    def build_command(self, task, binary_path, work_dir):
        # Build command line for your fuzzer
        pass

# Register the adapter
from fuzzflow.adapters import FuzzerRegistry
FuzzerRegistry.register("myfuzzer", MyFuzzerAdapter)
```

### Custom Scheduling Strategy

```python
from fuzzflow.core import SchedulingStrategy

class MyStrategy(SchedulingStrategy):
    def select_next_task(self, pending_tasks, running_tasks, 
                        available_memory_mb, available_cores):
        # Implement your scheduling logic
        pass
```
