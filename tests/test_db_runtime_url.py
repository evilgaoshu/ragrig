from ragrig.config import Settings


def test_runtime_database_url_targets_localhost_for_host_side_commands() -> None:
    settings = Settings(
        database_url="postgresql://ragrig:ragrig_dev@db:5432/ragrig",
        db_host_port=25433,
    )

    assert settings.runtime_database_url == "postgresql://ragrig:ragrig_dev@localhost:25433/ragrig"
    assert settings.sqlalchemy_runtime_database_url == (
        "postgresql+psycopg://ragrig:ragrig_dev@localhost:25433/ragrig"
    )
