"""Snowflake-style 64-bit ID generator (the from-scratch component for report §9).

See ``README.md`` for the bit layout, rationale, integration points, and trade-offs.
"""

from app.core.ids.snowflake import (
    ClockMovedBackwardsError,
    SnowflakeGenerator,
    get_id_generator,
)

__all__ = ["ClockMovedBackwardsError", "SnowflakeGenerator", "get_id_generator"]
