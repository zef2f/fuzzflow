import pytest
from unittest.mock import patch, MagicMock
import threading
import psutil
from src.resource_monitor import ResourceMonitor

@pytest.fixture
def resource_monitor():
    """Фикстура для создания экземпляра ResourceMonitor"""
    return ResourceMonitor(memory_limit=1000)

@pytest.fixture
def mock_virtual_memory():
    """Фикстура для создания мока virtual_memory"""
    mock = MagicMock()
    mock.used = 500 * 1024 * 1024  # 500 MB в байтах
    return mock

def test_resource_monitor_initialization(resource_monitor):
    """Тест корректной инициализации ResourceMonitor"""
    assert resource_monitor.memory_limit == 1000
    assert not resource_monitor.running
    assert resource_monitor.monitor_thread is None
    assert isinstance(resource_monitor.processes_to_kill, list)
    assert len(resource_monitor.processes_to_kill) == 0

def test_start_monitor(resource_monitor):
    """Тест запуска мониторинга"""
    with patch('threading.Thread') as mock_thread:
        resource_monitor.start()
        
        # Проверяем, что поток был создан с правильными параметрами
        mock_thread.assert_called_once_with(
            target=resource_monitor._monitor_loop,
            daemon=True
        )
        
        # Проверяем, что поток был запущен
        mock_thread.return_value.start.assert_called_once()
        
        # Проверяем состояние монитора
        assert resource_monitor.running
        assert resource_monitor.monitor_thread is not None

def test_start_monitor_already_running(resource_monitor):
    """Тест попытки запуска уже запущенного мониторинга"""
    with patch('threading.Thread') as mock_thread:
        # Первый запуск
        resource_monitor.start()
        first_thread = resource_monitor.monitor_thread
        
        # Второй запуск
        resource_monitor.start()
        
        # Проверяем, что второй раз поток не создавался
        assert mock_thread.call_count == 1
        assert resource_monitor.monitor_thread == first_thread

def test_stop_monitor(resource_monitor):
    """Тест остановки мониторинга"""
    # Создаем мок для потока
    mock_thread = MagicMock()
    resource_monitor.monitor_thread = mock_thread
    resource_monitor.running = True
    
    # Останавливаем монитор
    resource_monitor.stop()
    
    # Проверяем, что поток был остановлен корректно
    assert not resource_monitor.running
    mock_thread.join.assert_called_once()
    assert resource_monitor.monitor_thread is None

def test_stop_monitor_not_running(resource_monitor):
    """Тест остановки неработающего мониторинга"""
    resource_monitor.stop()
    assert not resource_monitor.running
    assert resource_monitor.monitor_thread is None

@patch('psutil.virtual_memory')
def test_can_start_new_process_under_limit(mock_virtual_memory, resource_monitor):
    """Тест проверки возможности запуска нового процесса при достаточной памяти"""
    # Устанавливаем использование памяти ниже лимита
    mock_mem = MagicMock()
    mock_mem.used = 500 * 1024 * 1024  # 500 MB
    mock_virtual_memory.return_value = mock_mem
    
    assert resource_monitor.can_start_new_process()

@patch('psutil.virtual_memory')
def test_can_start_new_process_over_limit(mock_virtual_memory, resource_monitor):
    """Тест проверки возможности запуска нового процесса при недостаточной памяти"""
    # Устанавливаем использование памяти выше лимита
    mock_mem = MagicMock()
    mock_mem.used = 1500 * 1024 * 1024  # 1500 MB
    mock_virtual_memory.return_value = mock_mem
    
    assert not resource_monitor.can_start_new_process()

@patch('time.sleep')
@patch('psutil.virtual_memory')
def test_monitor_loop(mock_virtual_memory, mock_sleep, resource_monitor):
    """Тест работы мониторинга в цикле"""
    # Настраиваем мок для памяти
    mock_mem = MagicMock()
    mock_mem.used = 900 * 1024 * 1024  # 900 MB
    mock_virtual_memory.return_value = mock_mem
    
    # Запускаем мониторинг
    resource_monitor.start()
    
    # Даем поработать немного
    import time
    time.sleep(0.1)
    
    # Останавливаем
    resource_monitor.stop()
    
    # Проверяем, что мониторинг работал
    assert mock_virtual_memory.called
    assert mock_sleep.called

@patch('time.sleep')
@patch('psutil.virtual_memory')
def test_monitor_loop_memory_threshold(mock_virtual_memory, mock_sleep, resource_monitor):
    """Тест работы мониторинга при превышении порога памяти"""
    # Настраиваем мок для памяти выше порога (80% от лимита)
    mock_mem = MagicMock()
    mock_mem.used = 850 * 1024 * 1024  # 850 MB (> 80% от 1000 MB)
    mock_virtual_memory.return_value = mock_mem
    
    # Запускаем мониторинг
    resource_monitor.start()
    
    # Даем поработать немного
    import time
    time.sleep(0.1)
    
    # Останавливаем
    resource_monitor.stop()
    
    # Проверяем, что мониторинг работал и проверял память
    assert mock_virtual_memory.called
    assert mock_sleep.called

def test_thread_daemon_status(resource_monitor):
    """Тест проверки статуса daemon у потока мониторинга"""
    resource_monitor.start()
    assert resource_monitor.monitor_thread.daemon

def test_monitor_cleanup(resource_monitor):
    """Тест очистки ресурсов при остановке монитора"""
    resource_monitor.start()
    assert resource_monitor.monitor_thread is not None
    assert resource_monitor.running
    
    resource_monitor.stop()
    assert resource_monitor.monitor_thread is None
    assert not resource_monitor.running
    assert len(resource_monitor.processes_to_kill) == 0 