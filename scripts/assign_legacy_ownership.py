"""Assign previously unowned local customers and conversations to one operator."""

import argparse

from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import DATABASE_PATH, Conversation, Customer, OperatorAccount, engine
from app.services.operator_accounts import normalize_username


def assign_legacy_ownership(db: Session, username: str) -> tuple[int, int]:
    username = normalize_username(username)

    with db.begin():
        # Acquire SQLite's write lock before inspecting the records to be assigned.
        locked = db.execute(
            update(OperatorAccount)
            .where(OperatorAccount.username == username, OperatorAccount.is_active.is_(True))
            .values(is_active=True)
        )
        if locked.rowcount != 1:
            raise ValueError("找不到已启用的目标销售账号。")

        owner_id = db.scalar(
            select(OperatorAccount.id).where(OperatorAccount.username == username)
        )
        conflicting_conversation = db.scalar(
            select(Conversation.id)
            .join(Customer, Customer.id == Conversation.customer_id)
            .where(
                Conversation.owner_operator_id.is_(None),
                Customer.owner_operator_id.is_not(None),
                Customer.owner_operator_id != owner_id,
            )
            .limit(1)
        )
        if conflicting_conversation is not None:
            raise ValueError("有未分配会话关联了其他账号的客户，无法批量分配。")

        customers = db.execute(
            update(Customer)
            .where(Customer.owner_operator_id.is_(None))
            .values(owner_operator_id=owner_id)
        ).rowcount
        conversations = db.execute(
            update(Conversation)
            .where(Conversation.owner_operator_id.is_(None))
            .values(owner_operator_id=owner_id)
        ).rowcount

    return customers, conversations


def main() -> None:
    parser = argparse.ArgumentParser(description="把未分配的历史记录归给指定销售账号")
    parser.add_argument("--username", required=True)
    args = parser.parse_args()

    if not DATABASE_PATH.is_file():
        raise SystemExit("业务数据库不存在。")

    try:
        with Session(engine) as db:
            customers, conversations = assign_legacy_ownership(db, args.username)
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    except SQLAlchemyError:
        raise SystemExit("历史记录分配失败，请检查数据库和迁移版本。") from None

    print(f"已分配给 {normalize_username(args.username)}：{customers} 个客户、{conversations} 个会话。")


if __name__ == "__main__":
    main()
