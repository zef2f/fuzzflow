import time
import logging
import json
from src.resource_monitor import ResourceMonitor
from src.process_manager import ProcessManager
from src.result_collector import ResultCollector

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

class Orchestrator:
    def __init__(self, wrapper_names, memory_limit, single_fuzz_script, other_params=None):
        """
        Инициализация оркестратора fuzzflow.

        :param wrapper_names: Список оберток для фаззинга в JSON формате.
        :param memory_limit: Лимит памяти в МБ (int).
        :param single_fuzz_script: Путь к скрипту, который запускает одиночный фаззинг-процесс.
        :param other_params: Дополнительные параметры (необязательно).
        """
        self.wrapper_names = wrapper_names
        self.memory_limit = memory_limit
        self.single_fuzz_script = single_fuzz_script
        self.other_params = other_params

        self.wrappers = json.loads(wrapper_names)

        logging.debug("Создание монитор ресурсов...")
        self.resource_monitor = ResourceMonitor(memory_limit=self.memory_limit)

        logging.debug("Создание менеджера процессов...")
        self.process_manager = ProcessManager(single_fuzz_script=self.single_fuzz_script)

        logging.debug("Создание коллектора результатов...")
        self.result_collector = ResultCollector()

        self.active_tasks = []

    def run(self):
        """
        Основной метод. Запускает мониторинг ресурсов, запускает фаззинг для каждой
        обертки (если позволяют ресурсы), собирает результаты и формирует финальный отчет.
        """
        logging.info("Запуск фаззинга...")

        logging.debug("Запускаем монитор ресурсов...")
        self.resource_monitor.start()

        for wrapper in self.wrappers:
            logging.info(f"Запуск фаззинга для {wrapper}")

            # Пока нельзя запускать из-за лимитов памяти – ожидаем
            while not self.resource_monitor.can_start_new_process():
                logging.warning("Недостаточно ресурсов для нового процесса. Ожидание...")
                self._wait_some_seconds(2)

            logging.debug(f"Запуск процесса фаззинга для обертки {wrapper}")
            proc_info = self.process_manager.start_fuzzing(wrapper)

            self.active_tasks.append(proc_info)
            logging.info(f"Фаззинг-процесс запущен (PID: {proc_info['process'].pid})")

            # Проверяем, завершился ли кто-то из ранее запущенных процессов
            self._collect_finished_processes()
            self._wait_some_seconds(5)


        # Ждем, пока все активные процессы завершатся
        while self._there_are_still_active_processes():
            logging.info("Ожидание завершения всех процессов...")
            self._collect_finished_processes()
            self._wait_some_seconds(5)

        logging.info("Останавливаем монитор ресурсов...")
        self.resource_monitor.stop()

        logging.info("Формируем итоговый отчёт...")
        self.result_collector.final_report()
        logging.info("Фаззинг завершён.")

    def _collect_finished_processes(self):
        """
        Проверяем, какие процессы завершились, собираем результаты и
        удаляем их из self.active_tasks.
        """
        finished_list = []
        for proc_info in self.active_tasks:
            if self._process_has_terminated(proc_info):
                logging.info(f"Процесс {proc_info['process'].pid} завершился, собираем результаты...")
                self.result_collector.collect(proc_info)
                finished_list.append(proc_info)

        self.active_tasks = self._remove_finished_from_active(self.active_tasks, finished_list)

    def _process_has_terminated(self, proc_info):
        """
        Проверяет, завершился ли subprocess.
        :param proc_info: Информация о процессе (dict).
        :return: True, если завершился; False, иначе.
        """
        process = proc_info["process"]
        if process.poll() is not None:
            logging.debug(f"Процесс {process.pid} завершился с кодом {process.returncode}.")
            return True
        return False

    def _remove_finished_from_active(self, active_list, finished_list):
        """
        Удаляем завершенные процессы из общего списка активных.
        :param active_list: Исходный список активных процессов.
        :param finished_list: Список процессов, которые завершились.
        :return: Обновленный список активных процессов.
        """
        return [p for p in active_list if p not in finished_list]

    def _there_are_still_active_processes(self):
        """
        Проверка, есть ли еще активные (незавершенные) процессы в self.active_tasks.
        """
        active_count = len(self.active_tasks)
        logging.debug(f"Активных процессов: {active_count}")
        return active_count > 0

    def _wait_some_seconds(self, seconds):
        """
        Промежуточное ожидание (задержка) для снижения нагрузки в циклах.
        """
        logging.debug(f"Ожидание {seconds} секунд...")
        time.sleep(seconds)
