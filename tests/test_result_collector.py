import pytest
from unittest.mock import patch, MagicMock, call
import time
from src.result_collector import ResultCollector


@pytest.fixture
def result_collector():
    """Фикстура для создания экземпляра ResultCollector"""
    return ResultCollector()


@pytest.fixture
def mock_process():
    """Фикстура для создания мока процесса"""
    process = MagicMock()
    process.poll.return_value = 0
    process.returncode = 0
    return process


@pytest.fixture
def mock_proc_info(mock_process):
    """Фикстура для создания информации о процессе"""
    return {
        "process": mock_process,
        "harness_name": "test_harness",
        "start_time": time.time() - 10,  # 10 секунд назад
    }


def test_result_collector_initialization(result_collector):
    """Тест корректной инициализации ResultCollector"""
    assert isinstance(result_collector.results, list)
    assert len(result_collector.results) == 0


def test_collect_successful_process(result_collector, mock_proc_info):
    """Тест сбора результатов успешно завершенного процесса"""
    result_collector.collect(mock_proc_info)

    assert len(result_collector.results) == 1
    result = result_collector.results[0]

    assert result["harness_name"] == "test_harness"
    assert result["exit_code"] == 0
    assert 9.9 <= result["duration_sec"] <= 10.1  # примерно 10 секунд


def test_collect_failed_process(result_collector, mock_proc_info):
    """Тест сбора результатов процесса с ошибкой"""
    mock_proc_info["process"].poll.return_value = 1
    mock_proc_info["process"].returncode = 1

    result_collector.collect(mock_proc_info)

    assert len(result_collector.results) == 1
    result = result_collector.results[0]

    assert result["harness_name"] == "test_harness"
    assert result["exit_code"] == 1
    assert 9.9 <= result["duration_sec"] <= 10.1


def test_collect_missing_process(result_collector):
    """Тест сбора результатов с отсутствующим процессом"""
    proc_info = {"harness_name": "test_harness", "start_time": time.time() - 5}

    result_collector.collect(proc_info)

    assert len(result_collector.results) == 1
    result = result_collector.results[0]

    assert result["harness_name"] == "test_harness"
    assert result["exit_code"] == -999
    assert 4.9 <= result["duration_sec"] <= 5.1


def test_collect_missing_start_time(result_collector, mock_proc_info):
    """Тест сбора результатов без времени старта"""
    del mock_proc_info["start_time"]

    result_collector.collect(mock_proc_info)

    assert len(result_collector.results) == 1
    result = result_collector.results[0]

    assert result["harness_name"] == "test_harness"
    assert result["exit_code"] == 0
    assert result["duration_sec"] >= 0


def test_collect_missing_harness_name(result_collector, mock_proc_info):
    """Тест сбора результатов без имени harness"""
    del mock_proc_info["harness_name"]

    result_collector.collect(mock_proc_info)

    assert len(result_collector.results) == 1
    result = result_collector.results[0]

    assert result["harness_name"] == "unknown harness"
    assert result["exit_code"] == 0


def test_collect_multiple_processes(result_collector, mock_proc_info):
    """Тест сбора результатов нескольких процессов"""
    # Первый процесс - успешный
    result_collector.collect(mock_proc_info)

    # Второй процесс - с ошибкой
    mock_proc_info_2 = mock_proc_info.copy()
    mock_proc_info_2["harness_name"] = "test_harness_2"
    mock_proc_info_2["process"].poll.return_value = 1
    mock_proc_info_2["process"].returncode = 1
    result_collector.collect(mock_proc_info_2)

    assert len(result_collector.results) == 2
    assert result_collector.results[0]["harness_name"] == "test_harness"
    assert result_collector.results[0]["exit_code"] == 0
    assert result_collector.results[1]["harness_name"] == "test_harness_2"
    assert result_collector.results[1]["exit_code"] == 1


@patch("builtins.print")
def test_final_report_empty(mock_print, result_collector):
    """Тест формирования пустого отчета"""
    result_collector.final_report()

    # Проверяем, что были напечатаны только заголовок и футер
    assert mock_print.call_count == 2
    mock_print.assert_has_calls(
        [
            call("\n========== Fuzzflow Results =========="),
            call("======================================"),
        ]
    )


@patch("builtins.print")
def test_final_report_with_results(
    mock_print, result_collector, mock_proc_info
):
    """Тест формирования отчета с результатами"""
    # Добавляем результаты
    result_collector.collect(mock_proc_info)

    # Второй процесс с ошибкой
    mock_proc_info_2 = mock_proc_info.copy()
    mock_proc_info_2["harness_name"] = "test_harness_2"
    mock_proc_info_2["process"].poll.return_value = 1
    mock_proc_info_2["process"].returncode = 1
    result_collector.collect(mock_proc_info_2)

    # Формируем отчет
    result_collector.final_report()

    # Проверяем вызовы print
    assert mock_print.call_count >= 4  # Заголовок + 2 результата + футер
    mock_print.assert_any_call("\n========== Fuzzflow Results ==========")
    mock_print.assert_any_call("======================================")
