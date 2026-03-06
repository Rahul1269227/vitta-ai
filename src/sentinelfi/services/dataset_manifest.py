from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import requests

DEFAULT_MANIFEST_PATH = Path("data/external/dataset_manifest.json")


class DatasetManifestError(RuntimeError):
    pass


def compute_sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest(path: Path = DEFAULT_MANIFEST_PATH) -> dict[str, Any]:
    if not path.exists():
        raise DatasetManifestError(f"Dataset manifest missing: {path}")

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DatasetManifestError(f"Invalid dataset manifest JSON: {path}") from exc

    if not isinstance(payload, dict):
        raise DatasetManifestError("Dataset manifest root must be an object")
    datasets = payload.get("datasets")
    if not isinstance(datasets, dict):
        raise DatasetManifestError("Dataset manifest must include object key 'datasets'")

    return payload


def ensure_dataset_artifact(
    dataset_id: str,
    url: str,
    cache_path: Path,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    timeout_seconds: int = 90,
) -> Path:
    manifest = load_manifest(manifest_path)
    datasets = manifest["datasets"]
    entry = datasets.get(dataset_id)

    if not isinstance(entry, dict):
        raise DatasetManifestError(f"Dataset '{dataset_id}' missing from manifest: {manifest_path}")

    expected_url = str(entry.get("url", "")).strip()
    expected_sha256 = str(entry.get("sha256", "")).strip().lower()
    expected_size = int(entry.get("size_bytes", 0))

    if expected_url != url:
        raise DatasetManifestError(
            f"Manifest URL mismatch for {dataset_id}: expected '{expected_url}', got '{url}'"
        )
    if len(expected_sha256) != 64:
        raise DatasetManifestError(f"Invalid sha256 in manifest for {dataset_id}")
    if expected_size <= 0:
        raise DatasetManifestError(f"Invalid size_bytes in manifest for {dataset_id}")

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    if cache_path.exists():
        actual_sha = compute_sha256(cache_path)
        actual_size = cache_path.stat().st_size
        if actual_sha != expected_sha256 or actual_size != expected_size:
            raise DatasetManifestError(
                f"Cached dataset integrity check failed for {dataset_id}: "
                f"path={cache_path} sha256={actual_sha} size={actual_size}"
            )
        return cache_path

    response = requests.get(url, timeout=timeout_seconds)
    response.raise_for_status()

    tmp_path = cache_path.with_suffix(f"{cache_path.suffix}.tmp")
    try:
        tmp_path.write_bytes(response.content)
        actual_sha = compute_sha256(tmp_path)
        actual_size = tmp_path.stat().st_size
        if actual_sha != expected_sha256 or actual_size != expected_size:
            raise DatasetManifestError(
                f"Downloaded dataset integrity check failed for {dataset_id}: "
                f"sha256={actual_sha} size={actual_size}"
            )
        tmp_path.replace(cache_path)
    finally:
        tmp_path.unlink(missing_ok=True)

    return cache_path
