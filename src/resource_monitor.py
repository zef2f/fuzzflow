import time
import threading
import psutil

from fuzzflow.src.utils import over_memory_threshold

class ResourceMonitor:
    """
    Class for monitoring resources in a separate thread.
    """

    def __init__(self, memory_limit):
        self.memory_limit = memory_limit
        self.running = False
        self.monitor_thread = None

        self.processes_to_kill = []

    def start(self):
        if not self.running:
            self.running = True
            self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self.monitor_thread.start()

    def stop(self):
        self.running = False
        if self.monitor_thread is not None:
            self.monitor_thread.join()
            self.monitor_thread = None

    def can_start_new_process(self) -> bool:
        return not over_memory_threshold(self.memory_limit)

    def _monitor_loop(self):
        while self.running:
            mem_info = psutil.virtual_memory()
            used_mb = mem_info.used // (1024 * 1024)

            # Simple 80% logic: if we exceed 80% of the limit,
            # we can terminate some fuzzing process.
            threshold_80 = int(self.memory_limit * 0.8)
            if used_mb > threshold_80:
                # TODO: Implement process termination logic
                pass

            time.sleep(60)
