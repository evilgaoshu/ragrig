import pytest

from ragrig.config import Settings
from ragrig.main import create_runtime_settings

pytestmark = pytest.mark.unit

def test_runtime_database_url_targets_localhost_for_host_side_commands() -> None:
    settings = Settings(
        app_port=8000,
        database_url="postgresql://ragrig:ragrig_dev@db:5432/ragrig",
        db_host_port=25433,
    )

    assert settings.runtime_database_url == "postgresql://ragrig:ragrig_dev@localhost:25433/ragrig"
    assert settings.sqlalchemy_runtime_database_url == (
        "postgresql+psycopg://ragrig:ragrig_dev@localhost:25433/ragrig"
    )


def test_create_runtime_settings_retargets_host_side_web_app_to_runtime_database_url() -> None:
    settings = Settings(
        app_port=8000,
        database_url="postgresql://ragrig:ragrig_dev@db:5432/ragrig",
        db_host_port=25433,
    )

    runtime_settings = create_runtime_settings(settings)

    assert runtime_settings.database_url == "postgresql://ragrig:ragrig_dev@localhost:25433/ragrig"
    assert runtime_settings.sqlalchemy_database_url == (
        "postgresql+psycopg://ragrig:ragrig_dev@localhost:25433/ragrig"
    )
    assert runtime_settings.app_port == 8000
