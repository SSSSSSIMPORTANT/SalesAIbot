import pytest
import json

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import (
    Base,
    Conversation,
    Message,
    ReplySuggestion,
    enable_foreign_keys,
    Customer,
)
from app.knowledge import DEFAULT_CATALOG_PATH, KnowledgeRepository
from app.services.memory import save_confirmed_fact
from app.services.suggestion_validity import (
    SuggestionCheckUnavailableError,
    check_suggestion,
)


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "suggestions.db"
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    event.listen(engine, "connect", enable_foreign_keys)
    Base.metadata.create_all(engine)

    try:
        with Session(engine) as session:
            yield session
    finally:
        engine.dispose()


def test_suggestion_preserves_snapshot_without_adding_message(db):
    conversation = Conversation(customer_name="合成测试客户")
    db.add(conversation)
    db.commit()

    conversation_id = conversation.id

    snapshot = {
        "reply": {
            "text": "课程价格是199.00元。",
            "model_name": "mock-v1",
            "mode": "mock",
        },
        "retrieved_knowledge": {
            "knowledge_id": "synthetic-terms",
            "revision": "v1",
            "price_cents": 19900,
        },
        "recalled_memory": [],
        "memory_conflicts": [],
        "trace": [],
    }

    suggestion = ReplySuggestion(
        conversation_id=conversation_id,
        based_on_version=0,
        product_id="synthetic-product",
        reply_text="课程价格是199.00元。",
        generation_snapshot=snapshot,
    )
    db.add(suggestion)
    db.commit()

    suggestion_id = suggestion.id
    db.expire_all()

    stored = db.get(ReplySuggestion, suggestion_id)

    assert stored is not None
    assert stored.generation_snapshot == snapshot
    assert stored.reply_text == snapshot["reply"]["text"]

    message_count = db.scalar(
        select(func.count()).select_from(Message)
    )
    assert message_count == 0

    conversation = db.get(Conversation, conversation_id)
    assert conversation.version == 0


@pytest.mark.parametrize("case", ["missing_conversation", "negative_version"])
def test_suggestion_rejects_invalid_reference_or_version(db, case):
    conversation = Conversation(customer_name="合成测试客户")
    db.add(conversation)
    db.commit()

    suggestion = ReplySuggestion(
        conversation_id=(
            "unknown-conversation"
            if case == "missing_conversation"
            else conversation.id
        ),
        based_on_version=-1 if case == "negative_version" else 0,
        product_id="synthetic-product",
        reply_text="合成回复。",
        generation_snapshot={},
    )
    db.add(suggestion)

    with pytest.raises(IntegrityError):
        db.commit()

    db.rollback()

    count = db.scalar(
        select(func.count()).select_from(ReplySuggestion)
    )
    assert count == 0


@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("current", None),
        ("conversation_changed", "conversation_changed"),
        ("memory_changed", "memory_changed"),
        ("knowledge_changed", "knowledge_changed"),
        ("knowledge_removed", "knowledge_unavailable"),
        ("invalid_snapshot", "invalid_snapshot"),
        ("invalid_catalog", None),
    ],
)
def test_suggestion_validity(db, tmp_path, case, reason):
    path = tmp_path / "catalog.json"
    path.write_bytes(DEFAULT_CATALOG_PATH.read_bytes())
    repository = KnowledgeRepository(path)

    customer = Customer(display_name="合成客户")
    db.add(customer)
    db.flush()

    source = Conversation(
        customer_name="合成客户",
        customer_id=customer.id,
    )
    target = Conversation(
        customer_name="合成客户",
        customer_id=customer.id,
    )
    db.add_all([source, target])
    db.flush()

    message = Message(
        conversation_id=source.id,
        actor="customer",
        text="我没有编程基础",
    )
    db.add(message)
    db.commit()

    product = repository.get_published_product(
        "demo_python_basic"
    )
    assert product is not None

    snapshot = {
        "conversation_id": target.id,
        "based_on_version": 0,
        "retrieved_knowledge": product.model_dump(mode="json"),
        "recalled_memory": [],
        "memory_conflicts": [],
    }

    suggestion = ReplySuggestion(
        conversation_id=target.id,
        based_on_version=0,
        product_id=product.product_id,
        reply_text="合成测试草稿。",
        generation_snapshot=snapshot,
    )
    db.add(suggestion)
    db.commit()

    if case == "conversation_changed":
        target.version += 1
        db.commit()

    elif case == "memory_changed":
        # 另一会话保存事实，目标会话版本保持不变。
        save_confirmed_fact(
            db,
            conversation_id=source.id,
            based_on_version=0,
            fact_key="current_level",
            value="我没有编程基础",
            source_message_id=message.id,
        )
        db.refresh(target)
        assert target.version == 0

    elif case in {"knowledge_changed", "knowledge_removed"}:
        catalog = json.loads(path.read_text(encoding="utf-8"))

        for item in catalog["products"]:
            if item["product_id"] == product.product_id:
                if case == "knowledge_changed":
                    # 故意不更新 revision。
                    item["price_cents"] += 100
                else:
                    item["status"] = "draft"

        path.write_text(
            json.dumps(catalog, ensure_ascii=False),
            encoding="utf-8",
        )

    elif case == "invalid_snapshot":
        suggestion.generation_snapshot = {}
        db.commit()

    elif case == "invalid_catalog":
        path.write_text("{broken", encoding="utf-8")

    if case == "invalid_catalog":
        with pytest.raises(
            SuggestionCheckUnavailableError,
            match="knowledge_check_unavailable",
        ):
            check_suggestion(
                db,
                suggestion=suggestion,
                repository=repository,
            )
        return

    result = check_suggestion(
        db,
        suggestion=suggestion,
        repository=repository,
    )

    assert result.status == (
        "current" if reason is None else "stale"
    )
    assert result.reasons == (
        [] if reason is None else [reason]
    )