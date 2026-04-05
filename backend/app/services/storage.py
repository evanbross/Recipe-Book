"""
Storage service: uploads and retrieves files from Cloudflare R2.
R2 is S3-compatible, so we use boto3 with a custom endpoint.
"""
import io
import uuid
from typing import Optional
import boto3
from PIL import Image
from app.config import settings

_s3 = boto3.client(
    "s3",
    endpoint_url=f"https://{settings.r2_account_id}.r2.cloudflarestorage.com",
    aws_access_key_id=settings.r2_access_key_id,
    aws_secret_access_key=settings.r2_secret_access_key,
    region_name="auto",
)

THUMBNAIL_SIZE = (400, 400)


def _object_url(key: str) -> str:
    return f"{settings.r2_public_url}/{key}"


def upload_image(image_bytes: bytes, media_type: str = "image/jpeg", folder: str = "originals") -> dict[str, str]:
    """
    Upload original image to R2 and generate a thumbnail.
    Returns dict with keys: image_key, image_url, thumbnail_key, thumbnail_url
    """
    ext = media_type.split("/")[-1].replace("jpeg", "jpg")
    uid = uuid.uuid4().hex

    # Upload original
    image_key = f"{folder}/{uid}.{ext}"
    _s3.put_object(
        Bucket=settings.r2_bucket_name,
        Key=image_key,
        Body=image_bytes,
        ContentType=media_type,
    )

    # Generate and upload thumbnail
    thumb_bytes = _make_thumbnail(image_bytes)
    thumbnail_key = f"thumbnails/{uid}.jpg"
    _s3.put_object(
        Bucket=settings.r2_bucket_name,
        Key=thumbnail_key,
        Body=thumb_bytes,
        ContentType="image/jpeg",
    )

    return {
        "image_key": image_key,
        "image_url": _object_url(image_key),
        "thumbnail_key": thumbnail_key,
        "thumbnail_url": _object_url(thumbnail_key),
    }


def delete_image(image_key: str, thumbnail_key: Optional[str] = None) -> None:
    """Delete image (and optional thumbnail) from R2."""
    keys = [{"Key": image_key}]
    if thumbnail_key:
        keys.append({"Key": thumbnail_key})
    _s3.delete_objects(
        Bucket=settings.r2_bucket_name,
        Delete={"Objects": keys},
    )


def _make_thumbnail(image_bytes: bytes) -> bytes:
    """Resize image to thumbnail using Pillow."""
    img = Image.open(io.BytesIO(image_bytes))
    img.thumbnail(THUMBNAIL_SIZE, Image.LANCZOS)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=85)
    return out.getvalue()
