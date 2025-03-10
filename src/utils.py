# -*- coding: utf-8 -*-

import os
import glob
import json
import psutil
import argparse

def parse_cli_args():
    """
    Парсит аргументы командной строки.
    Возвращает объект с полями:
      wrapper_names (str - json формат) – список оберток в json формате;
      memory_limit (int) – лимит памяти (в MB);
      single_fuzz_script (str) – путь к скрипту для запуска одного фаззинга.
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
    Проверяет, превышено ли текущее использование памяти заданный лимит (в MB).
    Возвращает True, если используется > memory_limit_mb.
    """
    mem_info = psutil.virtual_memory()
    used_mb = mem_info.used // (1024 * 1024)
    return used_mb > memory_limit_mb
