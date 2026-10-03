"""Alembic environment: runs revisions against the application's metadata and configured database."""

from alembic import context

from app.core import config as app_config
from app.core.database import make_engine
from app.models import Base

target_metadata = Base.metadata
OPTIONS = {"target_metadata": target_metadata, "render_as_batch": True, "compare_type": True}


def run_offline() -> None:
    url = context.config.get_main_option("sqlalchemy.url") or app_config.settings.database_url
    context.configure(url=url, literal_binds=True, dialect_opts={"paramstyle": "named"}, **OPTIONS)
    with context.begin_transaction():
        context.run_migrations()


def run_online() -> None:
    # app.core.migrate passes its own connection so the advisory lock and migration share a transaction.
    connection = context.config.attributes.get("connection")
    if connection is not None:
        context.configure(connection=connection, **OPTIONS)
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = make_engine(context.config.get_main_option("sqlalchemy.url") or app_config.settings.database_url)
    try:
        with engine.begin() as connection:
            context.configure(connection=connection, **OPTIONS)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_offline()
else:
    run_online()
