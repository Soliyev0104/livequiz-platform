"""Process-wide settings, sourced from env.

Loaded once via :func:`get_settings`. Missing required env vars raise at
import-time of the singleton, so the lifespan startup fails fast.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=None,
        case_sensitive=False,
        extra="ignore",
    )

    service_name: str = Field(default="api-a", alias="SERVICE_NAME")
    app_env: str = Field(default="local", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    cors_origins: str = Field(default="http://localhost", alias="CORS_ORIGINS")

    database_url: str = Field(alias="DATABASE_URL")
    redis_url: str = Field(alias="REDIS_URL")
    redpanda_bootstrap_servers: str = Field(
        default="redpanda:9092", alias="REDPANDA_BOOTSTRAP_SERVERS"
    )
    clickhouse_url: str = Field(default="http://clickhouse:8123", alias="CLICKHOUSE_URL")
    clickhouse_db: str = Field(default="livequiz", alias="CLICKHOUSE_DB")

    jwt_secret: str = Field(default="change_me", alias="JWT_SECRET")
    jwt_refresh_secret: str = Field(default="change_me", alias="JWT_REFRESH_SECRET")
    jwt_access_ttl_min: int = Field(default=15, alias="JWT_ACCESS_TTL_MIN")
    jwt_refresh_ttl_days: int = Field(default=7, alias="JWT_REFRESH_TTL_DAYS")

    snowflake_worker_id: int = Field(alias="SNOWFLAKE_WORKER_ID")
    snowflake_epoch_ms: int = Field(default=1767225600000, alias="SNOWFLAKE_EPOCH_MS")

    otel_exporter_otlp_endpoint: str = Field(
        default="http://otel-collector:4317", alias="OTEL_EXPORTER_OTLP_ENDPOINT"
    )

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
