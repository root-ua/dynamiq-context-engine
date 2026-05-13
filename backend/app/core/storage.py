"""Thin wrapper around the S3-compatible MinIO client.

Used today by the data-export job; designed so future code that needs to
push artifacts (uploads, reports, exports) shares the same client +
pre-sign helper without each call site repeating the bootstrap.

Lazy-initialized: the first call constructs the client; subsequent calls
reuse it.
"""
from __future__ import annotations

from datetime import timedelta
from threading import Lock
from urllib.parse import urlparse

from minio import Minio

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)

_client: Minio | None = None
_lock = Lock()


def get_client() -> Minio:
    global _client
    if _client is not None:
        return _client
    with _lock:
        if _client is not None:
            return _client
        settings = get_settings()
        parsed = urlparse(settings.s3_endpoint)
        endpoint = parsed.netloc or parsed.path  # supports "host:9000"
        secure = parsed.scheme == "https"
        _client = Minio(
            endpoint,
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key,
            secure=secure,
            region=settings.s3_region,
        )
        return _client


def ensure_bucket(bucket: str | None = None) -> str:
    """Create the bucket if it doesn't exist; return the name."""
    settings = get_settings()
    name = bucket or settings.s3_bucket
    client = get_client()
    if not client.bucket_exists(name):
        client.make_bucket(name, location=settings.s3_region)
        log.info("storage.bucket.created", bucket=name)
    return name


def put_object(
    *,
    key: str,
    data: bytes,
    bucket: str | None = None,
    content_type: str = "application/octet-stream",
) -> tuple[str, int]:
    """Upload ``data`` to ``key`` in the bucket. Returns ``(bucket, size)``."""
    import io
    name = ensure_bucket(bucket)
    client = get_client()
    stream = io.BytesIO(data)
    client.put_object(
        bucket_name=name,
        object_name=key,
        data=stream,
        length=len(data),
        content_type=content_type,
    )
    return name, len(data)


def presign_get(
    *, key: str, bucket: str | None = None, expires: timedelta | None = None
) -> str:
    """Return a pre-signed GET URL good for ``expires`` (default 24h)."""
    settings = get_settings()
    name = bucket or settings.s3_bucket
    return get_client().presigned_get_object(
        bucket_name=name,
        object_name=key,
        expires=expires or timedelta(hours=24),
    )
