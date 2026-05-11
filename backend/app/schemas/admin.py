"""Admin API schemas."""

from __future__ import annotations

from pydantic import BaseModel


class AdminMetricsResponse(BaseModel):
    total_users: int
    total_quiz_sets: int
    published_quiz_sets: int
    total_rooms: int
    total_matches: int
    completed_matches: int
