from collections.abc import Callable, Generator

from sqlalchemy.orm import Session, sessionmaker

from ragrig.db.engine import get_db_engine

SessionLocal = sessionmaker(
    bind=get_db_engine(), autoflush=False, autocommit=False, expire_on_commit=False
)


def get_db_session(
    session_factory: Callable[[], Session] | None = None,
) -> Generator[Session, None, None]:
    factory = session_factory or SessionLocal
    session = factory()
    try:
        yield session
    finally:
        session.close()
