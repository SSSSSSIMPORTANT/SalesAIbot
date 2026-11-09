from collections import defaultdict

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import Conversation, ConversationFact
from app.memory_candidates import FactKey


class RecallConversationNotFoundError(Exception):
    pass


class RecalledFact(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        frozen=True,
    )

    id: int
    conversation_id: str
    fact_key: FactKey
    value: str
    source_message_id: int


class MemoryConflict(BaseModel):
    fact_key: FactKey
    alternatives: list[RecalledFact]


class MemoryRecallResponse(BaseModel):
    conversation_id: str
    customer_id: str | None
    recalled_memory: list[RecalledFact]
    conflicts: list[MemoryConflict]


def recall_memory(
    db: Session,
    *,
    conversation_id: str,
) -> MemoryRecallResponse:
    conversation = db.get(Conversation, conversation_id)

    if conversation is None:
        raise RecallConversationNotFoundError(
            "Conversation not found"
        )

    statement = (
        select(ConversationFact)
        .join(
            Conversation,
            Conversation.id == ConversationFact.conversation_id,
        )
        .where(ConversationFact.status == "confirmed")
        .order_by(ConversationFact.id.asc())
    )

    if conversation.customer_id is None:
        statement = statement.where(
            ConversationFact.conversation_id == conversation_id
        )
    else:
        statement = statement.where(
            Conversation.customer_id == conversation.customer_id,
            Conversation.owner_operator_id == conversation.owner_operator_id,
        )

    grouped: dict[str, list[RecalledFact]] = defaultdict(list)

    for fact in db.scalars(statement):
        snapshot = RecalledFact.model_validate(fact)
        grouped[snapshot.fact_key].append(snapshot)

    recalled = []
    conflicts = []

    for fact_key, facts in grouped.items():
        values = {fact.value for fact in facts}

        if len(values) == 1:
            # 保留所有来源，避免去重时丢掉证据。
            recalled.extend(facts)
        else:
            conflicts.append(
                MemoryConflict(
                    fact_key=fact_key,
                    alternatives=facts,
                )
            )

    return MemoryRecallResponse(
        conversation_id=conversation_id,
        customer_id=conversation.customer_id,
        recalled_memory=recalled,
        conflicts=conflicts,
    )
