import time
import threading
import psutil

from fuzzflow.src.utils import over_memory_threshold

class ResourceMonitor:
    """
    Class for monitoring resources in a separate thread.
    """

    def __init__(self, memory_limit):
        """
        :param memory_limit: Memory limit in megabytes (int).
        """
        self.memory_limit = memory_limit
        self.running = False
        self.monitor_thread = None

        self.processes_to_kill = []

    def start(self):
        """
        Starts resource monitoring in a separate thread.
        """
        if not self.running:
            self.running = True
            self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self.monitor_thread.start()

    def stop(self):
        """
        Stops resource monitoring, waits for thread completion.
        """
        self.running = False
        if self.monitor_thread is not None:
            self.monitor_thread.join()
            self.monitor_thread = None

    def can_start_new_process(self) -> bool:
        """
        Checks if we can safely start a new process.
        Returns True if current memory usage is below the limit; False otherwise.
        """
        return not over_memory_threshold(self.memory_limit)

    def _monitor_loop(self):
        """
        Internal method running in background thread.
        Periodically checks current memory usage.
        May initiate kill processes if necessary.
        """
        while self.running:
            mem_info = psutil.virtual_memory()
            used_mb = mem_info.used // (1024 * 1024)

            # Simple 80% logic: if we exceed 80% of the limit,
            # we can terminate some fuzzing process.
            threshold_90 = int(self.memory_limit * 0.8)
            if used_mb > threshold_90:
                # TODO: Implement process termination logic
                pass

            time.sleep(10)
