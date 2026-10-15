"""Application settings, loaded from environment variables and validated at startup."""

import base64
from functools import lru_cache
from typing import Literal
from urllib.parse import parse_qs, urlparse

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _decode_key(value: str, name: str) -> bytes:
    try:
        raw = base64.b64decode(value, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"{name} must be base64 encoded") from exc
    if len(raw) < 32:
        raise ValueError(f"{name} must decode to at least 32 bytes")
    return raw


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: Literal["development", "test", "production"] = "production"
    app_url: str = "http://localhost:5173"
    allowed_origins: str = "http://localhost:5173"

    database_url: str
    db_ssl_root_cert: str | None = None
    db_pool_max_size: int = Field(default=4, ge=1, le=20)

    supabase_url: str
    supabase_anon_key: str = Field(min_length=20)
    supabase_service_role_key: str = Field(min_length=20)
    supabase_jwt_secret: str | None = None

    data_encryption_key: str
    audit_hmac_key: str
    pseudonym_key: str
    device_master_key: str

    require_admin_mfa: bool = True
    idle_timeout_minutes: int = Field(default=15, ge=1, le=240)
    absolute_timeout_hours: int = Field(default=12, ge=1, le=72)
    max_concurrent_sessions: int = Field(default=3, ge=1, le=20)
    password_min_length: int = Field(default=12, ge=8, le=128)
    login_max_failures: int = Field(default=5, ge=3, le=20)
    lockout_minutes: int = Field(default=15, ge=1, le=1440)
    login_ip_limit_per_5min: int = Field(default=100, ge=5, le=10000)
    emergency_access_minutes: int = Field(default=30, ge=5, le=240)
    data_retention_days: int = Field(default=7, ge=1, le=3650)
    max_body_bytes: int = 1_048_576
    max_upload_bytes: int = 2_097_152

    @field_validator("supabase_url", "app_url")
    @classmethod
    def _strip_slash(cls, v: str) -> str:
        return v.rstrip("/")

    @model_validator(mode="after")
    def _validate(self) -> "Settings":
        for name in ("data_encryption_key", "audit_hmac_key", "pseudonym_key", "device_master_key"):
            _decode_key(getattr(self, name), name.upper())
        if self.environment == "production":
            for name in ("supabase_url", "app_url"):
                if not getattr(self, name).startswith("https://"):
                    raise ValueError(f"{name.upper()} must use https in production")
            for origin in self.origins:
                if not origin.startswith("https://"):
                    raise ValueError("ALLOWED_ORIGINS must use https in production")
            sslmode = parse_qs(urlparse(self.database_url).query).get("sslmode", [""])[0]
            if sslmode not in ("require", "verify-ca", "verify-full"):
                raise ValueError("DATABASE_URL must set sslmode=require (or verify-full) in production")
        return self

    @property
    def origins(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    def key(self, name: str) -> bytes:
        return _decode_key(getattr(self, name), name.upper())


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
