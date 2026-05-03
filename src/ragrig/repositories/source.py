from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ragrig.db.models import Source


def get_or_create_source(
    session: Session,
    *,
    knowledge_base_id,
    uri: str,
    config_json: dict[str, object],
) -> Source:
    source = session.scalar(
        select(Source).where(Source.knowledge_base_id == knowledge_base_id, Source.uri == uri)
    )
    if source is not None:
        source.config_json = config_json
        session.flush()
        return source

    source = Source(
        knowledge_base_id=knowledge_base_id,
        kind="local_directory",
        uri=uri,
        config_json=config_json,
    )
    session.add(source)
    session.flush()
    return source
