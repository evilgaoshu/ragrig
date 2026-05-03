from ragrig.config import Settings


def test_settings_exposes_sqlalchemy_database_url_for_psycopg() -> None:
    settings = Settings(
        database_url="postgresql://ragrig:ragrig_dev@db:5432/ragrig",
    )

    assert (
        settings.sqlalchemy_database_url == "postgresql+psycopg://ragrig:ragrig_dev@db:5432/ragrig"
    )
