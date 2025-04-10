import os
import glob
import json
import psutil
import argparse

DEFAULT_WAIT_TIME_SECONDS = 60

def parse_cli_args():
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
    parser.add_argument(
        '-t', '--wait_time',
        type=int,
        default=DEFAULT_WAIT_TIME_SECONDS,
        help='Wait time between operations in seconds.'
    )

    return parser.parse_args()

def over_memory_threshold(memory_limit_mb):
    mem_info = psutil.virtual_memory()
    used_mb = mem_info.used // (1024 * 1024)
    # 80% logic: if we exceed 80% of allocated memory, return true
    return used_mb > (memory_limit_mb * 0.8)
