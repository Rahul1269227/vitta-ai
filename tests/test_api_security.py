from __future__ import annotations

import io
from pathlib import Path

import pytest

from sentinelfi.services.api_security import (
    RedisSlidingWindowRateLimiter,
    SlidingWindowRateLimiter,
    build_rate_limiter,
    build_upload_path,
    is_api_key_allowed,
    parse_api_keys,
    persist_upload_with_size_limit,
)


def test_parse_api_keys() -> None:
    keys = parse_api_keys("alpha, beta, ,gamma")
    assert keys == ["alpha", "beta", "gamma"]


def test_is_api_key_allowed() -> None:
    assert is_api_key_allowed("alpha", ["alpha", "beta"]) is True
    assert is_api_key_allowed("nope", ["alpha", "beta"]) is False


def test_build_upload_path_uses_uuid_name(tmp_path) -> None:
    out = build_upload_path(tmp_path, ".csv")
    assert out.parent == tmp_path
    assert out.suffix == ".csv"
    assert out.name != ".csv"


def test_persist_upload_with_size_limit_success(tmp_path) -> None:
    data = io.BytesIO(b"hello-world")
    out_path = Path(tmp_path) / "file.csv"
    written = persist_upload_with_size_limit(data, out_path, max_bytes=1024)
    assert written == 11
    assert out_path.read_bytes() == b"hello-world"


def test_persist_upload_with_size_limit_fails_and_cleans(tmp_path) -> None:
    data = io.BytesIO(b"x" * 64)
    out_path = Path(tmp_path) / "file.csv"
    with pytest.raises(ValueError):
        persist_upload_with_size_limit(data, out_path, max_bytes=10, chunk_size=8)
    assert out_path.exists() is False


def test_sliding_window_rate_limiter_allows_within_limit() -> None:
    now = {"t": 0.0}

    def clock() -> float:
        return now["t"]

    limiter = SlidingWindowRateLimiter(limit=2, window_seconds=60, clock=clock)

    allowed, retry_after = limiter.allow("client-1")
    assert allowed is True
    assert retry_after == 0

    allowed, retry_after = limiter.allow("client-1")
    assert allowed is True
    assert retry_after == 0


def test_sliding_window_rate_limiter_blocks_until_window_expires() -> None:
    now = {"t": 0.0}

    def clock() -> float:
        return now["t"]

    limiter = SlidingWindowRateLimiter(limit=2, window_seconds=60, clock=clock)
    assert limiter.allow("client-1")[0] is True
    assert limiter.allow("client-1")[0] is True

    allowed, retry_after = limiter.allow("client-1")
    assert allowed is False
    assert retry_after == 60

    now["t"] = 30.0
    allowed, retry_after = limiter.allow("client-1")
    assert allowed is False
    assert retry_after == 30

    now["t"] = 61.0
    allowed, retry_after = limiter.allow("client-1")
    assert allowed is True
    assert retry_after == 0


def test_build_rate_limiter_defaults_to_memory_without_redis_url() -> None:
    limiter = build_rate_limiter(limit=10, window_seconds=60, backend="auto", redis_url=None)
    assert isinstance(limiter, SlidingWindowRateLimiter)


class _FakeRedisPipeline:
    def __init__(self, store: dict[str, list[tuple[str, int]]]) -> None:
        self.store = store
        self.ops: list[tuple] = []

    def zremrangebyscore(self, key: str, min_score: int, max_score: int):  # noqa: ANN001, ANN201
        self.ops.append(("zremrangebyscore", key, min_score, max_score))
        return self

    def zcard(self, key: str):  # noqa: ANN201
        self.ops.append(("zcard", key))
        return self

    def zadd(self, key: str, mapping: dict[str, int]):  # noqa: ANN201
        self.ops.append(("zadd", key, mapping))
        return self

    def expire(self, key: str, ttl: int):  # noqa: ANN201, ARG002
        self.ops.append(("expire", key))
        return self

    def execute(self):  # noqa: ANN201
        out: list[object] = []
        for op in self.ops:
            if op[0] == "zremrangebyscore":
                _, key, _min_score, max_score = op
                rows = self.store.get(key, [])
                self.store[key] = [(member, score) for member, score in rows if score > max_score]
                out.append(None)
            elif op[0] == "zcard":
                _, key = op
                out.append(len(self.store.get(key, [])))
            elif op[0] == "zadd":
                _, key, mapping = op
                rows = self.store.setdefault(key, [])
                rows.extend([(member, score) for member, score in mapping.items()])
                rows.sort(key=lambda item: item[1])
                out.append(1)
            elif op[0] == "expire":
                out.append(True)
        self.ops = []
        return out


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, list[tuple[str, int]]] = {}

    def pipeline(self) -> _FakeRedisPipeline:
        return _FakeRedisPipeline(self.store)

    def zrange(self, key: str, start: int, end: int, withscores: bool):  # noqa: ANN001, ANN201, ARG002
        rows = self.store.get(key, [])
        selected = rows[start : end + 1]
        if withscores:
            return selected
        return [item[0] for item in selected]


def test_redis_sliding_window_rate_limiter_blocks_after_limit(monkeypatch) -> None:
    now = {"t": 1000.0}

    def fake_time() -> float:
        return now["t"]

    monkeypatch.setattr("sentinelfi.services.api_security.time.time", fake_time)

    limiter = RedisSlidingWindowRateLimiter(_FakeRedis(), limit=2, window_seconds=60)
    assert limiter.allow("client-a")[0] is True
    assert limiter.allow("client-a")[0] is True

    allowed, retry_after = limiter.allow("client-a")
    assert allowed is False
    assert retry_after >= 1
