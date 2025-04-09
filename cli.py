#!/usr/bin/env python3

import sys
import logging
from src.utils import parse_cli_args
from src.orchestrator import Orchestrator

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

def main():
    """
    Entry point for fuzzflow.
    Reads CLI parameters and starts the Orchestrator.
    """

    cli_args = parse_cli_args()
    logging.debug(f"Arguments received: wrapper_names={cli_args.wrapper_names}, "
                  f"memory_limit={cli_args.memory_limit}, "
                  f"single_fuzz_script={cli_args.single_fuzz_script}")

    try:
        orchestrator = Orchestrator(
            wrapper_names=cli_args.wrapper_names,
            memory_limit=cli_args.memory_limit,
            single_fuzz_script=cli_args.single_fuzz_script
        )

        orchestrator.run()

    except Exception as e:
        logging.error(f"Error in fuzzflow operation: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
