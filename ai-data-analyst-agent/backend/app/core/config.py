"""Application settings loaded from environment variables (see backend/.env.example)."""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]

log = logging.getLogger("app.config")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    app_name: str = "AI Data Analyst Agent"
    frontend_url: str = "http://localhost:5173"
    cors_origins: str = "http://localhost:5173"

    # Security: sessions end after `session_idle_days` without use, and in any case after `session_max_days`.
    session_idle_days: int = 7
    session_max_days: int = 30
    cookie_secure: bool | None = None  # None = secure only in production
    password_reset_minutes: int = 30

    # MongoDB
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db: str = "ai_data_analyst"

    # Currency for money columns whose values carry no symbol or code (e.g. a "Revenue" column of plain numbers).
    # Values written with a symbol keep it: $ = USD, ₹/Rs/INR = INR, and so on; nothing is converted.
    default_currency: str = "INR"

    # Storage and upload limits
    storage_dir: Path = BACKEND_DIR / "storage"
    # Tested: 30 lakh rows (156 MB CSV) cleans in about 4 minutes in the background and needs about 3.5 GB of memory;
    # pivots and dashboards on it take 5-12 seconds. Allow roughly 1.2 GB of server memory per 10 lakh rows.
    max_upload_mb: int = 150
    # Excel files are read far more slowly than CSV (about 17 s per 2 lakh rows). 40 MB covers Excel's own
    # maximum of 10,48,576 rows.
    max_excel_mb: int = 40
    max_rows: int = 3_000_000
    max_columns: int = 500

    # Background cleaning: "process" (default) or "thread" (used by the test suite for speed)
    cleaning_executor: Literal["process", "thread"] = "process"
    cleaning_workers: int = 2

    # Analytics / SQL
    query_timeout_seconds: int = 20
    sql_timeout_seconds: int = 10
    sql_max_rows: int = 10_000
    sql_memory_limit: str = "512MB"

    # Power BI export tokens
    export_token_max_days: int = 90
    export_token_in_url: bool = False

    # Email (SMTP). Empty host = not configured.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_starttls: bool = True

    # AI providers
    ai_provider: Literal["groq", "xai", ""] = ""
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    groq_base_url: str = "https://api.groq.com/openai/v1"
    xai_api_key: str = ""
    xai_model: str = "grok-4.7"
    xai_base_url: str = "https://api.x.ai/v1"
    ai_timeout_seconds: int = 45

    # Rate limits ("N/second|minute|hour|day")
    signin_rate_limit: str = "10/minute"
    signup_rate_limit: str = "5/minute"
    feed_rate_limit: str = "60/minute"
    api_rate_limit: str = "300/minute"     # every API request, per IP
    ai_rate_limit: str = "20/minute"       # AI calls (SQL generate/explain, chart ideas, insight explain), per user
    upload_rate_limit: str = "20/hour"     # uploads, URL imports and refreshes, per user
    sql_rate_limit: str = "60/minute"      # SQL Workbench runs, per user
    rate_limit_storage_uri: str = ""       # empty = in memory (one process); redis://... for several

    # Hosts this server answers for (comma-separated). Empty = any host; set it in production.
    allowed_hosts: str = ""

    @field_validator("storage_dir", mode="before")
    @classmethod
    def _abs_storage(cls, v):
        p = Path(v)
        return p if p.is_absolute() else (BACKEND_DIR / p)

    @field_validator("cookie_secure", mode="before")
    @classmethod
    def _empty_is_unset(cls, v):
        # .env.example ships `COOKIE_SECURE=` (empty) to mean "decide from APP_ENV".
        return None if isinstance(v, str) and not v.strip() else v

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def secure_cookies(self) -> bool:
        return self.is_production if self.cookie_secure is None else self.cookie_secure

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def allowed_host_list(self) -> list[str]:
        return [h.strip() for h in self.allowed_hosts.split(",") if h.strip()]

    def production_problems(self) -> list[str]:
        """Settings that are unsafe in production. The server refuses to start while any remain."""
        if not self.is_production:
            return []
        out = []
        origins = self.cors_origin_list
        if any(o == "*" for o in origins):
            out.append("CORS_ORIGINS must list your frontend address, not '*' (sign-in cookies would be exposed).")
        if any(not o.startswith("https://") for o in origins if o != "*"):
            out.append("CORS_ORIGINS must use https:// addresses only.")
        if not self.frontend_url.startswith("https://"):
            out.append("FRONTEND_URL must start with https://.")
        if self.cookie_secure is False:
            out.append("COOKIE_SECURE must not be false (the session cookie would travel over plain HTTP).")
        if not self.allowed_host_list:
            out.append("ALLOWED_HOSTS must list the API's host name(s).")
        uri = self.mongodb_uri
        host_part = uri.split("://", 1)[-1].split("/", 1)[0]
        local = all(h.split(":")[0] in ("localhost", "127.0.0.1", "::1", "[::1]") for h in host_part.rsplit("@", 1)[-1].split(","))
        has_login = "@" in host_part or "authMechanism=MONGODB-X509" in uri
        if not has_login:
            out.append("MONGODB_URI has no username/password: enable MongoDB access control and connect as an app user.")
        tls = uri.startswith("mongodb+srv://") or "tls=true" in uri.lower() or "ssl=true" in uri.lower()
        if not local and not tls:
            out.append("MONGODB_URI must use TLS for a remote database (mongodb+srv://, or add tls=true).")
        return out

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def max_excel_bytes(self) -> int:
        return min(self.max_excel_mb, self.max_upload_mb) * 1024 * 1024

    @property
    def smtp_configured(self) -> bool:
        return bool(self.smtp_host and self.smtp_from)

    def configured_ai_providers(self) -> list[str]:
        out = []
        if self.groq_api_key:
            out.append("groq")
        if self.xai_api_key:
            out.append("xai")
        return out


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.storage_dir.mkdir(parents=True, exist_ok=True)
    return s
