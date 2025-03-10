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
    Класс для запуска и остановки отдельных процессов фаззинга.
    """

    def __init__(self, single_fuzz_script):
        """
        :param single_fuzz_script: Путь к скрипту, который запускает конкретный fuzz-процесс.
        """
        self.single_fuzz_script = single_fuzz_script
        logging.info(f"Инициализирован ProcessManager с фаззинг-скриптом: {single_fuzz_script}")

    def start_fuzzing(self, wrapper):
        """
        Запускает процесс фаззинга, основываясь на названии обертки.
        """
        full_cmd = [self.single_fuzz_script] + [wrapper]
        logging.info(f"Запуск фаззинга для {wrapper}) с командой: {' '.join(full_cmd)}")

        try:
            process = subprocess.Popen(
                full_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            logging.info(f"Фаззинг-процесс запущен (Wrapper name: {wrapper}, PID: {process.pid})")

            proc_info = {
                "wrapper_name": wrapper,
                "process": process,
                "start_time": time.time(),
            }
            return proc_info

        except Exception as e:
            logging.error(f"Ошибка при запуске фаззинга (Wrapper ID: {wrapper_id}): {e}", exc_info=True)
            return None

    def kill_fuzzing(self, proc_info):
        """
        Прерывает процесс, соответствующий переданному proc_info.
        :param proc_info: словарь вида { "process": <subprocess.Popen>, ... }
        """
        process = proc_info.get("process")
        wrapper_name = proc_info.get("wrapper_name", "unknown")

        if process and process.poll() is None:
            try:
                logging.warning(f"Попытка завершить процесс фаззинга (Wrapper name: {wrapper_name}, PID: {process.pid})...")
                process.terminate()

                time.sleep(5)
                if process.poll() is None:
                    logging.error(f"Процесс {process.pid} не завершился, принудительное завершение...")
                    process.kill()

                logging.info(f"Процесс {process.pid} успешно завершён.")

            except Exception as e:
                logging.error(f"Ошибка при завершении процесса {process.pid} (Wrapper ID: {wrapper_id}): {e}", exc_info=True)
