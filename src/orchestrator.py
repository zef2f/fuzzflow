import time
import logging
import json
from fuzzflow.src.resource_monitor import ResourceMonitor
from fuzzflow.src.process_manager import ProcessManager
from fuzzflow.src.result_collector import ResultCollector
from fuzzflow.src.utils import DEFAULT_WAIT_TIME_SECONDS

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

class Orchestrator:
    def __init__(self, wrapper_names, memory_limit, single_fuzz_script, wait_time=DEFAULT_WAIT_TIME_SECONDS, other_params=None):
        self.wrapper_names = wrapper_names
        self.memory_limit = memory_limit
        self.single_fuzz_script = single_fuzz_script
        self.wait_time = wait_time
        self.other_params = other_params

        self.wrappers = json.loads(wrapper_names)

        logging.debug("Creating resource monitor...")
        self.resource_monitor = ResourceMonitor(memory_limit=self.memory_limit)

        logging.debug("Creating process manager...")
        self.process_manager = ProcessManager(single_fuzz_script=self.single_fuzz_script)

        logging.debug("Creating result collector...")
        self.result_collector = ResultCollector()

        self.active_tasks = []

    def run(self):
        logging.info("Starting fuzzing...")
        self.resource_monitor.start()
        self._start_fuzzing_loop()

        while self._has_active_tasks():
            logging.info("Waiting for all processes to complete...")
            self._cleanup_finished_tasks()
            self._wait()

        self.resource_monitor.stop()
        self.result_collector.final_report()
        logging.info("Fuzzing completed.")

    def _start_fuzzing_loop(self):
        for wrapper in self.wrappers:
            logging.info(f"Starting fuzzing for {wrapper}")
            self._wait_until_resources_available()

            proc_info = self.process_manager.start_fuzzing(wrapper)
            self.active_tasks.append(proc_info)
            self.resource_monitor.register_pid(proc_info["process"].pid)

            logging.info(f"Fuzzing process started (PID: {proc_info['process'].pid})")
            self._cleanup_finished_tasks()
            self._wait()

    def _wait_until_resources_available(self):
        while not self.resource_monitor.can_start_new_process():
            logging.warning("Insufficient resources for new process. Waiting...")
            self._wait()

    def _cleanup_finished_tasks(self):
        finished_list = []
        for proc_info in self.active_tasks:
            if self._process_has_terminated(proc_info):
                logging.info(f"Process {proc_info['process'].pid} completed, collecting results...")
                self.result_collector.collect(proc_info)
                finished_list.append(proc_info)

        self.active_tasks = [p for p in self.active_tasks if p not in finished_list]

    def _process_has_terminated(self, proc_info):
        process = proc_info["process"]
        if process.poll() is not None:
            logging.debug(f"Process {process.pid} completed with code {process.returncode}.")
            return True
        return False

    def _has_active_tasks(self):
        active_count = len(self.active_tasks)
        logging.debug(f"Active processes: {active_count}")
        return active_count > 0

    def _wait(self):
        logging.debug(f"Waiting {self.wait_time} seconds...")
        time.sleep(self.wait_time)
