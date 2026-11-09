import re

from argon2 import PasswordHasher
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import OperatorAccount


password_hasher = PasswordHasher()


class OperatorAlreadyExistsError(Exception):
    """规范化后的用户名已存在。"""


def normalize_username(username: str) -> str:
    username = username.strip()

    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{2,31}", username):
        raise ValueError(
            "用户名须为 3 到 32 个字符，以英文字母或数字开头，"
            "其余字符可使用英文字母、数字、下划线、点或短横线。"
        )

    return username.lower()


def create_operator_account(
    db: Session,
    *,
    username: str,
    password: str,
) -> OperatorAccount:
    username = normalize_username(username)

    if not 15 <= len(password) <= 128 or password.isspace():
        raise ValueError(
            "密码须为 15 到 128 个字符，并包含非空白字符。"
        )

    account = OperatorAccount(
        username=username,
        password_hash=password_hasher.hash(password),
    )

    try:
        db.add(account)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        existing_id = db.scalar(
            select(OperatorAccount.id).where(
                OperatorAccount.username == username
            )
        )
        if existing_id is not None:
            raise OperatorAlreadyExistsError("用户名已存在。") from exc
        raise

    db.refresh(account)
    return account
