"""Environment-backed configuration; secrets are never returned by API routes."""
from dataclasses import dataclass
import os
from pathlib import Path


PROJECT_ROOT = Path(os.getenv("CUAUTOREVIEW_PROJECT_ROOT", Path(__file__).resolve().parents[3])).resolve()


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./var/platform.sqlite")
    celery_broker_url: str = os.getenv("CELERY_BROKER_URL", "amqp://guest:guest@127.0.0.1:5672//")
    object_store_backend: str = os.getenv("OBJECT_STORE_BACKEND", "local")
    local_artifact_dir: Path = Path(os.getenv("LOCAL_ARTIFACT_DIR", "./var/artifacts")).resolve()
    s3_endpoint_url: str | None = os.getenv("S3_ENDPOINT_URL")
    s3_bucket: str = os.getenv("S3_BUCKET", "cuautoreview-local")
    aws_region: str = os.getenv("AWS_REGION", "us-east-1")
    session_cookie: str = os.getenv("SESSION_COOKIE", "cuautoreview_session")
    session_ttl_hours: int = int(os.getenv("SESSION_TTL_HOURS", "336"))
    secure_cookies: bool = os.getenv("SECURE_COOKIES", "false").lower() == "true"
    seed_poc: bool = os.getenv("SEED_POC", "true").lower() == "true"
    job_lease_seconds: int = int(os.getenv("JOB_LEASE_SECONDS", "180"))
    max_job_attempts: int = int(os.getenv("MAX_JOB_ATTEMPTS", "4"))


settings = Settings()
