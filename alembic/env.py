from sqlalchemy import engine_from_config, pool

from alembic import context
from app.config.settings import get_settings
from app.db.session import Base
from app.models import core  # noqa: F401

config = context.config
# ConfigParser reserves percent signs for interpolation. SQLAlchemy URLs commonly
# contain percent-encoded passwords, so escape them only for Alembic's config layer.
config.set_main_option("sqlalchemy.url", get_settings().database_url.replace("%", "%%"))


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
