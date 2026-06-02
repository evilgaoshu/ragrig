from functools import lru_cache
from typing import Any

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from ragrig.config import Settings, assert_database_url_safe, get_settings
from ragrig.metrics import setup_db_pool_metrics


def create_db_engine(settings: Settings | None = None) -> Engine:
    active_settings = settings or get_settings()
    assert_database_url_safe(active_settings)
    engine = create_engine(
        active_settings.sqlalchemy_database_url,
        **_create_engine_kwargs(active_settings),
    )
    setup_db_pool_metrics(engine)
    return engine


def _create_engine_kwargs(settings: Settings) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"pool_pre_ping": True}
    if not _is_postgresql_url(settings.sqlalchemy_database_url):
        return kwargs

    kwargs.update(
        pool_size=settings.ragrig_db_pool_size,
        max_overflow=settings.ragrig_db_max_overflow,
        pool_recycle=settings.ragrig_db_pool_recycle,
    )
    return kwargs


def _is_postgresql_url(url: str) -> bool:
    try:
        parsed = make_url(url)
    except ArgumentError:
        return False
    return parsed.get_backend_name() == "postgresql"


@lru_cache(maxsize=1)
def get_db_engine() -> Engine:
    return create_db_engine()
