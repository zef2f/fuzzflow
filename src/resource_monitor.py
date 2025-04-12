import time
import threading
import psutil

from fuzzflow.src.utils import (
    over_memory_threshold,
    DEFAULT_WAIT_TIME_SECONDS,
    get_total_subprocess_memory,
)


class ResourceMonitor:
    """
    Monitors system memory usage and decides if new subprocesses can be launched.
    """

    def __init__(self, memory_limit, wait_time=DEFAULT_WAIT_TIME_SECONDS):
        self.memory_limit = memory_limit
        self.wait_time = wait_time
        self.running = False
        self.monitor_thread = None

        self.managed_pids = []

    def register_pid(self, pid):
        if pid not in self.managed_pids:
            self.managed_pids.append(pid)

    def unregister_pid(self, pid):
        if pid in self.managed_pids:
            self.managed_pids.remove(pid)

    def start(self):
        if not self.running:
            self.running = True
            self.monitor_thread = threading.Thread(
                target=self._monitor_loop, daemon=True
            )
            self.monitor_thread.start()

    def stop(self):
        self.running = False
        if self.monitor_thread is not None:
            self.monitor_thread.join()
            self.monitor_thread = None

    def can_start_new_process(self) -> bool:
        current_usage = get_total_subprocess_memory(self.managed_pids)
        return current_usage < (self.memory_limit * 0.8)

    def _monitor_loop(self):
        while self.running:
            current_usage = get_total_subprocess_memory(self.managed_pids)
            print(
                f"[ResourceMonitor] Total subprocess memory usage: {current_usage} MB"
            )

            if current_usage > (self.memory_limit * 0.9):
                print(
                    "[ResourceMonitor] Memory usage critical. Consider killing some subprocesses!"
                )

            time.sleep(self.wait_time)
