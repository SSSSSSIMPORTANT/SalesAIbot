import argparse
import warnings
from getpass import GetPassWarning, getpass

from argon2.exceptions import HashingError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import DATABASE_PATH, engine
from app.services.operator_accounts import (
    OperatorAlreadyExistsError,
    create_operator_account,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="创建本地销售账号")
    parser.add_argument("--username", required=True)
    args = parser.parse_args()

    if not DATABASE_PATH.is_file():
        raise SystemExit("业务数据库不存在，请先执行迁移。")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", GetPassWarning)
            password = getpass("输入密码：")
            confirmation = getpass("再次输入密码：")
    except (GetPassWarning, EOFError):
        raise SystemExit("请在支持隐藏输入的交互终端中运行。") from None

    if password != confirmation:
        raise SystemExit("两次输入的密码不一致。")

    try:
        with Session(engine) as db:
            account = create_operator_account(
                db,
                username=args.username,
                password=password,
            )
            print(f"已创建销售账号 {account.username}")
    except (ValueError, OperatorAlreadyExistsError) as exc:
        raise SystemExit(str(exc)) from None
    except (HashingError, SQLAlchemyError):
        raise SystemExit("建号失败，请检查密码散列依赖和数据库迁移。") from None


if __name__ == "__main__":
    main()
