"""
GCS persistence helpers — optional.

If GCS_BUCKET env var is not set, all operations are no-ops.
Cloud Run uses ADC (service account) automatically — no key file needed.
"""

import logging
import os
from pathlib import Path

_bucket = None
_logger = logging.getLogger('gcs_storage')


def _get_bucket():
    global _bucket
    if _bucket is not None:
        return _bucket
    name = os.getenv('GCS_BUCKET', '')
    if not name:
        _logger.warning('[GCS] GCS_BUCKET not set — persistence disabled.')
        return None
    try:
        from google.cloud import storage
        _bucket = storage.Client().bucket(name)
        _logger.info(f'[GCS] Connected to bucket: {name}')
    except Exception as e:
        _logger.error(f'[GCS] Failed to connect to bucket {name}: {e}')
    return _bucket


def download(remote_path: str, local_path: Path) -> bool:
    """Download blob to local_path. Returns True if found and downloaded."""
    try:
        b = _get_bucket()
        if b is None:
            return False
        blob = b.blob(remote_path)
        if not blob.exists():
            return False
        local_path.parent.mkdir(parents=True, exist_ok=True)
        blob.download_to_filename(str(local_path))
        _logger.info(f'[GCS] Downloaded {remote_path}')
        return True
    except Exception as e:
        _logger.error(f'[GCS] Download failed for {remote_path}: {e}')
        return False


def upload(local_path: Path, remote_path: str) -> None:
    """Upload local_path to GCS. No-op if GCS not configured or file missing."""
    try:
        b = _get_bucket()
        if b is None or not local_path.exists():
            return
        b.blob(remote_path).upload_from_filename(str(local_path))
        _logger.info(f'[GCS] Uploaded {remote_path}')
    except Exception as e:
        _logger.error(f'[GCS] Upload failed for {remote_path}: {e}')
