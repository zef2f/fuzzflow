import pytest
from unittest.mock import patch, MagicMock
import json
import psutil
from src.utils import parse_cli_args, over_memory_threshold

def test_parse_cli_args_all_required():
    """Тест парсинга всех обязательных аргументов"""
    test_args = [
        'script.py',
        '--wrapper_names', '["wrapper1", "wrapper2"]',
        '--memory_limit', '1024',
        '--single_fuzz_script', 'fuzz.py'
    ]
    
    with patch('sys.argv', test_args):
        args = parse_cli_args()
        
        assert args.wrapper_names == '["wrapper1", "wrapper2"]'
        assert args.memory_limit == 1024
        assert args.single_fuzz_script == 'fuzz.py'

def test_parse_cli_args_short_form():
    """Тест парсинга аргументов в короткой форме"""
    test_args = [
        'script.py',
        '-w', '["wrapper1"]',
        '-m', '512',
        '-s', 'fuzz.py'
    ]
    
    with patch('sys.argv', test_args):
        args = parse_cli_args()
        
        assert args.wrapper_names == '["wrapper1"]'
        assert args.memory_limit == 512
        assert args.single_fuzz_script == 'fuzz.py'

def test_parse_cli_args_missing_wrapper_names():
    """Тест отсутствия обязательного аргумента wrapper_names"""
    test_args = [
        'script.py',
        '--memory_limit', '1024',
        '--single_fuzz_script', 'fuzz.py'
    ]
    
    with patch('sys.argv', test_args), \
         pytest.raises(SystemExit):
        parse_cli_args()

def test_parse_cli_args_missing_memory_limit():
    """Тест отсутствия обязательного аргумента memory_limit"""
    test_args = [
        'script.py',
        '--wrapper_names', '["wrapper1"]',
        '--single_fuzz_script', 'fuzz.py'
    ]
    
    with patch('sys.argv', test_args), \
         pytest.raises(SystemExit):
        parse_cli_args()

def test_parse_cli_args_missing_single_fuzz_script():
    """Тест отсутствия обязательного аргумента single_fuzz_script"""
    test_args = [
        'script.py',
        '--wrapper_names', '["wrapper1"]',
        '--memory_limit', '1024'
    ]
    
    with patch('sys.argv', test_args), \
         pytest.raises(SystemExit):
        parse_cli_args()

def test_parse_cli_args_invalid_memory_limit():
    """Тест некорректного значения memory_limit"""
    test_args = [
        'script.py',
        '--wrapper_names', '["wrapper1"]',
        '--memory_limit', 'invalid',
        '--single_fuzz_script', 'fuzz.py'
    ]
    
    with patch('sys.argv', test_args), \
         pytest.raises(SystemExit):
        parse_cli_args()

def test_parse_cli_args_negative_memory_limit():
    """Тест отрицательного значения memory_limit"""
    test_args = [
        'script.py',
        '--wrapper_names', '["wrapper1"]',
        '--memory_limit', '-1024',
        '--single_fuzz_script', 'fuzz.py'
    ]
    
    with patch('sys.argv', test_args):
        args = parse_cli_args()
        assert args.memory_limit == -1024  # argparse не проверяет отрицательные значения

def test_parse_cli_args_invalid_json():
    """Тест некорректного JSON в wrapper_names"""
    test_args = [
        'script.py',
        '--wrapper_names', 'invalid json',
        '--memory_limit', '1024',
        '--single_fuzz_script', 'fuzz.py'
    ]
    
    with patch('sys.argv', test_args):
        args = parse_cli_args()
        # argparse не проверяет валидность JSON, это должно проверяться позже
        assert args.wrapper_names == 'invalid json'

@patch('psutil.virtual_memory')
def test_over_memory_threshold_under_limit(mock_virtual_memory):
    """Тест использования памяти ниже порога"""
    mock_mem = MagicMock()
    mock_mem.used = 500 * 1024 * 1024  # 500 MB
    mock_virtual_memory.return_value = mock_mem
    
    assert not over_memory_threshold(1000)  # 1000 MB limit

@patch('psutil.virtual_memory')
def test_over_memory_threshold_over_limit(mock_virtual_memory):
    """Тест использования памяти выше порога"""
    mock_mem = MagicMock()
    mock_mem.used = 900 * 1024 * 1024  # 900 MB
    mock_virtual_memory.return_value = mock_mem
    
    assert over_memory_threshold(1000)  # 1000 MB limit, порог 80% = 800 MB

@patch('psutil.virtual_memory')
def test_over_memory_threshold_at_limit(mock_virtual_memory):
    """Тест использования памяти на пороге"""
    mock_mem = MagicMock()
    mock_mem.used = 800 * 1024 * 1024  # 800 MB (80% от 1000 MB)
    mock_virtual_memory.return_value = mock_mem
    
    assert not over_memory_threshold(1000)  # На пороге должно быть False

@patch('psutil.virtual_memory')
def test_over_memory_threshold_zero_limit(mock_virtual_memory):
    """Тест с нулевым лимитом памяти"""
    mock_mem = MagicMock()
    mock_mem.used = 100 * 1024 * 1024  # 100 MB
    mock_virtual_memory.return_value = mock_mem
    
    assert over_memory_threshold(0)  # Любое ненулевое использование должно быть over limit

@patch('psutil.virtual_memory')
def test_over_memory_threshold_negative_limit(mock_virtual_memory):
    """Тест с отрицательным лимитом памяти"""
    mock_mem = MagicMock()
    mock_mem.used = 100 * 1024 * 1024  # 100 MB
    mock_virtual_memory.return_value = mock_mem
    
    assert over_memory_threshold(-1000)  # Отрицательный лимит должен всегда давать True 