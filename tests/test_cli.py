import pytest
from unittest.mock import patch, MagicMock
from cli import main

@pytest.fixture
def mock_cli_args():
    return MagicMock(
        wrapper_names='["wrapper1", "wrapper2"]',
        memory_limit=1024,
        single_fuzz_script='test_script.py'
    )

def test_main_function_success(mock_cli_args):
    """Тест успешного запуска main()"""
    with patch('src.utils.parse_cli_args', return_value=mock_cli_args), \
         patch('src.orchestrator.Orchestrator') as mock_orchestrator:
        
        # Вызываем main()
        main()
        
        # Проверяем, что Orchestrator был создан с правильными параметрами
        mock_orchestrator.assert_called_once_with(
            wrapper_names=mock_cli_args.wrapper_names,
            memory_limit=mock_cli_args.memory_limit,
            single_fuzz_script=mock_cli_args.single_fuzz_script
        )
        
        # Проверяем, что run() был вызван
        mock_orchestrator.return_value.run.assert_called_once()

def test_main_function_error_handling(mock_cli_args):
    """Тест обработки ошибок в main()"""
    with patch('src.utils.parse_cli_args', return_value=mock_cli_args), \
         patch('src.orchestrator.Orchestrator') as mock_orchestrator, \
         patch('sys.exit') as mock_exit:
        
        # Симулируем ошибку в Orchestrator
        mock_orchestrator.return_value.run.side_effect = Exception("Test error")
        
        # Вызываем main()
        main()
        
        # Проверяем, что произошел выход с кодом 1
        mock_exit.assert_called_once_with(1)

def test_parse_cli_args_missing_required():
    """Тест отсутствия обязательных аргументов"""
    from src.utils import parse_cli_args
    
    with patch('sys.argv', ['fuzzflow.py']), \
         pytest.raises(SystemExit):
        parse_cli_args()

def test_parse_cli_args_invalid_json():
    """Тест некорректного JSON в wrapper_names"""
    from src.utils import parse_cli_args
    
    with patch('sys.argv', [
        'fuzzflow.py',
        '--wrapper-names', 'invalid json',
        '--memory-limit', '1024',
        '--single-fuzz-script', 'test_script.py'
    ]), \
         pytest.raises(SystemExit):
        parse_cli_args()

def test_parse_cli_args_invalid_memory():
    """Тест некорректного значения memory_limit"""
    from src.utils import parse_cli_args
    
    with patch('sys.argv', [
        'fuzzflow.py',
        '--wrapper-names', '["wrapper1"]',
        '--memory-limit', '-1',
        '--single-fuzz-script', 'test_script.py'
    ]), \
         pytest.raises(SystemExit):
        parse_cli_args()

def test_parse_cli_args_missing_script():
    """Тест отсутствия single_fuzz_script"""
    from src.utils import parse_cli_args
    
    with patch('sys.argv', [
        'fuzzflow.py',
        '--wrapper-names', '["wrapper1"]',
        '--memory-limit', '1024'
    ]), \
         pytest.raises(SystemExit):
        parse_cli_args()

def test_parse_cli_args_valid():
    """Тест корректных аргументов"""
    from src.utils import parse_cli_args
    
    with patch('sys.argv', [
        'fuzzflow.py',
        '--wrapper-names', '["wrapper1", "wrapper2"]',
        '--memory-limit', '1024',
        '--single-fuzz-script', 'test_script.py'
    ]):
        args = parse_cli_args()
        
        assert args.wrapper_names == '["wrapper1", "wrapper2"]'
        assert args.memory_limit == 1024
        assert args.single_fuzz_script == 'test_script.py'
