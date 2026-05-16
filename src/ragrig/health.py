from collections.abc import Callable

import psycopg

from ragrig.config import Settings
from ragrig.reranker import fake_reranker_policy


def create_database_check(settings: Settings) -> Callable[[], None]:
    def check_database() -> None:
        with psycopg.connect(settings.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()

    return check_database


def build_reranker_health(settings: Settings) -> dict[str, object]:
    return fake_reranker_policy(settings)
