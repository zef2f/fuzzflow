import os
import json
import time
from tabulate import tabulate, _table_formats

class ResultCollector:
    """
    Class for collecting fuzzing process results.
    """

    def __init__(self):
        self.results = []

    def collect(self, proc_info):
        process = proc_info.get("process")
        wrapper_name = proc_info.get("wrapper_name") or "unknown"
        start_time = proc_info.get("start_time") or 0
        end_time = time.time()
        duration = end_time - start_time

        status = "UNKNOWN"
        reason = ""
        if process:
            returncode = process.poll()
            if returncode is not None:
                if returncode == 0:
                    status = "OK"
                else:
                    status = "FAIL"
                    try:
                        _, stderr = process.communicate(timeout=1)
                        reason = stderr.strip().splitlines()[-1] if stderr else "Non-zero exit code"
                    except Exception:
                        reason = "Failed to capture stderr"
            else:
                reason = "Process still running?"
        else:
            reason = "No process object"

        result_entry = {
            "Wrapper": wrapper_name,
            "Status": status,
            "Reason": reason if status != "OK" else "-",
            "Duration": f"{duration:.2f}s"
        }

        self.results.append(result_entry)

    def final_report(self):
        if self.results:
            print("\n<!-- table:start -->\n" + tabulate(
                self.results,
                headers="keys", tablefmt="pipe",
                maxcolwidths=[None, None, 40, None]) +
                "\n<!-- table:end -->\n")
        else:
            print("No results collected.")
