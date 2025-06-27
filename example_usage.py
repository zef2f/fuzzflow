#!/usr/bin/env python3
"""Example usage of Fuzzflow as a library"""

import asyncio
from pathlib import Path

from fuzzflow import (
    FuzzTask,
    TaskPriority,
    Orchestrator,
    OrchestratorConfig,
)


async def main():
    # Configure orchestrator
    config = OrchestratorConfig(
        max_parallel_tasks=5,
        memory_limit_mb=4096,
        enable_adaptive_scheduling=True,
        output_dir=Path("my_fuzzing_campaign"),
    )

    # Create orchestrator
    orchestrator = Orchestrator(config)

    # Create tasks
    tasks = [
        FuzzTask(
            name="fuzz_parser_afl",
            command=["./parser", "@@"],
            fuzzer_type="afl++",
            priority=TaskPriority.HIGH,
            memory_limit_mb=1024,
            fuzzer_config={
                "skip_deterministic": True,
                "is_master": True,
            },
            tags=["parser", "afl"],
        ),
        FuzzTask(
            name="fuzz_parser_libfuzzer",
            command=["./parser_libfuzzer"],
            fuzzer_type="libfuzzer",
            priority=TaskPriority.NORMAL,
            memory_limit_mb=1024,
            fuzzer_config={
                "max_len": 4096,
                "workers": 2,
            },
            tags=["parser", "libfuzzer"],
        ),
    ]

    # Submit tasks
    orchestrator.submit_tasks(tasks)

    # Start orchestrator
    await orchestrator.start()

    try:
        # Wait for completion
        while orchestrator.has_pending_tasks():
            stats = orchestrator.get_statistics()
            print(f"Running: {stats['running_tasks']}, "
                  f"Pending: {stats['pending_tasks']}, "
                  f"Completed: {stats['completed_tasks']}")
            await asyncio.sleep(10)

        print("All tasks completed!")

    finally:
        # Cleanup
        await orchestrator.stop()


if __name__ == "__main__":
    asyncio.run(main())
