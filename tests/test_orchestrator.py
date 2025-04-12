import pytest
from unittest.mock import Mock, patch, MagicMock
import json
from src.orchestrator import Orchestrator
from src.utils import DEFAULT_WAIT_TIME_SECONDS


@pytest.fixture
def mock_harness_names():
    return json.dumps(["harness1", "harness2"])


@pytest.fixture
def mock_process():
    process = MagicMock()
    process.pid = 12345
    process.poll.return_value = None
    return process


@pytest.fixture
def mock_proc_info(mock_process):
    return {"process": mock_process, "harness": "harness1"}


@pytest.fixture
def orchestrator(mock_harness_names):
    with patch(
        "src.orchestrator.ResourceMonitor"
    ) as mock_resource_monitor, patch(
        "src.orchestrator.ProcessManager"
    ) as mock_process_manager, patch(
        "src.orchestrator.ResultCollector"
    ) as mock_result_collector:

        # Настраиваем моки
        mock_resource_monitor.return_value.can_start_new_process.return_value = (
            True
        )
        mock_process_manager.return_value.start_fuzzing.return_value = {
            "process": mock_process
        }
        mock_result_collector.return_value.collect.return_value = None

        orchestrator = Orchestrator(
            harness_names=mock_harness_names,
            memory_limit=1000,
            single_fuzz_script="test_script.py",
        )
        return orchestrator


def test_orchestrator_initialization(orchestrator, mock_harness_names):
    """Тест корректной инициализации Orchestrator"""
    assert orchestrator.harness_names == mock_harness_names
    assert orchestrator.memory_limit == 1000
    assert orchestrator.single_fuzz_script == "test_script.py"
    assert orchestrator.wait_time == DEFAULT_WAIT_TIME_SECONDS
    assert orchestrator.active_tasks == []


def test_orchestrator_custom_wait_time(mock_harness_names):
    """Тест инициализации Orchestrator с пользовательским временем ожидания"""
    with patch(
        "src.orchestrator.ResourceMonitor"
    ) as mock_resource_monitor, patch(
        "src.orchestrator.ProcessManager"
    ) as mock_process_manager, patch(
        "src.orchestrator.ResultCollector"
    ) as mock_result_collector:

        custom_wait_time = 30
        orchestrator = Orchestrator(
            harness_names=mock_harness_names,
            memory_limit=1000,
            single_fuzz_script="test_script.py",
            wait_time=custom_wait_time,
        )

        assert orchestrator.wait_time == custom_wait_time
        mock_resource_monitor.assert_called_once_with(
            memory_limit=1000, wait_time=custom_wait_time
        )


def test_process_has_terminated(orchestrator, mock_proc_info):
    """Тест проверки завершения процесса"""
    # Процесс активен
    assert not orchestrator._process_has_terminated(mock_proc_info)

    # Процесс завершен
    mock_proc_info["process"].poll.return_value = 0
    assert orchestrator._process_has_terminated(mock_proc_info)


def test_remove_finished_from_active(orchestrator, mock_proc_info):
    """Тест удаления завершенных процессов из активного списка"""
    active_list = [mock_proc_info]
    finished_list = [mock_proc_info]

    result = orchestrator._remove_finished_from_active(
        active_list, finished_list
    )
    assert result == []


def test_there_are_still_active_processes(orchestrator, mock_proc_info):
    """Тест проверки наличия активных процессов"""
    # Нет активных процессов
    assert not orchestrator._there_are_still_active_processes()

    # Есть активные процессы
    orchestrator.active_tasks = [mock_proc_info]
    assert orchestrator._there_are_still_active_processes()


@pytest.mark.timeout(5)
def test_run_with_single_harness(orchestrator):
    """Тест запуска с одним harness"""
    orchestrator.harnesses = ["harness1"]
    orchestrator.run()

    # Проверяем, что были вызваны все необходимые методы
    orchestrator.resource_monitor.start.assert_called_once()
    orchestrator.resource_monitor.stop.assert_called_once()
    orchestrator.process_manager.start_fuzzing.assert_called_once_with(
        "harness1"
    )
    orchestrator.result_collector.final_report.assert_called_once()


@pytest.mark.timeout(5)
def test_run_with_multiple_harnesses(orchestrator):
    """Тест запуска с несколькими harnesses"""
    orchestrator.harnesses = ["harness1", "harness2"]
    orchestrator.run()

    # Проверяем, что были вызваны методы для каждого harness
    assert orchestrator.process_manager.start_fuzzing.call_count == 2
    orchestrator.process_manager.start_fuzzing.assert_any_call("harness1")
    orchestrator.process_manager.start_fuzzing.assert_any_call("harness2")


@pytest.mark.timeout(5)
def test_run_with_resource_limit(orchestrator):
    """Тест запуска с ограничением ресурсов"""
    orchestrator.harnesses = ["harness1", "harness2"]
    orchestrator.resource_monitor.can_start_new_process.side_effect = [
        False,
        True,
    ]

    orchestrator.run()

    # Проверяем, что был вызов ожидания при недостатке ресурсов
    assert orchestrator.resource_monitor.can_start_new_process.call_count > 1


def test_collect_finished_processes(orchestrator, mock_proc_info):
    """Тест сбора результатов завершенных процессов"""
    # Настраиваем процесс как завершенный
    mock_proc_info["process"].poll.return_value = 0
    orchestrator.active_tasks = [mock_proc_info]

    orchestrator._collect_finished_processes()

    # Проверяем, что результаты были собраны
    orchestrator.result_collector.collect.assert_called_once_with(
        mock_proc_info
    )
    assert len(orchestrator.active_tasks) == 0
