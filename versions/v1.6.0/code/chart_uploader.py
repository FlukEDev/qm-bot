"""
Upload a rendered chart PNG to Cloudflare R2 and return its public HTTPS URL.

R2 is S3-compatible, so the plain `boto3` S3 client works against R2's
account-scoped endpoint — no Cloudflare-specific SDK needed.

LINE fetches the image itself (see line_notifier.py), so the URL must be
public and HTTPS. The object key always carries a random token: this bucket
is public, and a guessable name like "BTCUSDT_1h.png" would let anyone
enumerate every chart the bot has ever posted.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path


class UploadError(RuntimeError):
    pass


def upload_chart(png_path: str | Path, prefix: str = "charts") -> str:
    """Upload `png_path` to the configured R2 bucket, return its public URL.

    Reads R2_ACCOUNT_ID / R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY / R2_BUCKET /
    R2_PUBLIC_BASE_URL from the environment (populate them from .env before
    the process starts, e.g. via `python-dotenv` or your process manager).
    """
    account_id = os.environ.get("R2_ACCOUNT_ID")
    access_key = os.environ.get("R2_ACCESS_KEY_ID")
    secret_key = os.environ.get("R2_SECRET_ACCESS_KEY")
    bucket = os.environ.get("R2_BUCKET")
    public_base = os.environ.get("R2_PUBLIC_BASE_URL")

    missing = [
        name
        for name, val in [
            ("R2_ACCOUNT_ID", account_id),
            ("R2_ACCESS_KEY_ID", access_key),
            ("R2_SECRET_ACCESS_KEY", secret_key),
            ("R2_BUCKET", bucket),
            ("R2_PUBLIC_BASE_URL", public_base),
        ]
        if not val
    ]
    if missing:
        raise UploadError(f"missing R2 env vars: {', '.join(missing)}")

    import boto3  # imported lazily so --dry-run doesn't need it installed

    s3 = boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="auto",
    )

    key = f"{prefix}/{uuid.uuid4().hex}.png"
    try:
        s3.upload_file(
            str(png_path), bucket, key,
            ExtraArgs={"ContentType": "image/png", "CacheControl": "public, max-age=31536000"},
        )
    except Exception as exc:  # noqa: BLE001 — surface as our own error type
        raise UploadError(f"R2 upload failed: {exc}") from exc

    return f"{public_base.rstrip('/')}/{key}"
