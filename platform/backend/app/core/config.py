"""Environment-backed configuration; secrets are never returned by API routes."""

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

PROJECT_ROOT = Path(os.getenv("CUAUTOREVIEW_PROJECT_ROOT", Path(__file__).resolve().parents[4])).resolve()
# Largest JSON import body; the global request cap sits above it so imports keep their specific errors.
MAX_IMPORT_BYTES = 32 * 1024 * 1024

ENVIRONMENT = os.getenv("ENVIRONMENT", "development").strip().lower()
_PRODUCTION = ENVIRONMENT == "production"


def _flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    return default if value is None or not value.strip() else value.strip().lower() == "true"


def _origins(value: str) -> tuple[str, ...]:
    """Normalize a comma-separated origin list to lower-case scheme://host[:port] without trailing slashes."""
    return tuple(origin.strip().rstrip("/").lower() for origin in value.split(",") if origin.strip())


@dataclass(frozen=True)
class Settings:
    environment: str = ENVIRONMENT
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./var/platform.sqlite")
    celery_broker_url: str = os.getenv("CELERY_BROKER_URL", "amqp://guest:guest@127.0.0.1:5672//")
    object_store_backend: str = os.getenv("OBJECT_STORE_BACKEND", "local")
    local_artifact_dir: Path = Path(os.getenv("LOCAL_ARTIFACT_DIR", "./var/artifacts")).resolve()
    # Empty means AWS S3 itself; set for S3-compatible stores such as SeaweedFS or MinIO.
    s3_endpoint_url: str | None = os.getenv("S3_ENDPOINT_URL") or None
    s3_bucket: str = os.getenv("S3_BUCKET", "cuautoreview-local")
    aws_region: str = os.getenv("AWS_REGION", "us-east-1")
    session_cookie: str = os.getenv("SESSION_COOKIE", "cuautoreview_session")
    session_ttl_hours: int = int(os.getenv("SESSION_TTL_HOURS", "336"))
    secure_cookies: bool = _flag("SECURE_COOKIES", False)
    seed_poc: bool = _flag("SEED_POC", True)
    job_lease_seconds: int = int(os.getenv("JOB_LEASE_SECONDS", "180"))
    max_job_attempts: int = int(os.getenv("MAX_JOB_ATTEMPTS", "4"))
    # Production defaults are stricter; every value can still be set explicitly.
    auto_migrate: bool = _flag("AUTO_MIGRATE", not _PRODUCTION)
    allow_signup: bool = _flag("ALLOW_SIGNUP", not _PRODUCTION)
    expose_api_docs: bool = _flag("EXPOSE_API_DOCS", not _PRODUCTION)
    # Browser origins allowed to send cookie-authenticated writes, e.g. https://review.example.com.
    trusted_origins: tuple[str, ...] = _origins(os.getenv("PUBLIC_ORIGIN", ""))
    log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()
    log_format: str = os.getenv("LOG_FORMAT", "json" if _PRODUCTION else "text").lower()
    login_max_failures: int = int(os.getenv("LOGIN_MAX_FAILURES", "5"))
    login_ip_max_failures: int = int(os.getenv("LOGIN_IP_MAX_FAILURES", "50"))
    login_window_seconds: int = int(os.getenv("LOGIN_WINDOW_SECONDS", "900"))

    @property
    def production(self) -> bool:
        return self.environment == "production"


settings = Settings()


def production_problems(current: Settings, environ: dict[str, str] | None = None) -> list[str]:
    """Return every reason the configuration is unsafe for production (empty when it is acceptable).

    The committed local credentials (platform/compose.yaml, platform/deploy/s3.json) are rejected by value.
    """
    env = os.environ if environ is None else environ
    problems = []
    if not current.secure_cookies:
        problems.append("SECURE_COOKIES must be true (session cookies require HTTPS)")
    if current.database_url.startswith("sqlite"):
        problems.append("DATABASE_URL must point to PostgreSQL, not SQLite")
    if "local_database" in current.database_url:
        problems.append("DATABASE_URL uses the committed local database password")
    if any(secret in current.celery_broker_url for secret in ("local_broker", "guest:guest")):
        problems.append("CELERY_BROKER_URL uses committed or default broker credentials")
    if current.object_store_backend != "s3":
        problems.append("OBJECT_STORE_BACKEND must be s3; the local file store is a development fallback")
    elif any(
        env.get(name, "") in ("", "local_access", "local_secret")
        for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY")
    ):
        problems.append("AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY must be set to non-default credentials")
    if current.seed_poc:
        problems.append("SEED_POC must be false")
    if not current.trusted_origins:
        problems.append("PUBLIC_ORIGIN must list the HTTPS origin(s) users open, e.g. https://review.example.com")
    for origin in current.trusted_origins:
        parts = urlsplit(origin)
        if parts.scheme != "https" or not parts.netloc or parts.path or parts.query or parts.fragment:
            problems.append(f"PUBLIC_ORIGIN entry {origin!r} must be an https://host[:port] origin")
    if current.log_format not in ("json", "text"):
        problems.append("LOG_FORMAT must be 'json' or 'text'")
    return problems


def check_settings(current: Settings | None = None) -> None:
    """Refuse to start with an unknown environment, or in production with unsafe settings (all listed at once)."""
    current = current or settings
    if current.environment not in ("development", "production"):
        raise RuntimeError(f"ENVIRONMENT must be 'development' or 'production', not {current.environment!r}")
    if not current.production:
        return
    problems = production_problems(current)
    if problems:
        raise RuntimeError(
            "Refusing to start: unsafe production configuration:\n" + "\n".join(f"  - {item}" for item in problems)
        )
