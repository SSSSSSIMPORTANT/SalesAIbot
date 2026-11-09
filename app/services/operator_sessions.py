import secrets
import time
from hashlib import sha256

from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.database import OperatorAccount, OperatorSession
from app.schemas.auth import OperatorIdentity
from app.services.operator_accounts import normalize_username, password_hasher


SESSION_COOKIE = "salesaibot_session"
SESSION_TTL_SECONDS = 8 * 60 * 60
_DUMMY_HASH = password_hasher.hash(secrets.token_urlsafe(32))


class LoginRejectedError(Exception):
    """账号或密码未通过验证。"""


def _hash_token(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def _cookie_digest(token: str | None) -> str | None:
    if token is None or len(token) != 43:
        return None
    return _hash_token(token)


def login_operator(
    db: Session,
    *,
    username: str,
    password: str,
    previous_token: str | None,
) -> tuple[OperatorIdentity, str]:
    try:
        normalized = normalize_username(username)
    except ValueError:
        normalized = None

    account = db.execute(
        select(
            OperatorAccount.id,
            OperatorAccount.username,
            OperatorAccount.password_hash,
            OperatorAccount.is_active,
        ).where(OperatorAccount.username == normalized)
    ).one_or_none()
    db.rollback()

    stored_hash = account.password_hash if account is not None else _DUMMY_HASH

    try:
        matched = password_hasher.verify(stored_hash, password)
    except (VerificationError, InvalidHashError):
        matched = False

    if not matched or account is None or not account.is_active:
        raise LoginRejectedError

    token = secrets.token_urlsafe(32)
    previous_digest = _cookie_digest(previous_token)

    with db.begin():
        # 写入会话前，再确认账号仍启用且凭据未变化。
        checked = db.execute(
            update(OperatorAccount)
            .where(
                OperatorAccount.id == account.id,
                OperatorAccount.is_active.is_(True),
                OperatorAccount.password_hash == account.password_hash,
            )
            .values(is_active=True)
            .execution_options(synchronize_session=False)
        )

        if checked.rowcount != 1:
            raise LoginRejectedError

        if previous_digest is not None:
            db.execute(
                delete(OperatorSession).where(
                    OperatorSession.token_digest == previous_digest
                )
            )

        db.add(
            OperatorSession(
                token_digest=_hash_token(token),
                operator_id=account.id,
                expires_at=int(time.time()) + SESSION_TTL_SECONDS,
            )
        )

    return OperatorIdentity(id=account.id, username=account.username), token


def find_session_operator(
    db: Session,
    token: str | None,
) -> OperatorAccount | None:
    digest = _cookie_digest(token)
    if digest is None:
        return None

    return db.scalar(
        select(OperatorAccount)
        .join(OperatorSession, OperatorSession.operator_id == OperatorAccount.id)
        .where(
            OperatorSession.token_digest == digest,
            OperatorSession.expires_at > int(time.time()),
            OperatorAccount.is_active.is_(True),
        )
    )


def revoke_session(db: Session, token: str | None) -> None:
    digest = _cookie_digest(token)
    if digest is None:
        return

    with db.begin():
        db.execute(
            delete(OperatorSession).where(OperatorSession.token_digest == digest)
        )
