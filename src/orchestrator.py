import time
import logging
import json
from fuzzflow.src.resource_monitor import ResourceMonitor
from fuzzflow.src.process_manager import ProcessManager
from fuzzflow.src.result_collector import ResultCollector

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

class Orchestrator:
    def __init__(self, wrapper_names, memory_limit, single_fuzz_script, other_params=None):
        """
        Initialize the fuzzflow orchestrator.

        :param wrapper_names: List of fuzzing wrappers in JSON format.
        :param memory_limit: Memory limit in MB (int).
        :param single_fuzz_script: Path to the script that runs a single fuzzing process.
        :param other_params: Additional parameters (optional).
        """
        self.wrapper_names = wrapper_names
        self.memory_limit = memory_limit
        self.single_fuzz_script = single_fuzz_script
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
        """
        Main method. Starts resource monitoring, runs fuzzing for each
        wrapper (if resources allow), collects results and generates final report.
        """
        logging.info("Starting fuzzing...")

        logging.debug("Starting resource monitor...")
        self.resource_monitor.start()

        for wrapper in self.wrappers:
            logging.info(f"Starting fuzzing for {wrapper}")

            # Wait if we can't start due to memory limits
            while not self.resource_monitor.can_start_new_process():
                logging.warning("Insufficient resources for new process. Waiting...")
                self._wait_some_seconds(2)

            logging.debug(f"Starting fuzzing process for wrapper {wrapper}")
            proc_info = self.process_manager.start_fuzzing(wrapper)

            self.active_tasks.append(proc_info)
            logging.info(f"Fuzzing process started (PID: {proc_info['process'].pid})")

            # Check if any previously started processes have completed
            self._collect_finished_processes()
            self._wait_some_seconds(5)


        # Wait for all active processes to complete
        while self._there_are_still_active_processes():
            logging.info("Waiting for all processes to complete...")
            self._collect_finished_processes()
            self._wait_some_seconds(5)

        logging.info("Stopping resource monitor...")
        self.resource_monitor.stop()

        logging.info("Generating final report...")
        self.result_collector.final_report()
        logging.info("Fuzzing completed.")

    def _collect_finished_processes(self):
        """
        Check which processes have completed, collect results and
        remove them from self.active_tasks.
        """
        finished_list = []
        for proc_info in self.active_tasks:
            if self._process_has_terminated(proc_info):
                logging.info(f"Process {proc_info['process'].pid} completed, collecting results...")
                self.result_collector.collect(proc_info)
                finished_list.append(proc_info)

        self.active_tasks = self._remove_finished_from_active(self.active_tasks, finished_list)

    def _process_has_terminated(self, proc_info):
        """
        Check if subprocess has terminated.
        :param proc_info: Process information (dict).
        :return: True if terminated; False otherwise.
        """
        process = proc_info["process"]
        if process.poll() is not None:
            logging.debug(f"Process {process.pid} completed with code {process.returncode}.")
            return True
        return False

    def _remove_finished_from_active(self, active_list, finished_list):
        """
        Remove completed processes from the list of active processes.
        :param active_list: Original list of active processes.
        :param finished_list: List of completed processes.
        :return: Updated list of active processes.
        """
        return [p for p in active_list if p not in finished_list]

    def _there_are_still_active_processes(self):
        """
        Check if there are still active (uncompleted) processes in self.active_tasks.
        """
        active_count = len(self.active_tasks)
        logging.debug(f"Active processes: {active_count}")
        return active_count > 0

    def _wait_some_seconds(self, seconds):
        """
        Intermediate wait (delay) to reduce load in loops.
        """
        logging.debug(f"Waiting {seconds} seconds...")
        time.sleep(seconds)
