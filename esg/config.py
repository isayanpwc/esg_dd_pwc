"""
Central runtime configuration.

Everything that differs between a laptop and a deployed environment is read
from the environment here, so no module reaches for os.getenv on its own.

Required in production
----------------------
DATABASE_URL        postgresql+psycopg://user:pass@host/db
ESG_DATA_KEYS       key-id:base64-32-byte-key[,key-id:...]   (field encryption)
ESG_ACTIVE_KEY_ID   which key-id new writes are encrypted with
ESG_EMAIL_DOMAINS   comma-separated allowlist for account provisioning
"""

import os
from dataclasses import dataclass, field


def _split(value):
    return [v.strip() for v in (value or "").split(",") if v.strip()]


@dataclass(frozen=True)
class Settings:
    database_url: str = field(
        default_factory=lambda: os.getenv("DATABASE_URL", "")
    )
    sql_echo: bool = field(
        default_factory=lambda: os.getenv("ESG_SQL_ECHO", "").lower() == "true"
    )
    data_keys_raw: str = field(default_factory=lambda: os.getenv("ESG_DATA_KEYS", ""))
    active_key_id: str = field(default_factory=lambda: os.getenv("ESG_ACTIVE_KEY_ID", ""))
    email_domains: tuple = field(
        default_factory=lambda: tuple(_split(os.getenv("ESG_EMAIL_DOMAINS", "")))
    )
    retention_days_documents: int = field(
        default_factory=lambda: int(os.getenv("ESG_RETENTION_DAYS_DOCUMENTS", "2555"))
    )
    retention_days_audit: int = field(
        default_factory=lambda: int(os.getenv("ESG_RETENTION_DAYS_AUDIT", "3650"))
    )
    quarantine_dir: str = field(
        default_factory=lambda: os.getenv(
            "ESG_QUARANTINE_DIR",
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "quarantine"),
        )
    )
    document_dir: str = field(
        default_factory=lambda: os.getenv(
            "ESG_DOCUMENT_DIR",
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "uploads"),
        )
    )
    ocr_backend: str = field(default_factory=lambda: os.getenv("ESG_OCR_BACKEND", ""))

    def resolved_database_url(self):
        """Postgres when configured; a local SQLite file otherwise (dev only)."""
        if self.database_url:
            return self.database_url
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return f"sqlite+pysqlite:///{os.path.join(base, 'database', 'esg_local.db')}"

    def is_postgres(self):
        return self.resolved_database_url().startswith("postgresql")


_settings = None


def settings():
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reload_settings():
    """Test hook — re-read the environment."""
    global _settings
    _settings = None
    return settings()
