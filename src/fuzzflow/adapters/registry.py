"""Fuzzer adapter registry"""

from typing import Dict, Optional, Type

from .base import FuzzerAdapter
from .afl import AFLAdapter
from .libfuzzer import LibFuzzerAdapter


class FuzzerRegistry:
    """Registry for fuzzer adapters"""

    _adapters: Dict[str, Type[FuzzerAdapter]] = {
        "afl": AFLAdapter,
        "afl++": AFLAdapter,
        "aflplusplus": AFLAdapter,
        "libfuzzer": LibFuzzerAdapter,
    }

    @classmethod
    def register(cls, name: str, adapter_class: Type[FuzzerAdapter]) -> None:
        """Register a new fuzzer adapter"""
        cls._adapters[name.lower()] = adapter_class

    @classmethod
    def get(cls, name: str) -> Optional[Type[FuzzerAdapter]]:
        """Get adapter class by name"""
        return cls._adapters.get(name.lower())

    @classmethod
    def list_adapters(cls) -> list[str]:
        """List available adapter names"""
        return list(cls._adapters.keys())


def get_adapter(fuzzer_type: str, **kwargs) -> FuzzerAdapter:
    """
    Get fuzzer adapter instance.

    Args:
        fuzzer_type: Type of fuzzer (afl, libfuzzer, etc.)
        **kwargs: Arguments passed to adapter constructor

    Returns:
        FuzzerAdapter instance

    Raises:
        ValueError: If fuzzer type is not supported
    """
    adapter_class = FuzzerRegistry.get(fuzzer_type)

    if not adapter_class:
        available = ", ".join(FuzzerRegistry.list_adapters())
        raise ValueError(
            f"Unsupported fuzzer type: {fuzzer_type}. "
            f"Available: {available}"
        )

    return adapter_class(**kwargs)
