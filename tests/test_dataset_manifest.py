from __future__ import annotations

import json
from pathlib import Path

import pytest

from sentinelfi.services.dataset_manifest import (
    DatasetManifestError,
    compute_sha256,
    ensure_dataset_artifact,
    load_manifest,
)


def _write_manifest(path: Path, dataset_id: str, url: str, sha256: str, size_bytes: int) -> None:
    payload = {
        "version": 1,
        "datasets": {
            dataset_id: {
                "url": url,
                "sha256": sha256,
                "size_bytes": size_bytes,
            }
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_load_manifest_missing_file(tmp_path) -> None:
    with pytest.raises(DatasetManifestError):
        load_manifest(tmp_path / "missing.json")


def test_ensure_dataset_artifact_accepts_valid_cached_file(tmp_path) -> None:
    dataset_id = "ds"
    url = "https://example.com/data.csv"
    cache = tmp_path / "data.csv"
    cache.write_bytes(b"abc123")
    sha = compute_sha256(cache)
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, dataset_id, url, sha, cache.stat().st_size)

    out = ensure_dataset_artifact(dataset_id, url, cache, manifest)
    assert out == cache
    assert out.read_bytes() == b"abc123"


def test_ensure_dataset_artifact_rejects_checksum_mismatch(tmp_path) -> None:
    dataset_id = "ds"
    url = "https://example.com/data.csv"
    cache = tmp_path / "data.csv"
    cache.write_bytes(b"abc123")
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, dataset_id, url, "0" * 64, cache.stat().st_size)

    with pytest.raises(DatasetManifestError):
        ensure_dataset_artifact(dataset_id, url, cache, manifest)


def test_ensure_dataset_artifact_downloads_and_validates(tmp_path, monkeypatch) -> None:
    dataset_id = "ds"
    url = "https://example.com/data.csv"
    cache = tmp_path / "data.csv"
    content = b"downloaded-content"

    expected_path = tmp_path / "expected.bin"
    expected_path.write_bytes(content)
    sha = compute_sha256(expected_path)

    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, dataset_id, url, sha, len(content))

    class FakeResponse:
        def __init__(self, payload: bytes) -> None:
            self.content = payload

        def raise_for_status(self) -> None:
            return None

    def fake_get(request_url: str, timeout: int):  # noqa: ARG001
        assert request_url == url
        return FakeResponse(content)

    monkeypatch.setattr("sentinelfi.services.dataset_manifest.requests.get", fake_get)

    out = ensure_dataset_artifact(dataset_id, url, cache, manifest)
    assert out.exists()
    assert out.read_bytes() == content
