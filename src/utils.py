# -*- coding: utf-8 -*-

import os
import glob
import json
import psutil
import argparse

def parse_cli_args():
    """
    Parse command line arguments.
    Returns an object with fields:
      wrapper_names (str - json format) – list of wrappers in json format;
      memory_limit (int) – memory limit (in MB);
      single_fuzz_script (str) – path to the script that runs a single fuzzing process.
    """
    parser = argparse.ArgumentParser(
        description='Fuzzflow orchestrator CLI arguments'
    )
    parser.add_argument(
        '-w', '--wrapper_names',
        required=True,
        help='String with JSON format contained wrapper names.'
    )
    parser.add_argument(
        '-m', '--memory_limit',
        type=int,
        required=True,
        help='Memory limit in MB.'
    )
    parser.add_argument(
        '-s', '--single_fuzz_script',
        required=True,
        help='Path to the script that runs a single fuzzing process.'
    )

    return parser.parse_args()

def over_memory_threshold(memory_limit_mb):
    """
    Check if current memory usage exceeds the specified limit (in MB).
    Returns True if usage > memory_limit_mb.
    """
    mem_info = psutil.virtual_memory()
    used_mb = mem_info.used // (1024 * 1024)
    # 80% logic: if we exceed 80% of allocated memory, return true
    return used_mb > (memory_limit_mb * 0.8)
