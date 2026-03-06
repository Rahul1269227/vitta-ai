from __future__ import annotations

import math
import secrets
import threading
import time
import uuid
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, BinaryIO, Callable, Protocol


def parse_api_keys(api_keys_csv: str) -> list[str]:
    return [key.strip() for key in api_keys_csv.split(",") if key.strip()]


def is_api_key_allowed(provided: str, allowed_keys: list[str]) -> bool:
    if not provided:
        return False
    for key in allowed_keys:
        if secrets.compare_digest(provided, key):
            return True
    return False


class SlidingWindowRateLimiter:
    def __init__(
        self,
        limit: int,
        window_seconds: int = 60,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.limit = max(0, limit)
        self.window_seconds = max(1, window_seconds)
        self._clock = clock or time.time
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> tuple[bool, int]:
        if self.limit <= 0:
            return True, 0

        now = float(self._clock())
        window_start = now - self.window_seconds

        with self._lock:
            bucket = self._requests[key]
            while bucket and bucket[0] <= window_start:
                bucket.popleft()

            if len(bucket) >= self.limit:
                retry_after = max(1, math.ceil(self.window_seconds - (now - bucket[0])))
                return False, retry_after

            bucket.append(now)
            return True, 0


class RateLimiter(Protocol):
    def allow(self, key: str) -> tuple[bool, int]:
        ...


class RedisSlidingWindowRateLimiter:
    def __init__(
        self,
        redis_client: Any,
        limit: int,
        window_seconds: int = 60,
        namespace: str = "sentinelfi:ratelimit",
    ) -> None:
        self.redis_client = redis_client
        self.limit = max(0, limit)
        self.window_seconds = max(1, window_seconds)
        self.namespace = namespace

    def allow(self, key: str) -> tuple[bool, int]:
        if self.limit <= 0:
            return True, 0

        now_ms = int(time.time() * 1000)
        window_ms = self.window_seconds * 1000
        min_allowed = now_ms - window_ms
        redis_key = f"{self.namespace}:{key}"
        member = f"{now_ms}-{uuid.uuid4().hex}"

        pipe = self.redis_client.pipeline()
        pipe.zremrangebyscore(redis_key, 0, min_allowed)
        pipe.zcard(redis_key)
        _, count = pipe.execute()
        count_int = int(count)
        if count_int >= self.limit:
            first = self.redis_client.zrange(redis_key, 0, 0, withscores=True)
            if first:
                oldest_ms = int(first[0][1])
                retry_after = max(1, math.ceil((window_ms - (now_ms - oldest_ms)) / 1000))
            else:
                retry_after = 1
            return False, retry_after

        pipe = self.redis_client.pipeline()
        pipe.zadd(redis_key, {member: now_ms})
        pipe.expire(redis_key, self.window_seconds + 5)
        pipe.execute()
        return True, 0


def build_rate_limiter(
    *,
    limit: int,
    window_seconds: int,
    backend: str = "auto",
    redis_url: str | None = None,
) -> RateLimiter:
    backend_normalized = backend.strip().lower()
    prefer_redis = backend_normalized in {"auto", "redis"}

    if prefer_redis and redis_url:
        try:
            import redis  # type: ignore[import-not-found]

            client = redis.Redis.from_url(redis_url, decode_responses=True)
            client.ping()
            return RedisSlidingWindowRateLimiter(client, limit=limit, window_seconds=window_seconds)
        except Exception:
            if backend_normalized == "redis":
                raise

    return SlidingWindowRateLimiter(limit=limit, window_seconds=window_seconds)


def build_upload_path(upload_dir: Path, suffix: str) -> Path:
    upload_dir.mkdir(parents=True, exist_ok=True)
    return upload_dir / f"{uuid.uuid4().hex}{suffix}"


def persist_upload_with_size_limit(
    source: BinaryIO,
    out_path: Path,
    max_bytes: int,
    chunk_size: int = 1024 * 1024,
) -> int:
    written = 0
    with out_path.open("wb") as handle:
        while True:
            chunk = source.read(chunk_size)
            if not chunk:
                break
            written += len(chunk)
            if written > max_bytes:
                handle.close()
                out_path.unlink(missing_ok=True)
                raise ValueError(f"File exceeds size limit of {max_bytes} bytes")
            handle.write(chunk)
    return written
