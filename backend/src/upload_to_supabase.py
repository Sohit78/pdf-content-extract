import logging
import mimetypes
import tempfile
from urllib.parse import quote
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

from .compression import DEFAULT_TARGET_BYTES, compress_pdf, human_size

load_dotenv()

logger = logging.getLogger(__name__)


def _prepare_for_upload(
    local_file: Path,
    staging_dir: Path,
    max_bytes: Optional[int],
    compress_pdfs: bool,
) -> Path:
    size = local_file.stat().st_size
    if max_bytes is None or size <= max_bytes:
        return local_file

    if not (compress_pdfs and local_file.suffix.lower() == ".pdf"):
        raise ValueError(
            f"{local_file.name} is {human_size(size)}, over the {human_size(max_bytes)} upload limit, "
            "and cannot be compressed."
        )

    result = compress_pdf(local_file, staging_dir / local_file.name, target_bytes=max_bytes)
    logger.info(
        "Compressed %s from %s to %s via %s",
        local_file.name,
        human_size(result.original_bytes),
        human_size(result.final_bytes),
        result.strategy,
    )
    return result.path


def supabase_upload_file(
    supabase_url: str,
    service_role_key: str,
    bucket: str,
    local_file: Path,
    object_path: str,
    upsert: bool = True,
    max_bytes: Optional[int] = DEFAULT_TARGET_BYTES,
    compress_pdfs: bool = True,
) -> str:

    local_file = Path(local_file)
    if not local_file.is_file():
        raise ValueError(f"No such file: {local_file}")

    # Name the mime type off the original, so compression cannot change it.
    mime, _ = mimetypes.guess_type(str(local_file))
    mime = mime or "application/octet-stream"

    upload_url = f"{supabase_url}/storage/v1/object/{bucket}/{quote(object_path)}"

    headers = {
        "Authorization": f"Bearer {service_role_key}",
        "apikey": service_role_key,
        "Content-Type": mime,
        "x-upsert": "true" if upsert else "false",
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        payload_file = _prepare_for_upload(local_file, Path(tmpdir), max_bytes, compress_pdfs)

        with payload_file.open("rb") as f:
            resp = requests.post(upload_url, headers=headers, data=f)

    # Some Supabase setups may return 200/201; handle both.
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Upload failed ({resp.status_code}): {resp.text}")

    # Public URL format (only works if the bucket is public)
    public_url = f"{supabase_url}/storage/v1/object/public/{bucket}/{quote(object_path)}"
    return public_url
