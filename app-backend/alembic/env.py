import sys
import os
from logging.config import fileConfig

from alembic import context

# 将项目根目录添加到 sys.path 中，以便我们可以导入 core 模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 导入我们的数据库设置和模型
from core.database import engine, SQLALCHEMY_DATABASE_URL
from core.models import Base

# 这是 Alembic 配置对象，它提供了对所使用的 .ini 文件中数值的访问。
config = context.config

# 解析日志配置文件。
if config.config_file_name is not None and config.attributes.get("configure_logging", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# 设置目标元数据以支持自动生成迁移脚本 (autogenerate)
target_metadata = Base.metadata

def run_migrations_offline() -> None:
    """在“离线”（offline）模式下运行迁移。"""
    url = SQLALCHEMY_DATABASE_URL
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # SQLite 列修改需要使用 batch 模式
    )

    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online() -> None:
    """在“在线”（online）模式下运行迁移。"""
    connectable = engine

    with connectable.connect() as connection:
        # SQLite batch 重建被引用的表时，DROP TABLE 会触发 CASCADE/SET NULL。
        # 在事务外暂停外键执行，在同一写事务中校验完整性后才提交。
        foreign_keys = connection.exec_driver_sql("PRAGMA foreign_keys").scalar()
        connection.commit()
        try:
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            connection.commit()
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                render_as_batch=True,
                transactional_ddl=True,
            )
            with context.begin_transaction():
                context.run_migrations()
            violations = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise RuntimeError("迁移后外键校验失败，已回滚")
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.exec_driver_sql(f"PRAGMA foreign_keys={int(foreign_keys)}")
            connection.commit()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
