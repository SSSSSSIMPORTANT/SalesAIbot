from fastapi.testclient import TestClient

from app.config import Settings
from app.database import get_db
from app.knowledge import DEFAULT_CATALOG_PATH, KnowledgeRepository
from app.llm import MockModelGateway
from app.main import create_app

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from app.database import (
    Base,
    Conversation,
    Message,
    enable_foreign_keys,
)
from app.services.memory import (
    FactSourceError,
    list_confirmed_facts,
    save_confirmed_fact,
)


@pytest.fixture
def db(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'memory.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    event.listen(engine, "connect", enable_foreign_keys)
    Base.metadata.create_all(engine)

    try:
        with Session(engine) as session:
            yield session
    finally:
        engine.dispose()


def version_of(db, conversation):
    return db.scalar(
        select(Conversation.version)
        .where(Conversation.id == conversation.id)
    )


def make_source(
    db,
    customer_name="合成测试客户",
    message_text="我想学习 Python 基础。",
):
    conversation = Conversation(customer_name=customer_name)
    db.add(conversation)
    db.flush()

    message = Message(
        conversation_id=conversation.id,
        actor="customer",
        text=message_text,
    )
    db.add(message)
    db.commit()
    db.refresh(message)

    return conversation, message


def test_save_fact_keeps_source_message(db):
    conversation, message = make_source(db)

    fact = save_confirmed_fact(
        db,
        conversation_id=conversation.id,
        based_on_version=version_of(db, conversation),
        fact_key="learning_goal",
        value="  学习 Python 基础  ",
        source_message_id=message.id,
    )

    assert fact.value == "学习 Python 基础"
    assert fact.source_message_id == message.id
    assert fact.status == "confirmed"

    current = list_confirmed_facts(
        db,
        conversation_id=conversation.id,
    )
    assert [item.id for item in current] == [fact.id]


def test_new_fact_supersedes_old_value(db):
    conversation, message = make_source(db)

    old = save_confirmed_fact(
        db,
        conversation_id=conversation.id,
        based_on_version=version_of(db, conversation),
        fact_key="learning_goal",
        value="学习 Python 基础",
        source_message_id=message.id,
    )
    correction = Message(
        conversation_id=conversation.id,
        actor="customer",
        text="我改为学习 Python 项目开发。",
    )
    db.add(correction)
    db.commit()
    db.refresh(correction)

    new = save_confirmed_fact(
        db,
        conversation_id=conversation.id,
        based_on_version=version_of(db, conversation),
        fact_key="learning_goal",
        value="改为学习 Python 项目开发",
        source_message_id=correction.id,
    )

    assert old.status == "superseded"
    assert old.superseded_at is not None

    current = list_confirmed_facts(
        db,
        conversation_id=conversation.id,
    )
    assert [item.value for item in current] == [
        "改为学习 Python 项目开发"
    ]


def test_fact_cannot_use_another_conversations_message(db):
    conversation, _ = make_source(db)
    _, other_message = make_source(db, customer_name="另一个客户")

    with pytest.raises(FactSourceError, match="invalid_fact_source"):
        save_confirmed_fact(
            db,
            conversation_id=conversation.id,
            based_on_version=version_of(db, conversation),
            fact_key="learning_goal",
            value="学习 Python",
            source_message_id=other_message.id,
        )


@pytest.mark.parametrize(
    ("fact_key", "value", "error"),
    [
        ("made_up_key", "学习 Python", "unsupported_fact_key"),
        ("learning_goal", "   ", "empty_fact_value"),
    ],
)
def test_fact_rejects_unsupported_or_empty_values(
    db,
    fact_key,
    value,
    error,
):
    conversation, message = make_source(db)

    with pytest.raises(FactSourceError, match=error):
        save_confirmed_fact(
            db,
            conversation_id=conversation.id,
            based_on_version=version_of(db, conversation),
            fact_key=fact_key,
            value=value,
            source_message_id=message.id,
        )


def test_preview_recalls_fact_outside_recent_window(db, tmp_path, as_test_operator):
    conversation, source = make_source(db)

    save_confirmed_fact(
        db,
        conversation_id=conversation.id,
        based_on_version=version_of(db, conversation),
        fact_key="learning_goal",
        value="学习 Python 基础",
        source_message_id=source.id,
    )

    # 添加足够多的新消息，让来源消息离开最近16条窗口。
    for index in range(20):
        db.add(
            Message(
                conversation_id=conversation.id,
                actor="customer",
                text=f"合成后续消息-{index}",
            )
        )
    db.commit()

    # 另一位客户也有记忆，不应进入当前会话。
    other, other_source = make_source(
        db,
        "另一位客户",
        "我想学习其他内容。",
    )
    save_confirmed_fact(
        db,
        conversation_id=other.id,
        based_on_version=version_of(db, other),
        fact_key="learning_goal",
        value="学习其他内容",
        source_message_id=other_source.id,
    )

    captured = {}

    class RecordingGateway(MockModelGateway):
        def generate(
            self,
            *,
            messages,
            product=None,
            tool_call=None,
            memories=(),
        ):
            captured["messages"] = messages
            captured["memories"] = memories

            return super().generate(
                messages=messages,
                product=product,
                tool_call=tool_call,
                memories=memories,
            )

    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_bytes(DEFAULT_CATALOG_PATH.read_bytes())

    application = create_app(
        Settings(app_env="test"),
        model_gateway=RecordingGateway(),
        knowledge_repository=KnowledgeRepository(catalog_path),
    )

    def override_get_db():
        with Session(db.get_bind()) as session:
            yield session

    application.dependency_overrides[get_db] = override_get_db

    db.rollback()

    with TestClient(application) as client:
        operator = as_test_operator(client)
        conversation.owner_operator_id = operator.id
        db.commit()
        response = client.post(
            f"/conversations/{conversation.id}/reply-preview",
            json={
                "based_on_version": conversation.version,
                "product_id": "demo_python_basic",
            },
        )

    assert response.status_code == 200

    recent = captured["messages"]
    assert len(recent) == 16
    assert source.text not in [item.content for item in recent]

    memories = captured["memories"]
    assert len(memories) == 1
    assert memories[0].value == "学习 Python 基础"
    assert memories[0].source_message_id == source.id

    recalled = response.json()["recalled_memory"]
    assert recalled[0]["value"] == "学习 Python 基础"
