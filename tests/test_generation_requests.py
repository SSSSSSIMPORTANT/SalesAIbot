from datetime import datetime, timezone

import pytest

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import (
    Base,
    Conversation,
    ReplySuggestion,
    SuggestionGenerationRequest,
    enable_foreign_keys,
)
from app.schemas.suggestions import CreateSuggestionRequest
from app.services.errors import ServiceError
from app.services.generation_requests import claim_generation


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "generation.db"
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    event.listen(engine, "connect", enable_foreign_keys)
    Base.metadata.create_all(engine)

    try:
        with Session(engine) as session:
            yield session
    finally:
        engine.dispose()


def make_conversation(db):
    conversation = Conversation(
        customer_name="合成幂等测试客户",
    )
    db.add(conversation)
    db.flush()
    return conversation.id


def test_request_key_is_unique_within_conversation(db):
    first_id = make_conversation(db)
    second_id = make_conversation(db)

    for conversation_id in (first_id, second_id):
        db.add(
            SuggestionGenerationRequest(
                conversation_id=conversation_id,
                request_key="generate-001",
                based_on_version=0,
                product_id="demo_python_basic",
            )
        )
    db.commit()

    # 不同会话允许使用相同 key。
    count = db.scalar(
        select(func.count()).select_from(
            SuggestionGenerationRequest
        )
    )
    assert count == 2

    # 同一会话不能再创建相同 key。
    db.add(
        SuggestionGenerationRequest(
            conversation_id=first_id,
            request_key="generate-001",
            based_on_version=0,
            product_id="demo_python_basic",
        )
    )

    with pytest.raises(IntegrityError):
        db.commit()

    db.rollback()

    count = db.scalar(
        select(func.count()).select_from(
            SuggestionGenerationRequest
        )
    )
    assert count == 2


@pytest.mark.parametrize(
    "overrides",
    [
        {"based_on_version": -1},
        {"status": "unknown"},
        {"status": "succeeded"},
        {"status": "failed"},
        {"status": "running", "error_code": "model_timeout"},
    ],
)
def test_generation_request_rejects_invalid_state(db, overrides):
    conversation_id = make_conversation(db)
    db.commit()

    values = {
        "conversation_id": conversation_id,
        "request_key": "invalid-state",
        "based_on_version": 0,
        "product_id": "demo_python_basic",
        "status": "running",
    }
    values.update(overrides)

    db.add(SuggestionGenerationRequest(**values))

    with pytest.raises(IntegrityError):
        db.commit()

    db.rollback()

    count = db.scalar(
        select(func.count()).select_from(
            SuggestionGenerationRequest
        )
    )
    assert count == 0


def generation_body(**changes):
    values = {
        "request_key": "generate-001",
        "based_on_version": 0,
        "product_id": "demo_python_basic",
    }
    values.update(changes)
    return CreateSuggestionRequest(**values)


def test_claim_is_committed_before_generation(db):
    conversation_id = make_conversation(db)
    db.commit()

    result = claim_generation(conversation_id, generation_body(), db)

    assert result.created is True
    assert result.suggestion_id is None
    assert not db.in_transaction()

    # 另一个 Session 也能读到，说明并非只停留在内存或未提交事务中。
    with Session(db.get_bind()) as observer:
        row = observer.get(
            SuggestionGenerationRequest, (conversation_id, "generate-001")
        )
        assert row is not None
        assert row.status == "running"
        assert observer.get(Conversation, conversation_id).version == 0
        assert observer.scalar(
            select(func.count()).select_from(ReplySuggestion)
        ) == 0


@pytest.mark.parametrize(
    ("case", "code"),
    [
        ("running", "generation_in_progress"),
        ("failed", "generation_failed"),
        ("changed_version", "generation_request_mismatch"),
        ("changed_product", "generation_request_mismatch"),
    ],
)
def test_claim_rejects_repeated_or_changed_request(db, case, code):
    conversation_id = make_conversation(db)
    db.commit()
    claim_generation(conversation_id, generation_body(), db)

    if case == "failed":
        row = db.get(
            SuggestionGenerationRequest, (conversation_id, "generate-001")
        )
        row.status = "failed"
        row.error_code = "model_timeout"
        row.finished_at = datetime.now(timezone.utc).isoformat()
        db.commit()

    changes = {}
    if case == "changed_version":
        changes["based_on_version"] = 1
    if case == "changed_product":
        changes["product_id"] = "another-product"

    with pytest.raises(ServiceError) as caught:
        claim_generation(conversation_id, generation_body(**changes), db)

    assert caught.value.status_code == 409
    assert caught.value.detail == {"code": code}
    assert not db.in_transaction()
    assert db.scalar(
        select(func.count()).select_from(SuggestionGenerationRequest)
    ) == 1
    db.expire_all()
    row = db.get(
        SuggestionGenerationRequest, (conversation_id, "generate-001")
    )
    assert row.status == ("failed" if case == "failed" else "running")


@pytest.mark.parametrize("foreign_result", [False, True])
def test_completed_claim_replays_only_its_original_result(db, foreign_result):
    conversation_id = make_conversation(db)
    other_id = make_conversation(db) if foreign_result else conversation_id
    suggestion = ReplySuggestion(
        conversation_id=other_id,
        based_on_version=0,
        product_id="demo_python_basic",
        reply_text="合成测试回复",
        generation_snapshot={},
    )
    db.add(suggestion)
    db.flush()
    suggestion_id = suggestion.id
    db.add(
        SuggestionGenerationRequest(
            conversation_id=conversation_id,
            request_key="generate-001",
            based_on_version=0,
            product_id="demo_python_basic",
            status="succeeded",
            suggestion_id=suggestion_id,
            finished_at=datetime.now(timezone.utc).isoformat(),
        )
    )
    db.get(Conversation, conversation_id).version = 1
    db.commit()

    if foreign_result:
        with pytest.raises(ServiceError) as caught:
            claim_generation(conversation_id, generation_body(), db)
        assert caught.value.status_code == 503
        assert caught.value.detail == {"code": "generation_result_unavailable"}
    else:
        result = claim_generation(conversation_id, generation_body(), db)
        assert result.created is False
        assert result.suggestion_id == suggestion_id
    assert not db.in_transaction()


@pytest.mark.parametrize("missing", [False, True])
def test_invalid_new_claim_leaves_no_request(db, missing):
    conversation_id = "missing" if missing else make_conversation(db)
    db.commit()

    with pytest.raises(ServiceError) as caught:
        claim_generation(
            conversation_id, generation_body(based_on_version=1), db
        )

    assert caught.value.status_code == (404 if missing else 409)
    assert not db.in_transaction()
    assert db.scalar(
        select(func.count()).select_from(SuggestionGenerationRequest)
    ) == 0
