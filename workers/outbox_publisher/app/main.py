"""Outbox publisher entrypoint. Filled in P08."""

from __future__ import annotations

import time


def main() -> None:
    print("worker stub: outbox-publisher", flush=True)
    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
