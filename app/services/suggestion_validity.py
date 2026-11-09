from typing import Literal

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.database import Conversation, ReplySuggestion, SuggestionAbandonment
from app.knowledge import KnowledgeRepository, ProductKnowledge
from app.services.memory_recall import (
    MemoryConflict,
    RecalledFact,
    recall_memory,
)
from app.services.turn_engine import RULE_TOPICS, build_rule_reply


class SuggestionCheckUnavailableError(Exception):
    """当前无法完成检查，不能据此认定草稿有效。"""


class SuggestionBasis(BaseModel):
    """从生成快照中读取本次需要比对的依据。"""

    conversation_id: str
    based_on_version: int
    retrieved_knowledge: ProductKnowledge | None
    recalled_memory: list[RecalledFact]
    memory_conflicts: list[MemoryConflict]


class SuggestionValidity(BaseModel):
    suggestion_id: str
    status: Literal["current", "stale"]
    reasons: list[str]


def check_suggestion(
        db: Session,
        *,
        suggestion: ReplySuggestion,
        repository: KnowledgeRepository,
) -> SuggestionValidity:
    if db.get(SuggestionAbandonment, suggestion.id) is not None:
        return SuggestionValidity(
            suggestion_id=suggestion.id,
            status="stale",
            reasons=["suggestion_abandoned"],
        )

    def invalid_snapshot():
        return SuggestionValidity(
            suggestion_id=suggestion.id,
            status="stale",
            reasons=["invalid_snapshot"],
        )

    try:
        basis = SuggestionBasis.model_validate(
            suggestion.generation_snapshot
        )
    except ValidationError:
        return invalid_snapshot()

    if (
            basis.conversation_id != suggestion.conversation_id
            or basis.based_on_version != suggestion.based_on_version
    ):
        return invalid_snapshot()

    knowledge = basis.retrieved_knowledge
    if knowledge is None:
        saved_reply = suggestion.generation_snapshot.get("reply")
        if not isinstance(saved_reply, dict):
            return invalid_snapshot()
        rule_name = saved_reply.get("model_name")
        rule_topic = RULE_TOPICS.get(rule_name) if isinstance(rule_name, str) else None
        if rule_topic is None:
            return invalid_snapshot()
        expected_reply = build_rule_reply(rule_topic)
        if (
                {"text_source": "template", **saved_reply}
                != expected_reply.model_dump(mode="json")
                or suggestion.reply_text != expected_reply.text
                or (rule_topic == "product_clarification" and suggestion.product_id is not None)
        ):
            return invalid_snapshot()
    elif knowledge.product_id != suggestion.product_id:
        return invalid_snapshot()

    reasons = []

    conversation = db.get(
        Conversation,
        suggestion.conversation_id,
    )

    if (
            conversation is None
            or conversation.version != suggestion.based_on_version
    ):
        reasons.append("conversation_changed")

    if conversation is not None:
        if conversation.suggestions_paused:
            reasons.append("suggestions_paused")

        current_memory = recall_memory(
            db,
            conversation_id=conversation.id,
        )

        if (
                current_memory.recalled_memory != basis.recalled_memory
                or current_memory.conflicts != basis.memory_conflicts
        ):
            reasons.append("memory_changed")

    if knowledge is not None:
        try:
            current_product = repository.get_current_published_product(
                suggestion.product_id
            )
        except (OSError, ValidationError):
            raise SuggestionCheckUnavailableError(
                "knowledge_check_unavailable"
            ) from None

        if current_product is None:
            reasons.append("knowledge_unavailable")
        elif current_product != knowledge:
            reasons.append("knowledge_changed")

    return SuggestionValidity(
        suggestion_id=suggestion.id,
        status="stale" if reasons else "current",
        reasons=reasons,
    )
