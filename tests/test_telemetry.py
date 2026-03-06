from __future__ import annotations

from fastapi import FastAPI

from sentinelfi.core.config import Settings
from sentinelfi.services.telemetry import setup_opentelemetry


def test_setup_opentelemetry_disabled_returns_false() -> None:
    app = FastAPI()
    settings = Settings(otel_enabled=False)
    assert setup_opentelemetry(app, settings) is False
