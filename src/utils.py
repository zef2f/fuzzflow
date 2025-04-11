import os
import glob
import json
import psutil
import argparse
import logging

DEFAULT_WAIT_TIME_SECONDS = 60

def parse_cli_args():
    parser = argparse.ArgumentParser(description='Fuzzflow CLI')
    parser.add_argument('-w', '--wrapper_names', required=True, help='JSON list of wrapper names')
    parser.add_argument('-m', '--memory_limit', type=int, required=True, help='Memory limit in MB')
    parser.add_argument('-s', '--single_fuzz_script', required=True, help='Script to run a single fuzzing process')
    parser.add_argument('-t', '--wait_time', type=int, default=DEFAULT_WAIT_TIME_SECONDS, help='Wait time in seconds')
    return parser.parse_args()

def over_memory_threshold(memory_limit_mb):
    mem_info = psutil.virtual_memory()
    used_mb = mem_info.used // (1024 * 1024)
    return used_mb > (memory_limit_mb * 0.8)

def get_total_subprocess_memory(pids):
    total_rss = 0
    for pid in pids:
        try:
            parent = psutil.Process(pid)
            children = parent.children(recursive=True)
            all_procs = [parent] + children

            for p in all_procs:
                mem = p.memory_info().rss
                total_rss += mem

        except psutil.NoSuchProcess:
            continue

    total_mb = total_rss // (1024 * 1024)
    logging.debug(f"Total memory usage of monitored subprocess trees: {total_mb} MB")
    return total_mb
