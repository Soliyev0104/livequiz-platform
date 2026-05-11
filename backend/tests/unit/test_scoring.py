"""Unit tests for :mod:`app.services.scoring_service`.

Boundary cases that double as the scoring contract for P07:

- ``response_time_ms == 0`` → full points (instant correct answer).
- ``response_time_ms == deadline_ms`` → exactly half points (50/50 split
  in ``speed_bonus``).
- ``is_correct == False`` → 0 regardless of mode or timing.
- ``mode == "fixed"`` → flat ``points`` ignoring response time.
- Pathological ``deadline_ms <= 0`` falls back to full points so a
  zero-duration question can never produce NaN scores.

The function is pure, so no fixtures are needed.
"""

from __future__ import annotations

import pytest

from app.services.scoring_service import (
    SCORING_MODE_FIXED,
    SCORING_MODE_SPEED_BONUS,
    score,
)


def test_speed_bonus_instant_correct_full_points() -> None:
    assert score(1000, response_time_ms=0, deadline_ms=20_000) == 1000


def test_speed_bonus_at_deadline_half_points() -> None:
    assert score(1000, response_time_ms=20_000, deadline_ms=20_000) == 500


def test_speed_bonus_midway_three_quarter_points() -> None:
    # Halfway through the question: 50% correctness + 50% × (1 - 0.5) = 75%
    assert score(1000, response_time_ms=10_000, deadline_ms=20_000) == 750


def test_incorrect_zero_regardless_of_mode() -> None:
    assert score(
        1000, response_time_ms=0, deadline_ms=20_000, is_correct=False
    ) == 0
    assert (
        score(
            1000,
            response_time_ms=10_000,
            deadline_ms=20_000,
            mode=SCORING_MODE_FIXED,
            is_correct=False,
        )
        == 0
    )


def test_fixed_mode_flat_points() -> None:
    assert (
        score(1000, response_time_ms=12345, deadline_ms=20_000, mode=SCORING_MODE_FIXED)
        == 1000
    )


def test_response_time_clamped_above_deadline_yields_half() -> None:
    # A 200 ms grace submit lands slightly past the deadline; the
    # scoring fn clamps and treats it as exactly at the deadline.
    assert (
        score(1000, response_time_ms=20_500, deadline_ms=20_000)
        == 500
    )


def test_zero_deadline_returns_full_points() -> None:
    assert score(1000, response_time_ms=0, deadline_ms=0) == 1000


@pytest.mark.parametrize(
    ("rt_ms", "expected"),
    [
        (0, 1000),
        (5_000, 875),  # 50% + 50% × 0.75 = 87.5%
        (15_000, 625),  # 50% + 50% × 0.25 = 62.5%
        (20_000, 500),
    ],
)
def test_speed_bonus_curve(rt_ms: int, expected: int) -> None:
    assert score(
        1000,
        response_time_ms=rt_ms,
        deadline_ms=20_000,
        mode=SCORING_MODE_SPEED_BONUS,
    ) == expected
