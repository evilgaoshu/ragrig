from collections.abc import Callable, Generator
from threading import Lock

from sqlalchemy.orm import Session, sessionmaker

from ragrig.db.engine import get_db_engine

_session_factory_lock = Lock()
_session_factory: sessionmaker[Session] | None = None


def _default_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        with _session_factory_lock:
            if _session_factory is None:
                _session_factory = sessionmaker(
                    bind=get_db_engine(),
                    autoflush=False,
                    autocommit=False,
                    expire_on_commit=False,
                )
    return _session_factory


class _LazySessionLocal:
    def __call__(self) -> Session:
        return _default_session_factory()()


SessionLocal = _LazySessionLocal()


def get_db_session(
    session_factory: Callable[[], Session] | None = None,
) -> Generator[Session, None, None]:
    factory = session_factory or SessionLocal
    session = factory()
    try:
        yield session
    finally:
        session.close()


def get_session() -> Generator[Session, None, None]:
    """FastAPI dependency for a DB session.

    create_app() overrides this with a session-factory-aware closure so tests
    and custom factories work correctly. This default falls back to SessionLocal.
    """
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
