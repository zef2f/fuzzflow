"""AFL++ adapter implementation"""

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from rich.console import Console

from ..core.task import FuzzTask
from ..monitoring.metrics import AFLMetricProvider, MetricProvider
from .base import FuzzerAdapter, FuzzerCapabilities


console = Console()


class AFLAdapter(FuzzerAdapter):
    """Adapter for AFL++ fuzzer"""

    def __init__(self, afl_path: Optional[Path] = None):
        super().__init__()
        self.afl_path = afl_path or self._find_afl_path()

    def _find_afl_path(self) -> Path:
        """Find AFL++ installation path"""
        # Check common locations
        paths = [
            Path("/usr/local/bin"),
            Path("/usr/bin"),
            Path.home() / "AFL",
            Path.home() / "AFLplusplus",
        ]

        for path in paths:
            if (path / "afl-fuzz").exists():
                return path

        # Check PATH
        afl_fuzz = shutil.which("afl-fuzz")
        if afl_fuzz:
            return Path(afl_fuzz).parent

        raise RuntimeError("AFL++ not found. Please install AFL++ or specify path.")

    def get_capabilities(self) -> FuzzerCapabilities:
        """Get AFL++ capabilities"""
        return FuzzerCapabilities(
            supports_persistent_mode=True,
            supports_parallel_fuzzing=True,
            supports_custom_mutators=True,
            supports_dictionary=True,
            supports_coverage_guided=True,
            supports_crash_analysis=True,
            supports_timeout=True,
            requires_instrumentation=True,
            requires_source_code=False,
        )

    def build_command(
        self,
        task: FuzzTask,
        binary_path: Path,
        work_dir: Path
    ) -> List[str]:
        """Build AFL++ command line"""
        cmd = [str(self.afl_path / "afl-fuzz")]

        # Input/output directories
        input_dir = task.input_dir or work_dir / "input"
        output_dir = work_dir / "output"

        cmd.extend(["-i", str(input_dir)])
        cmd.extend(["-o", str(output_dir)])

        # Memory limit
        if task.memory_limit_mb:
            cmd.extend(["-m", str(task.memory_limit_mb)])
        else:
            cmd.extend(["-m", "none"])

        # Timeout
        if task.timeout_seconds:
            timeout_ms = task.timeout_seconds * 1000
            cmd.extend(["-t", str(timeout_ms)])

        # AFL++ specific options from config
        config = task.fuzzer_config

        # Dictionary
        if "dictionary" in config:
            cmd.extend(["-x", str(config["dictionary"])])

        # AFL++ mode
        if config.get("mode"):
            cmd.extend(["-P", config["mode"]])

        # Deterministic mode
        if config.get("skip_deterministic", False):
            cmd.append("-d")

        # CPU affinity
        if "cpu_affinity" in config:
            cmd.extend(["-b", str(config["cpu_affinity"])])

        # Master/slave mode for parallel fuzzing
        if config.get("fuzzer_id"):
            cmd.extend(["-S", config["fuzzer_id"]])
        elif config.get("is_master", True):
            cmd.extend(["-M", "master"])

        # Custom mutator
        if "custom_mutator" in config:
            cmd.extend(["-l", str(config["custom_mutator"])])

        # Power schedule
        if "power_schedule" in config:
            cmd.extend(["-p", config["power_schedule"]])

        # Add binary and arguments
        cmd.append("--")
        cmd.append(str(binary_path))

        # Binary arguments with @@ for input file
        if "binary_args" in config:
            cmd.extend(config["binary_args"])
        else:
            cmd.append("@@")

        return cmd

    def get_metric_provider(
        self,
        work_dir: Path,
        task: FuzzTask
    ) -> MetricProvider:
        """Get AFL++ metric provider"""
        output_dir = work_dir / "output"

        # Find fuzzer stats file
        if task.fuzzer_config.get("fuzzer_id"):
            stats_file = output_dir / task.fuzzer_config["fuzzer_id"] / "fuzzer_stats"
        elif task.fuzzer_config.get("is_master", True):
            stats_file = output_dir / "master" / "fuzzer_stats"
        else:
            # Find first stats file
            stats_files = list(output_dir.glob("*/fuzzer_stats"))
            stats_file = stats_files[0] if stats_files else output_dir / "fuzzer_stats"

        return AFLMetricProvider(stats_file)

    def validate_setup(
        self,
        binary_path: Path,
        work_dir: Path
    ) -> Tuple[bool, Optional[str]]:
        """Validate AFL++ setup"""
        # Check AFL++ installation
        if not (self.afl_path / "afl-fuzz").exists():
            return False, f"afl-fuzz not found at {self.afl_path}"

        # Check binary exists
        if not binary_path.exists():
            return False, f"Binary not found: {binary_path}"

        # Check if binary is instrumented
        try:
            result = subprocess.run(
                ["file", str(binary_path)],
                capture_output=True,
                text=True
            )

            # Simple heuristic - instrumented binaries are usually larger
            if binary_path.stat().st_size < 50000:  # Less than 50KB
                console.log("[yellow]Warning:[/yellow] Binary seems small, might not be instrumented")
        except:
            pass

        # Check input directory
        input_dir = work_dir / "input"
        if not input_dir.exists():
            input_dir.mkdir(parents=True)
            # Create default input
            (input_dir / "default").write_bytes(b"TEST")
            console.log(f"[yellow]Created default input in {input_dir}[/yellow]")

        if not list(input_dir.glob("*")):
            return False, f"No input files found in {input_dir}"

        # Check system settings
        if Path("/proc/sys/kernel/core_pattern").exists():
            core_pattern = Path("/proc/sys/kernel/core_pattern").read_text().strip()
            if core_pattern != "core":
                console.log(
                    "[yellow]Warning:[/yellow] core_pattern is not 'core'. "
                    "Run: echo core | sudo tee /proc/sys/kernel/core_pattern"
                )

        return True, None

    def prepare_corpus(
        self,
        input_dir: Path,
        corpus_dir: Path,
        task: FuzzTask
    ) -> None:
        """Prepare AFL++ corpus"""
        # AFL++ uses -i directory as corpus
        if input_dir != corpus_dir:
            shutil.copytree(input_dir, corpus_dir, dirs_exist_ok=True)

        # Minimize corpus if requested
        if task.fuzzer_config.get("minimize_corpus", False):
            self._minimize_corpus(corpus_dir, task)

    def _minimize_corpus(self, corpus_dir: Path, task: FuzzTask) -> None:
        """Minimize corpus using afl-cmin"""
        console.log("[cyan]Minimizing corpus...[/cyan]")

        minimized_dir = corpus_dir.parent / "corpus_minimized"
        minimized_dir.mkdir(exist_ok=True)

        cmd = [
            str(self.afl_path / "afl-cmin"),
            "-i", str(corpus_dir),
            "-o", str(minimized_dir),
        ]

        if task.memory_limit_mb:
            cmd.extend(["-m", str(task.memory_limit_mb)])

        if task.timeout_seconds:
            cmd.extend(["-t", str(task.timeout_seconds * 1000)])

        cmd.append("--")
        cmd.extend(task.command)  # Use task command as target

        try:
            subprocess.run(cmd, check=True)

            # Replace original with minimized
            shutil.rmtree(corpus_dir)
            shutil.move(str(minimized_dir), str(corpus_dir))

            console.log("[green]Corpus minimized successfully[/green]")
        except subprocess.CalledProcessError as e:
            console.log(f"[yellow]Corpus minimization failed:[/yellow] {e}")

    def analyze_crash(
        self,
        crash_file: Path,
        binary_path: Path,
        work_dir: Path
    ) -> Dict[str, Any]:
        """Analyze crash using AFL++ tools"""
        analysis = {
            "crash_file": str(crash_file),
            "file_size": crash_file.stat().st_size,
        }

        # Get crash info from filename (AFL++ format)
        # Example: id:000000,sig:11,src:000000,op:flip1,pos:0
        parts = crash_file.name.split(',')
        for part in parts:
            if ':' in part:
                key, value = part.split(':', 1)
                analysis[key] = value

        # Run through afl-analyze if available
        if (self.afl_path / "afl-analyze").exists():
            try:
                result = subprocess.run(
                    [
                        str(self.afl_path / "afl-analyze"),
                        "-i", str(crash_file),
                        "--", str(binary_path), "@@"
                    ],
                    capture_output=True,
                    text=True,
                    timeout=10
                )

                analysis["afl_analyze"] = result.stdout

            except Exception as e:
                analysis["analyze_error"] = str(e)

        return analysis

    def get_environment(self, task: FuzzTask) -> Dict[str, str]:
        """Get AFL++ environment variables"""
        env = super().get_environment(task)

        # AFL++ specific environment
        config = task.fuzzer_config

        # AFL++ options
        if config.get("no_affinity"):
            env["AFL_NO_AFFINITY"] = "1"

        if config.get("skip_crashes"):
            env["AFL_SKIP_CRASHES"] = "1"

        if config.get("hang_timeout"):
            env["AFL_HANG_TMOUT"] = str(config["hang_timeout"])

        if config.get("map_size"):
            env["AFL_MAP_SIZE"] = str(config["map_size"])

        # Persistent mode
        if config.get("persistent_mode"):
            env["AFL_PERSISTENT"] = "1"

        # Custom mutator
        if config.get("python_module"):
            env["AFL_PYTHON_MODULE"] = str(config["python_module"])

        return env
