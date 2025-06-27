"""Base adapter interface for fuzzing tools"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..core.task import FuzzTask
from ..monitoring.metrics import MetricProvider


@dataclass
class FuzzerCapabilities:
    """Capabilities of a fuzzer"""
    supports_persistent_mode: bool = False
    supports_parallel_fuzzing: bool = False
    supports_custom_mutators: bool = False
    supports_dictionary: bool = False
    supports_coverage_guided: bool = True
    supports_crash_analysis: bool = True
    supports_timeout: bool = True
    requires_instrumentation: bool = True
    requires_source_code: bool = False


class FuzzerAdapter(ABC):
    """
    Abstract base class for fuzzer adapters.

    Adapters provide a unified interface for different fuzzing tools,
    handling command generation, output parsing, and metric collection.
    """

    def __init__(self):
        self.capabilities = self.get_capabilities()

    @abstractmethod
    def get_capabilities(self) -> FuzzerCapabilities:
        """Get fuzzer capabilities"""
        pass

    @abstractmethod
    def build_command(
        self,
        task: FuzzTask,
        binary_path: Path,
        work_dir: Path
    ) -> List[str]:
        """
        Build fuzzer command line.

        Args:
            task: Fuzzing task configuration
            binary_path: Path to target binary
            work_dir: Working directory for fuzzer output

        Returns:
            Command line as list of arguments
        """
        pass

    @abstractmethod
    def get_metric_provider(
        self,
        work_dir: Path,
        task: FuzzTask
    ) -> MetricProvider:
        """
        Get metric provider for this fuzzer.

        Args:
            work_dir: Fuzzer working directory
            task: Fuzzing task

        Returns:
            MetricProvider instance
        """
        pass

    @abstractmethod
    def validate_setup(
        self,
        binary_path: Path,
        work_dir: Path
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate fuzzer setup.

        Returns:
            (is_valid, error_message)
        """
        pass

    @abstractmethod
    def prepare_corpus(
        self,
        input_dir: Path,
        corpus_dir: Path,
        task: FuzzTask
    ) -> None:
        """
        Prepare initial corpus for fuzzing.

        Args:
            input_dir: Directory with seed inputs
            corpus_dir: Directory for fuzzer corpus
            task: Fuzzing task configuration
        """
        pass

    @abstractmethod
    def analyze_crash(
        self,
        crash_file: Path,
        binary_path: Path,
        work_dir: Path
    ) -> Dict[str, Any]:
        """
        Analyze a crash file.

        Returns:
            Crash analysis results
        """
        pass

    def get_environment(self, task: FuzzTask) -> Dict[str, str]:
        """Get environment variables for fuzzer"""
        return task.fuzzer_config.get('env', {})

    def supports_feature(self, feature: str) -> bool:
        """Check if fuzzer supports a feature"""
        return getattr(self.capabilities, f"supports_{feature}", False)

    def post_process_results(
        self,
        work_dir: Path,
        task: FuzzTask
    ) -> Dict[str, Any]:
        """
        Post-process fuzzing results.

        Returns:
            Processed results dictionary
        """
        return {
            "crashes": self.find_crashes(work_dir),
            "corpus_size": self.get_corpus_size(work_dir),
        }

    def find_crashes(self, work_dir: Path) -> List[Path]:
        """Find crash files in work directory"""
        crashes = []

        # Common crash directory names
        for crash_dir_name in ['crashes', 'crash', 'failures']:
            crash_dir = work_dir / crash_dir_name
            if crash_dir.exists():
                crashes.extend(crash_dir.glob('*'))

        return crashes

    def get_corpus_size(self, work_dir: Path) -> int:
        """Get corpus size"""
        # Common corpus directory names
        for corpus_dir_name in ['corpus', 'queue', 'inputs']:
            corpus_dir = work_dir / corpus_dir_name
            if corpus_dir.exists():
                return len(list(corpus_dir.glob('*')))

        return 0
