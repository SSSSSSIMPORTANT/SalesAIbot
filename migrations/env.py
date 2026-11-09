from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from app.database import Base, engine


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# SQLAlchemy 模型描述的全部表结构。
target_metadata = Base.metadata

# 默认使用项目数据库，也允许命令行指定测试数据库。
arguments = context.get_x_argument(as_dictionary=True)
database_url = arguments.get("database_url", str(engine.url))


def run_migrations_offline():
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    migration_engine = create_engine(
        database_url,
        poolclass=pool.NullPool,
    )

    try:
        with migration_engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                render_as_batch=True,
                compare_type=True,
            )

            with context.begin_transaction():
                context.run_migrations()
    finally:
        migration_engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()