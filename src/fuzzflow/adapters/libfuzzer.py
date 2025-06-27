"""LibFuzzer adapter implementation"""

import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from rich.console import Console

from ..core.task import FuzzTask
from ..monitoring.metrics import LibFuzzerMetricProvider, MetricProvider
from .base import FuzzerAdapter, FuzzerCapabilities


console = Console()


class LibFuzzerAdapter(FuzzerAdapter):
    """Adapter for LibFuzzer"""

    def get_capabilities(self) -> FuzzerCapabilities:
        """Get LibFuzzer capabilities"""
        return FuzzerCapabilities(
            supports_persistent_mode=True,  # Built-in
            supports_parallel_fuzzing=True,
            supports_custom_mutators=True,
            supports_dictionary=True,
            supports_coverage_guided=True,
            supports_crash_analysis=True,
            supports_timeout=True,
            requires_instrumentation=True,
            requires_source_code=True,  # Need to compile with -fsanitize=fuzzer
        )

    def build_command(
        self,
        task: FuzzTask,
        binary_path: Path,
        work_dir: Path
    ) -> List[str]:
        """Build LibFuzzer command line"""
        cmd = [str(binary_path)]

        # Corpus directory
        corpus_dir = task.corpus_dir or work_dir / "corpus"
        corpus_dir.mkdir(exist_ok=True)
        cmd.append(str(corpus_dir))

        # Additional corpus directories
        if task.input_dir and task.input_dir.exists():
            cmd.append(str(task.input_dir))

        # LibFuzzer flags
        config = task.fuzzer_config

        # Basic options
        if task.timeout_seconds:
            cmd.append(f"-max_total_time={task.timeout_seconds}")

        if config.get("max_len"):
            cmd.append(f"-max_len={config['max_len']}")

        if config.get("runs", 0) > 0:
            cmd.append(f"-runs={config['runs']}")

        # Memory limit
        if task.memory_limit_mb:
            cmd.append(f"-rss_limit_mb={task.memory_limit_mb}")

        # Dictionary
        if "dictionary" in config:
            cmd.append(f"-dict={config['dictionary']}")

        # Parallelism
        if config.get("workers"):
            cmd.append(f"-workers={config['workers']}")
            cmd.append(f"-jobs={config['workers']}")

        # Fuzzing strategy
        if config.get("only_ascii"):
            cmd.append("-only_ascii=1")

        if config.get("mutate_depth"):
            cmd.append(f"-mutate_depth={config['mutate_depth']}")

        # Corpus control
        if config.get("reduce_inputs", True):
            cmd.append("-reduce_inputs=1")

        if config.get("minimize_crash", True):
            cmd.append("-minimize_crash=1")

        # Artifacts
        artifact_dir = work_dir / "artifacts"
        artifact_dir.mkdir(exist_ok=True)
        cmd.append(f"-artifact_prefix={artifact_dir}/")

        # Logging
        if config.get("verbosity", 1) > 0:
            cmd.append(f"-verbosity={config['verbosity']}")

        if config.get("print_stats"):
            cmd.append("-print_stats=1")

        if config.get("print_coverage"):
            cmd.append("-print_coverage=1")

        return cmd

    def get_metric_provider(
        self,
        work_dir: Path,
        task: FuzzTask
    ) -> MetricProvider:
        """Get LibFuzzer metric provider"""
        log_file = work_dir / "fuzzer.log"
        return LibFuzzerMetricProvider(log_file)

    def validate_setup(
        self,
        binary_path: Path,
        work_dir: Path
    ) -> Tuple[bool, Optional[str]]:
        """Validate LibFuzzer setup"""
        # Check binary exists
        if not binary_path.exists():
            return False, f"Binary not found: {binary_path}"

        # Check if binary is LibFuzzer-enabled
        try:
            # Run with -help to check if it's a LibFuzzer binary
            result = subprocess.run(
                [str(binary_path), "-help=1"],
                capture_output=True,
                text=True,
                timeout=5
            )

            if "libFuzzer" not in result.stdout:
                return False, "Binary does not appear to be built with LibFuzzer"

        except subprocess.TimeoutExpired:
            return False, "Binary timeout on -help (not a LibFuzzer binary?)"
        except Exception as e:
            return False, f"Failed to validate binary: {e}"

        # Create corpus directory
        corpus_dir = work_dir / "corpus"
        corpus_dir.mkdir(exist_ok=True)

        return True, None

    def prepare_corpus(
        self,
        input_dir: Path,
        corpus_dir: Path,
        task: FuzzTask
    ) -> None:
        """Prepare LibFuzzer corpus"""
        # Copy initial seeds
        if input_dir.exists() and input_dir != corpus_dir:
            for seed_file in input_dir.glob("*"):
                if seed_file.is_file():
                    shutil.copy2(seed_file, corpus_dir / seed_file.name)

        # LibFuzzer can merge and minimize corpus
        if task.fuzzer_config.get("merge_corpus", False):
            self._merge_corpus(corpus_dir, task)

    def _merge_corpus(self, corpus_dir: Path, task: FuzzTask) -> None:
        """Merge corpus using LibFuzzer"""
        console.log("[cyan]Merging corpus...[/cyan]")

        merged_dir = corpus_dir.parent / "corpus_merged"
        merged_dir.mkdir(exist_ok=True)

        cmd = task.command.copy() if isinstance(task.command, list) else [task.command]
        cmd.extend([
            "-merge=1",
            str(merged_dir),
            str(corpus_dir)
        ])

        try:
            subprocess.run(cmd, check=True, timeout=300)

            # Replace original with merged
            shutil.rmtree(corpus_dir)
            shutil.move(str(merged_dir), str(corpus_dir))

            console.log("[green]Corpus merged successfully[/green]")
        except Exception as e:
            console.log(f"[yellow]Corpus merge failed:[/yellow] {e}")

    def analyze_crash(
        self,
        crash_file: Path,
        binary_path: Path,
        work_dir: Path
    ) -> Dict[str, Any]:
        """Analyze crash using LibFuzzer"""
        analysis = {
            "crash_file": str(crash_file),
            "file_size": crash_file.stat().st_size,
        }

        # Run crash through binary to get stack trace
        try:
            result = subprocess.run(
                [str(binary_path), str(crash_file)],
                capture_output=True,
                text=True,
                timeout=10
            )

            analysis["stdout"] = result.stdout
            analysis["stderr"] = result.stderr
            analysis["return_code"] = result.returncode

            # Parse sanitizer output
            if "ERROR: AddressSanitizer" in result.stderr:
                analysis["crash_type"] = "ASAN"
            elif "ERROR: MemorySanitizer" in result.stderr:
                analysis["crash_type"] = "MSAN"
            elif "ERROR: UndefinedBehaviorSanitizer" in result.stderr:
                analysis["crash_type"] = "UBSAN"
            elif "ERROR: ThreadSanitizer" in result.stderr:
                analysis["crash_type"] = "TSAN"
            else:
                analysis["crash_type"] = "UNKNOWN"

        except subprocess.TimeoutExpired:
            analysis["error"] = "Timeout analyzing crash"
        except Exception as e:
            analysis["error"] = str(e)

        return analysis

    def get_environment(self, task: FuzzTask) -> Dict[str, str]:
        """Get LibFuzzer environment variables"""
        env = super().get_environment(task)

        config = task.fuzzer_config

        # Sanitizer options
        if config.get("asan_options"):
            env["ASAN_OPTIONS"] = config["asan_options"]
        else:
            env["ASAN_OPTIONS"] = "abort_on_error=1:symbolize=1:detect_leaks=0"

        if config.get("ubsan_options"):
            env["UBSAN_OPTIONS"] = config["ubsan_options"]
        else:
            env["UBSAN_OPTIONS"] = "halt_on_error=1:abort_on_error=1:symbolize=1"

        if config.get("msan_options"):
            env["MSAN_OPTIONS"] = config["msan_options"]

        # LibFuzzer options
        if config.get("libfuzzer_extra_counters"):
            env["LIBFUZZER_EXTRA_COUNTERS"] = "1"

        return env
