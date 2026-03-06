from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

from alembic.config import Config
from sqlmodel import Session, create_engine

from alembic import command
from sentinelfi.core.config import Settings, get_settings
from sentinelfi.repositories import models as _models  # noqa: F401

_ENGINE_CACHE: dict[str, object] = {}


def get_engine(settings: Settings | None = None):
    cfg = settings or get_settings()
    if cfg.database_url not in _ENGINE_CACHE:
        _ENGINE_CACHE[cfg.database_url] = create_engine(cfg.database_url, echo=False)
    return _ENGINE_CACHE[cfg.database_url]


@contextmanager
def session_scope(settings: Settings | None = None):
    engine = get_engine(settings)
    with Session(engine) as session:
        yield session


def _project_root() -> Path:
    env_root = os.getenv("SENTINELFI_PROJECT_ROOT")
    candidates: list[Path] = []
    if env_root:
        candidates.append(Path(env_root).expanduser().resolve(strict=False))

    module_path = Path(__file__).resolve()
    candidates.extend(
        [
            module_path.parents[3],
            module_path.parents[2],
            Path.cwd().resolve(strict=False),
            Path.cwd().resolve(strict=False).parent,
            Path("/app"),
        ]
    )

    for root in candidates:
        if (root / "alembic.ini").exists() and (root / "alembic").is_dir():
            return root
    return module_path.parents[3]


def _alembic_config(settings: Settings) -> Config:
    root = _project_root()
    ini_path = root / "alembic.ini"
    if not ini_path.exists():
        raise FileNotFoundError(f"Alembic config not found: {ini_path}")

    cfg = Config(str(ini_path))
    cfg.set_main_option("script_location", str(root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    return cfg


def run_migrations(settings: Settings | None = None) -> None:
    cfg = settings or get_settings()
    alembic_cfg = _alembic_config(cfg)
    command.upgrade(alembic_cfg, "head")


def init_db(settings: Settings | None = None) -> None:
    run_migrations(settings)
