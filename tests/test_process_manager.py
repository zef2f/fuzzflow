import pytest
from unittest.mock import patch, MagicMock, call
import subprocess
import time
from src.process_manager import ProcessManager


@pytest.fixture
def process_manager():
    return ProcessManager(single_fuzz_script="test_fuzz.py")


@pytest.fixture
def mock_process():
    process = MagicMock()
    process.pid = 12345
    process.poll.return_value = None
    process.stdout = MagicMock()
    process.stderr = MagicMock()
    return process


def test_process_manager_initialization(process_manager):
    """Тест корректной инициализации ProcessManager"""
    assert process_manager.single_fuzz_script == "test_fuzz.py"


@patch("subprocess.Popen")
def test_start_fuzzing_success(mock_popen, process_manager, mock_process):
    """Тест успешного запуска процесса фаззинга"""
    mock_popen.return_value = mock_process

    result = process_manager.start_fuzzing("test_harness")

    # Проверяем, что Popen был вызван с правильными параметрами
    mock_popen.assert_called_once_with(
        ["test_fuzz.py", "test_harness"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    # Проверяем структуру возвращаемого результата
    assert result is not None
    assert result["harness_name"] == "test_harness"
    assert result["process"] == mock_process
    assert "start_time" in result
    assert isinstance(result["start_time"], float)


@patch("subprocess.Popen")
def test_start_fuzzing_failure(mock_popen, process_manager):
    """Тест неудачного запуска процесса фаззинга"""
    mock_popen.side_effect = Exception("Failed to start process")

    result = process_manager.start_fuzzing("test_harness")

    assert result is None


@patch("time.sleep")
def test_kill_fuzzing_success(mock_sleep, process_manager, mock_process):
    """Тест успешного завершения процесса"""
    proc_info = {"process": mock_process, "harness_name": "test_harness"}

    # Симулируем успешное завершение после terminate
    mock_process.poll.side_effect = [None, 0]

    process_manager.kill_fuzzing(proc_info)

    # Проверяем, что были вызваны правильные методы
    mock_process.terminate.assert_called_once()
    mock_sleep.assert_called_once_with(5)
    mock_process.kill.assert_not_called()


@patch("time.sleep")
def test_kill_fuzzing_force_kill(mock_sleep, process_manager, mock_process):
    """Тест принудительного завершения процесса"""
    proc_info = {"process": mock_process, "harness_name": "test_harness"}

    # Симулируем, что процесс не завершился после terminate
    mock_process.poll.side_effect = [None, None]

    process_manager.kill_fuzzing(proc_info)

    # Проверяем, что был вызван kill после неудачного terminate
    mock_process.terminate.assert_called_once()
    mock_sleep.assert_called_once_with(5)
    mock_process.kill.assert_called_once()


def test_kill_fuzzing_already_terminated(process_manager, mock_process):
    """Тест попытки завершить уже завершенный процесс"""
    proc_info = {"process": mock_process, "harness_name": "test_harness"}

    # Симулируем уже завершенный процесс
    mock_process.poll.return_value = 0

    process_manager.kill_fuzzing(proc_info)

    # Проверяем, что методы завершения не были вызваны
    mock_process.terminate.assert_not_called()
    mock_process.kill.assert_not_called()


@patch("subprocess.Popen")
def test_start_fuzzing_with_empty_harness(
    mock_popen, process_manager, mock_process
):
    """Тест запуска процесса с пустым именем обертки"""
    mock_popen.return_value = mock_process

    result = process_manager.start_fuzzing("")

    # Проверяем, что Popen был вызван с пустым именем обертки
    mock_popen.assert_called_once_with(
        ["test_fuzz.py", ""],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    assert result is not None
    assert result["harness_name"] == ""


def test_kill_fuzzing_with_invalid_proc_info(process_manager):
    """Тест попытки завершить процесс с некорректной информацией"""
    # Передаем некорректную информацию о процессе
    proc_info = {"invalid_key": "invalid_value"}

    # Проверяем, что метод не вызывает исключение
    process_manager.kill_fuzzing(proc_info)


@patch("subprocess.Popen")
def test_start_fuzzing_with_special_characters(
    mock_popen, process_manager, mock_process
):
    """Тест запуска процесса с специальными символами в имени обертки"""
    mock_popen.return_value = mock_process

    special_harness = "test@#$%^&*()_+"
    result = process_manager.start_fuzzing(special_harness)

    # Проверяем, что Popen был вызван с правильными параметрами
    mock_popen.assert_called_once_with(
        ["test_fuzz.py", special_harness],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    assert result is not None
    assert result["harness_name"] == special_harness
