import pytest

from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import (
    Base,
    Conversation,
    Customer,
    enable_foreign_keys,
)


@pytest.fixture
def db(tmp_path):
    database_path = tmp_path / "customers.db"
    engine = create_engine(
        f"sqlite:///{database_path.as_posix()}",
    )
    event.listen(engine, "connect", enable_foreign_keys)
    Base.metadata.create_all(engine)

    try:
        with Session(engine) as session:
            yield session
    finally:
        engine.dispose()


def test_same_name_does_not_merge_customers(db):
    first = Customer(display_name="合成客户")
    second = Customer(display_name="合成客户")

    db.add_all([first, second])
    db.commit()

    assert first.id != second.id

    conversation = Conversation(
        customer_name="合成客户",
        customer_id=first.id,
    )
    db.add(conversation)
    db.commit()
    db.refresh(conversation)

    assert conversation.customer_id == first.id
    assert conversation.customer_id != second.id


def test_conversation_can_remain_unassigned(db):
    conversation = Conversation(
        customer_name="尚未确认身份的客户",
    )

    db.add(conversation)
    db.commit()
    db.refresh(conversation)

    assert conversation.customer_id is None


def test_conversation_rejects_nonexistent_customer(db):
    db.add(
        Conversation(
            customer_name="合成客户",
            customer_id="nonexistent-customer",
        )
    )

    with pytest.raises(IntegrityError):
        db.commit()

    db.rollback()