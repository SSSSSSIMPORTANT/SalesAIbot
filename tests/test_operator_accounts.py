import pytest
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.database import Base, OperatorAccount
from app.services.operator_accounts import (
    OperatorAlreadyExistsError,
    create_operator_account,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            yield session
    finally:
        engine.dispose()


def test_saved_password_hash_can_be_verified(db):
    password = "synthetic local test passphrase"
    account = create_operator_account(
        db,
        username=" Local-Sales ",
        password=password,
    )

    assert account.username == "local-sales"
    assert account.is_active is True
    assert account.password_hash.startswith("$argon2id$")
    assert PasswordHasher().verify(account.password_hash, password)

    with pytest.raises(VerifyMismatchError):
        PasswordHasher().verify(account.password_hash, "wrong test passphrase")


def test_username_is_unique_after_normalization(db):
    password = "synthetic local test passphrase"
    create_operator_account(db, username="Local-Sales", password=password)

    with pytest.raises(OperatorAlreadyExistsError):
        create_operator_account(db, username="local-sales", password=password)

    count = db.scalar(select(func.count()).select_from(OperatorAccount))
    assert count == 1


def test_short_password_does_not_create_account(db):
    with pytest.raises(ValueError, match="15"):
        create_operator_account(db, username="local-sales", password="short")

    assert db.scalar(select(OperatorAccount.id)) is None