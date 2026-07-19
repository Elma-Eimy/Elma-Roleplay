import sys
import os
from logging.config import fileConfig

from alembic import context

# Importing core.database normally performs the application's automatic startup
# migration. While Alembic is already loading this env.py, that side effect would
# recursively invoke Alembic before context.config is ready. The guard is scoped
# to this env load and restored after migrations finish.
_migration_guard_name = "APP_ALEMBIC_ENV_ACTIVE"
_previous_migration_guard = os.environ.get(_migration_guard_name)
os.environ[_migration_guard_name] = "1"

# Add the project root to sys.path so we can import core modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import our database settings and models
from core.database import engine, SQLALCHEMY_DATABASE_URL
from core.models import Base

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Set target metadata for autogenerate support
target_metadata = Base.metadata

def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = SQLALCHEMY_DATABASE_URL
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # SQLite column alterations require batch mode
    )

    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # SQLite column alterations require batch mode
        )

        with context.begin_transaction():
            context.run_migrations()

try:
    if context.is_offline_mode():
        run_migrations_offline()
    else:
        run_migrations_online()
finally:
    if _previous_migration_guard is None:
        os.environ.pop(_migration_guard_name, None)
    else:
        os.environ[_migration_guard_name] = _previous_migration_guard
