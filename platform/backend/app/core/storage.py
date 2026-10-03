"""Artifact storage with an explicit developer-local fallback and an S3 adapter."""

from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path
from typing import Protocol

from app.core.config import Settings


class ArtifactStore(Protocol):
    mode: str

    def put(self, key: str, data: bytes, content_type: str) -> str: ...
    def get(self, key: str) -> bytes: ...


def safe_key(key: str) -> str:
    p = Path(key)
    if p.is_absolute() or ".." in p.parts or not p.parts:
        raise ValueError("Invalid artifact key")
    return p.as_posix()


class LocalArtifactStore:
    mode = "local_file_fallback"

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        relative = safe_key(key)
        destination = (self.root / relative).resolve()
        if not destination.is_relative_to(self.root):
            raise ValueError("Invalid artifact path")
        destination.parent.mkdir(parents=True, exist_ok=True)
        expected = hashlib.sha256(data).hexdigest()
        try:
            # Link is atomic and fails if another writer already published this immutable key.
            temporary = destination.with_name(destination.name + f".{uuid.uuid4().hex}.tmp")
            with temporary.open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, destination)
            except FileExistsError:
                if hashlib.sha256(destination.read_bytes()).hexdigest() != expected:
                    raise ValueError("Immutable artifact key already contains different data") from None
            finally:
                temporary.unlink(missing_ok=True)
        except FileExistsError:
            if hashlib.sha256(destination.read_bytes()).hexdigest() != expected:
                raise ValueError("Immutable artifact key already contains different data") from None
        return relative

    def get(self, key: str) -> bytes:
        relative = safe_key(key)
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root) or not path.is_file():
            raise FileNotFoundError(relative)
        return path.read_bytes()


class S3ArtifactStore:
    mode = "s3"

    def __init__(self, settings: Settings):
        import boto3

        self.bucket = settings.s3_bucket
        self.client = boto3.client("s3", endpoint_url=settings.s3_endpoint_url, region_name=settings.aws_region)

    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        key = safe_key(key)
        expected = hashlib.sha256(data).hexdigest()
        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
                Metadata={"sha256": expected},
                IfNoneMatch="*",
            )
        except Exception as exc:
            # S3-compatible stores use 412 for an existing immutable key. If the endpoint
            # cannot enforce conditional writes, fail closed rather than risk overwriting.
            response = getattr(exc, "response", {}) or {}
            code = str(response.get("ResponseMetadata", {}).get("HTTPStatusCode", ""))
            error_code = str(response.get("Error", {}).get("Code", ""))
            if code not in ("409", "412") and error_code not in ("PreconditionFailed", "ConditionalRequestConflict"):
                raise RuntimeError("Conditional artifact write failed; existing objects were not overwritten") from exc
            existing = self.client.get_object(Bucket=self.bucket, Key=key)
            body = existing["Body"].read()
            if hashlib.sha256(body).hexdigest() != expected:
                raise ValueError("Immutable artifact key already contains different data") from None
        return key

    def get(self, key: str) -> bytes:
        key = safe_key(key)
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()


def create_artifact_store(settings: Settings) -> ArtifactStore:
    if settings.object_store_backend == "s3":
        return S3ArtifactStore(settings)
    if settings.object_store_backend == "local":
        return LocalArtifactStore(settings.local_artifact_dir)
    raise ValueError("OBJECT_STORE_BACKEND must be 's3' or 'local'")
