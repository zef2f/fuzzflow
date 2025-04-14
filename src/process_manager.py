import subprocess
import time
import logging
from pathlib import Path

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


class ProcessManager:
    """
    Class for starting and stopping individual fuzzing processes.
    """

    def __init__(self, single_fuzz_script):
        self.single_fuzz_script = single_fuzz_script
        logging.info(
            f"ProcessManager initialized with fuzzing script: {single_fuzz_script}"
        )

    def start_fuzzing(self, harness):
        full_cmd = [self.single_fuzz_script] + ["--harness", harness]
        logging.info(
            f"Starting fuzzing for {harness}) with command: {' '.join(full_cmd)}"
        )

        try:
            process = subprocess.Popen(
                full_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            logging.info(
                f"Fuzzing process started (Harness name: {harness}, PID: {process.pid})"
            )

            proc_info = {
                "harness_name": harness,
                "process": process,
                "start_time": time.time(),
            }
            return proc_info

        except Exception as e:
            logging.error(
                f"Error starting fuzzing (Harness ID: {harness}): {e}",
                exc_info=True,
            )
            return None

    def kill_fuzzing(self, proc_info):
        process = proc_info.get("process")
        harness_name = proc_info.get("harness_name", "unknown")

        if process and process.poll() is None:
            try:
                process.terminate()
                process.communicate()

            except Exception as e:
                logging.error(
                    f"Error terminating process {process.pid} (Harness ID: {harness_name}): {e}",
                    exc_info=True,
                )
