"""Centralized file-upload helper.

Storage backends are selected by environment configuration and degrade safely:

* **Cloudinary**  — set ``CLOUDINARY_URL`` (or ``CLOUDINARY_*`` vars). Used for
  images/video; returns a CDN URL. Great for demos and free tiers.
* **AWS S3**      — set ``AWS_S3_BUCKET`` (+ ``AWS_*`` creds/region). Used for all
  file types; returns a public/read URL.
* **Local**       — default. Saves into ``app/static/uploads`` and returns a
  relative ``/static/uploads/...`` URL served by the static mount.

The same helper is used by chat attachments and avatar uploads so behaviour is
consistent and the demo keeps working with zero configuration.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Optional

from app.core.config import settings

LOCAL_UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent / "static" / "uploads"

# Extension -> broad category, used to pick a Cloudinary resource_type.
_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
_VIDEO_EXT = {".mp4", ".mov", ".webm", ".ogg"}
_DOC_EXT = {".pdf", ".doc", ".docx", ".txt", ".xls", ".xlsx", ".csv", ".zip"}


def _allowed(ext: str, allowlist: set[str]) -> bool:
    return ext.lower() in allowlist


def _validate_content(data: bytes, ext: str) -> None:
    """Reject files whose bytes don't match the type implied by the extension.

    Images are sniffed by magic bytes (cheap, catches most spoofing). Video/doc
    types are harder to sniff reliably, so we trust the extension allowlist for
    those (they are served, not executed).
    """
    if ext in _IMAGE_EXT:
        image_sigs = (
            b"\xff\xd8\xff",  # JPEG
            b"\x89PNG",      # PNG
            b"GIF8",         # GIF
            b"RIFF",         # WEBP (RIFF....WEBP)
        )
        if not any(data[: len(sig)] == sig for sig in image_sigs):
            raise ValueError("File content does not match an image type")
    # PDFs: require the %PDF header.
    if ext == ".pdf" and not data[:4] == b"%PDF":
        raise ValueError("File content does not match a PDF")


async def save_upload(
    data: bytes,
    filename: str,
    *,
    allowlist: set[str],
    max_bytes: int,
    folder: str = "uploads",
    resource_type: Optional[str] = None,
) -> str:
    """Persist ``data`` and return a URL/identifier the app can store + serve.

    ``resource_type`` lets callers hint at "image"/"video"/"auto" for Cloudinary
    (otherwise derived from the extension).
    """
    ext = Path(filename or "").suffix.lower()
    if not _allowed(ext, allowlist):
        raise ValueError("Unsupported file type")
    if len(data) > max_bytes:
        raise ValueError(f"File too large (max {max_bytes // (1024 * 1024)}MB)")

    # Basic content sniffing: reject files whose bytes don't match the type
    # implied by their extension (stops ".png" executables, etc.).
    _validate_content(data, ext)

    name = f"{uuid.uuid4().hex}{ext}"

    # 1) Cloudinary
    if settings.CLOUDINARY_URL or (settings.CLOUDINARY_API_KEY and settings.CLOUDINARY_CLOUD_NAME):
        url = _to_cloudinary(data, name, ext, folder, resource_type)
        if url:
            return url

    # 2) AWS S3
    if settings.AWS_S3_BUCKET:
        url = _to_s3(data, name, ext, folder)
        if url:
            return url

    # 3) Local fallback (default, zero-config)
    LOCAL_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    (LOCAL_UPLOAD_DIR / name).write_bytes(data)
    return f"/static/uploads/{name}"


def _to_cloudinary(data: bytes, name: str, ext: str, folder: str,
                   resource_type: Optional[str]) -> Optional[str]:
    try:
        import cloudinary
        import cloudinary.uploader
    except ImportError:
        return None
    if settings.CLOUDINARY_URL:
        cloudinary.config(cloudinary_url=settings.CLOUDINARY_URL)
    else:
        cloudinary.config(
            cloud_name=settings.CLOUDINARY_CLOUD_NAME,
            api_key=settings.CLOUDINARY_API_KEY,
            api_secret=settings.CLOUDINARY_API_SECRET,
        )
    rtype = resource_type or ("video" if ext in _VIDEO_EXT else "image" if ext in _IMAGE_EXT else "auto")
    try:
        resp = cloudinary.uploader.upload(
            data, public_id=f"{folder}/{name}", resource_type=rtype, overwrite=True
        )
        return resp.get("secure_url") or resp.get("url")
    except Exception:
        return None


def _to_s3(data: bytes, name: str, ext: str, folder: str) -> Optional[str]:
    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError
    except ImportError:
        return None
    try:
        s3 = boto3.client(
            "s3",
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_REGION,
        )
        key = f"{folder}/{name}"
        s3.put_object(Bucket=settings.AWS_S3_BUCKET, Key=key, Body=data)
        if settings.AWS_S3_CUSTOM_DOMAIN:
            return f"https://{settings.AWS_S3_CUSTOM_DOMAIN}/{key}"
        return f"https://{settings.AWS_S3_BUCKET}.s3.{settings.AWS_REGION}.amazonaws.com/{key}"
    except (BotoCoreError, ClientError, Exception):
        return None
