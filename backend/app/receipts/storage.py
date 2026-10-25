"""Receipt photos in S3 (SeaweedFS locally). The API never proxies image bytes: phones upload
straight to storage with a presigned PUT URL, and the worker reads the object back."""

import time
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.config import settings

BUCKET = "receipts"
UPLOAD_TTL_SECONDS = 600


def _client(endpoint: str) -> Any:
    # Path-style addressing: local S3 servers serve buckets at /bucket, not bucket.host.
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def presign_put(key: str, content_type: str) -> str:
    """Signing is local computation (no network call). Content-Type is part of the signature,
    so the upload must send the same header."""
    url: str = _client(settings.s3_public_endpoint_url).generate_presigned_url(
        "put_object",
        Params={"Bucket": BUCKET, "Key": key, "ContentType": content_type},
        ExpiresIn=UPLOAD_TTL_SECONDS,
    )
    return url


def get_bytes(key: str) -> bytes:
    """Blocking (boto3 is sync): call through asyncio.to_thread."""
    body: bytes = (
        _client(settings.s3_endpoint_url).get_object(Bucket=BUCKET, Key=key)["Body"].read()
    )
    return body


def ensure_bucket() -> None:
    """Idempotent setup, run once per deploy: python -m app.receipts.storage.
    Retries while the storage server is still starting."""
    client = _client(settings.s3_endpoint_url)
    for _ in range(60):
        try:
            client.head_bucket(Bucket=BUCKET)
            return
        except ClientError:
            client.create_bucket(Bucket=BUCKET)
            return
        except BotoCoreError:  # connection refused: server not up yet
            time.sleep(1)
    raise RuntimeError(f"storage at {settings.s3_endpoint_url} never came up")


if __name__ == "__main__":
    ensure_bucket()
