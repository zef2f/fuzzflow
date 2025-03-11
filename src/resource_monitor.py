import time
import threading
import psutil

from src.utils import over_memory_threshold

class ResourceMonitor:
    """
    Класс для мониторинга ресурсов в отдельном потоке.
    """

    def __init__(self, memory_limit):
        """
        :param memory_limit: Лимит памяти в мегабайтах (int).
        """
        self.memory_limit = memory_limit
        self.running = False
        self.monitor_thread = None

        self.processes_to_kill = []

    def start(self):
        """
        Запускает мониторинг ресурсов в отдельном потоке.
        """
        if not self.running:
            self.running = True
            self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self.monitor_thread.start()

    def stop(self):
        """
        Останавливает мониторинг ресурсов, дожидается завершения потока.
        """
        self.running = False
        if self.monitor_thread is not None:
            self.monitor_thread.join()
            self.monitor_thread = None

    def can_start_new_process(self) -> bool:
        """
        Проверяет, можем ли мы безопасно запустить новый процесс.
        Возвращает True, если текущая память не превышает лимит; False иначе.
        """
        return not over_memory_threshold(self.memory_limit)

    def _monitor_loop(self):
        """
        Внутренний метод, работающий в фоновом потоке.
        Периодически проверяет текущее использование памяти.
        При необходимости может инициировать kill-процессы.
        """
        while self.running:
            mem_info = psutil.virtual_memory()
            used_mb = mem_info.used // (1024 * 1024)

            # Простая логика 80%: если мы превысили 80% лимита,
            # можно завершить какой-нибудь процесс фаззинга.
            threshold_90 = int(self.memory_limit * 0.8)
            if used_mb > threshold_90:
                # TODO: Реализовать логику, как убиваем процесс
                pass

            time.sleep(10)
