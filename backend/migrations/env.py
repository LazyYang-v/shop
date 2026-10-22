import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from shop_api.database import Base
from shop_api.catalog import Product  # noqa: F401
from shop_api.identity import AuthSession, User  # noqa: F401
from shop_api.cart import CartItem  # noqa: F401
from shop_api.addresses import Address  # noqa: F401
from shop_api.orders import Order, OrderItem  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=os.getenv("SHOP_DATABASE_URL", config.get_main_option("sqlalchemy.url")),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {}) or {}
    section["sqlalchemy.url"] = os.getenv(
        "SHOP_DATABASE_URL", section["sqlalchemy.url"]
    )
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
