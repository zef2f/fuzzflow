import os
import json
import time

class ResultCollector:
    """
    Class for collecting fuzzing process results.
    """

    def __init__(self):
        self.results = []

    def collect(self, proc_info):
        process = proc_info.get("process")
        wrapper_name = proc_info.get("wrapper_name", "unknown wrapper")
        start_time = proc_info.get("start_time", 0)
        end_time = time.time()
        duration = end_time - start_time

        if process and process.poll() is not None:
            exit_code = process.returncode
        else:
            exit_code = -999

        result_entry = {
            "wrapper_name": wrapper_name,
            "exit_code": exit_code,
            "duration_sec": duration
        }

        self.results.append(result_entry)

    def final_report(self):
        print("\n========== Fuzzflow Results ==========")
        for entry in self.results:
            print(f"Wrapper name: {entry['wrapper_name']}, ExitCode: {entry['exit_code']}, "
                  f"Duration: {entry['duration_sec']:.2f}s")
        print("======================================")


