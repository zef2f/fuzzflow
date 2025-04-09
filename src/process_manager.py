import subprocess
import time
import logging

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

class ProcessManager:
    """
    Class for starting and stopping individual fuzzing processes.
    """

    def __init__(self, single_fuzz_script):
        self.single_fuzz_script = single_fuzz_script
        logging.info(f"ProcessManager initialized with fuzzing script: {single_fuzz_script}")

    def start_fuzzing(self, wrapper):
        full_cmd = [self.single_fuzz_script] + [wrapper]
        logging.info(f"Starting fuzzing for {wrapper}) with command: {' '.join(full_cmd)}")

        try:
            process = subprocess.Popen(
                full_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            logging.info(f"Fuzzing process started (Wrapper name: {wrapper}, PID: {process.pid})")

            proc_info = {
                "wrapper_name": wrapper,
                "process": process,
                "start_time": time.time(),
            }
            return proc_info

        except Exception as e:
            logging.error(f"Error starting fuzzing (Wrapper ID: {wrapper_id}): {e}", exc_info=True)
            return None

    def kill_fuzzing(self, proc_info):
        process = proc_info.get("process")
        wrapper_name = proc_info.get("wrapper_name", "unknown")

        if process and process.poll() is None:
            try:
                logging.warning(f"Attempting to terminate fuzzing process (Wrapper name: {wrapper_name}, PID: {process.pid})...")
                process.terminate()

                time.sleep(5)
                if process.poll() is None:
                    logging.error(f"Process {process.pid} did not terminate, forcing termination...")
                    process.kill()

                logging.info(f"Process {process.pid} successfully terminated.")

            except Exception as e:
                logging.error(f"Error terminating process {process.pid} (Wrapper ID: {wrapper_id}): {e}", exc_info=True)
