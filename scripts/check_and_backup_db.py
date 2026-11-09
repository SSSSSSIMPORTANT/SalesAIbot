import sqlite3
from datetime import datetime

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from app.database import Base, DATABASE_PATH, engine


def main():
    if not DATABASE_PATH.exists():
        raise SystemExit("业务数据库不存在，请先检查路径。")

    with engine.connect() as connection:
        context = MigrationContext.configure(
            connection,
            opts={"compare_type": True},
        )

        differences = compare_metadata(context, Base.metadata)

    if differences:
        print("数据库与当前模型存在差异：")
        print(differences)
        raise SystemExit("请先核对差异，暂不标记迁移版本。")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_path = DATABASE_PATH.with_name(
        f"salesaibot_backup_{timestamp}.db"
    )

    source_url = DATABASE_PATH.resolve().as_uri() + "?mode=ro"

    with sqlite3.connect(source_url, uri=True) as source:
        with sqlite3.connect(backup_path) as target:
            source.backup(target)

    print("表结构与当前模型一致。")
    print(f"备份完成：{backup_path}")


if __name__ == "__main__":
    main()