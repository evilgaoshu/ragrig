from functools import lru_cache

from sqlalchemy import Engine, create_engine

from ragrig.config import Settings, get_settings
from ragrig.metrics import setup_db_pool_metrics


def create_db_engine(settings: Settings | None = None) -> Engine:
    active_settings = settings or get_settings()
    engine = create_engine(active_settings.sqlalchemy_database_url, pool_pre_ping=True)
    setup_db_pool_metrics(engine)
    return engine


@lru_cache(maxsize=1)
def get_db_engine() -> Engine:
    return create_db_engine()
