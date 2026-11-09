from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.database import Conversation, ConversationFact, Message
from app.memory_candidates import FactKey

ALLOWED_FACT_KEYS = {
    "learning_goal",
    "current_level",
    "preferred_format",
    "concern",
}


class FactNotFoundError(Exception):
    """指定会话中不存在这条事实。"""


class FactSourceError(Exception):
    """事实内容或来源消息不符合要求。"""


class FactConflictError(Exception):
    """保存记忆时，会话已经变化。"""


def save_confirmed_fact(
        db: Session,
        *,
        conversation_id: str,
        fact_key: str,
        value: str,
        source_message_id: int,
        based_on_version: int,
) -> ConversationFact:
    normalized_value = value.strip()

    if fact_key not in ALLOWED_FACT_KEYS:
        raise FactSourceError("unsupported_fact_key")

    if not normalized_value:
        raise FactSourceError("empty_fact_value")

    conversation = db.get(Conversation, conversation_id)

    if conversation is None:
        raise FactSourceError("conversation_not_found")

    source = db.get(Message, source_message_id)

    if (
            source is None
            or source.conversation_id != conversation_id
            or source.actor != "customer"
    ):
        raise FactSourceError("invalid_fact_source")

    if normalized_value not in source.text:
        raise FactSourceError("fact_value_not_in_source")

    # 记忆变化会影响模型输入，也要推进上下文版本。
    result = db.execute(
        update(Conversation)
        .where(
            Conversation.id == conversation_id,
            Conversation.version == based_on_version,
        )
        .values(version=Conversation.version + 1)
        .execution_options(synchronize_session=False)
    )

    if result.rowcount != 1:
        db.rollback()
        raise FactConflictError(
            "Conversation changed; refresh before saving memory"
        )

    now = datetime.now(timezone.utc).isoformat()

    current_facts = db.scalars(
        select(ConversationFact).where(
            ConversationFact.conversation_id == conversation_id,
            ConversationFact.fact_key == fact_key,
            ConversationFact.status == "confirmed",
        )
    ).all()

    for fact in current_facts:
        fact.status = "superseded"
        fact.superseded_at = now

    fact = ConversationFact(
        conversation_id=conversation_id,
        fact_key=fact_key,
        value=normalized_value,
        source_message_id=source_message_id,
        status="confirmed",
        created_at=now,
    )

    db.add(fact)
    db.commit()
    db.refresh(fact)

    return fact


def list_confirmed_facts(
        db: Session,
        *,
        conversation_id: str,
) -> list[ConversationFact]:
    return list(
        db.scalars(
            select(ConversationFact)
            .where(
                ConversationFact.conversation_id == conversation_id,
                ConversationFact.status == "confirmed",
            )
            .order_by(ConversationFact.id.asc())
        ).all()
    )


def revoke_confirmed_fact(
        db: Session,
        *,
        conversation_id: str,
        fact_id: int,
        based_on_version: int,
) -> ConversationFact:
    fact = db.get(ConversationFact, fact_id)

    if fact is None or fact.conversation_id != conversation_id:
        raise FactNotFoundError("Fact not found")

    # 取得本会话的写入权，同时检查版本。
    result = db.execute(
        update(Conversation)
        .where(
            Conversation.id == conversation_id,
            Conversation.version == based_on_version,
        )
        .values(version=Conversation.version + 1)
        .execution_options(synchronize_session=False)
    )

    if result.rowcount != 1:
        db.rollback()
        raise FactConflictError(
            "Conversation changed; refresh before revoking memory"
        )

    db.refresh(fact)

    if fact.status != "confirmed":
        db.rollback()
        raise FactConflictError("Fact is no longer confirmed")

    fact.status = "revoked"
    fact.revoked_at = datetime.now(timezone.utc).isoformat()

    db.commit()
    db.refresh(fact)

    return fact
