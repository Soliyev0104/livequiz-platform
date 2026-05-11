"""Pure scoring functions.

Two modes are supported:

- ``fixed`` — flat ``points`` for any correct answer.
- ``speed_bonus`` (default) — half the points for correctness plus the
  other half scaled linearly by remaining time. A submission at
  ``response_time_ms == 0`` earns full points; one at
  ``response_time_ms == deadline_ms`` earns half. Wrong answers always
  earn zero.

This module is intentionally side-effect free. The match service computes
``response_time_ms`` and ``deadline_ms`` from server timestamps and feeds
them in; tests can exercise corner cases without touching Postgres.
"""

from __future__ import annotations


SCORING_MODE_FIXED = "fixed"
SCORING_MODE_SPEED_BONUS = "speed_bonus"


def score(
    points: int,
    response_time_ms: int,
    deadline_ms: int,
    mode: str = SCORING_MODE_SPEED_BONUS,
    is_correct: bool = True,
) -> int:
    """Award integer points for a single answer.

    ``deadline_ms`` is the question's full time-limit in milliseconds.
    ``response_time_ms`` is clamped into ``[0, deadline_ms]`` so the
    speed-bonus scaling never goes negative or above 1.
    """
    if not is_correct:
        return 0
    if mode == SCORING_MODE_FIXED:
        return int(points)

    # speed_bonus: 50% for correctness + 50% scaled by remaining time
    if deadline_ms <= 0:
        # Pathological: zero-duration question. Treat as full speed.
        return int(points)
    rt = max(0, min(int(response_time_ms), int(deadline_ms)))
    fraction = 1.0 - rt / deadline_ms
    return int(round(points * (0.5 + 0.5 * fraction)))
