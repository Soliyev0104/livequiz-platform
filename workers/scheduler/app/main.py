"""Scheduler entrypoint. Filled in P07."""

from __future__ import annotations

import time


def main() -> None:
    print("worker stub: scheduler", flush=True)
    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
