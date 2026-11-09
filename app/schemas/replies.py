from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.knowledge import ProductKnowledge
from app.llm import ConfirmedFactSnapshot, ModelReply
from app.services.memory_recall import MemoryConflict
from app.services.reply_rendering import HandoffReason, RISK_TOPICS, ReplyResultTopic
from app.services.turn_engine import TurnTraceStep


class ReplyPreviewRequest(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    based_on_version: int = Field(ge=0, strict=True)
    product_id: str | None = Field(default=None, min_length=1, max_length=100)


class ReplyRouting(BaseModel):
    intents: list[ReplyResultTopic]
    risk_flags: list[HandoffReason]
    action: Literal["suggest_reply", "clarify_product", "human_handoff"]
    handoff_reason: HandoffReason | None = None


class ReplyPreviewResponse(BaseModel):
    conversation_id: str
    based_on_version: int
    reply: ModelReply
    retrieved_knowledge: ProductKnowledge | None
    trace: list[TurnTraceStep]
    recalled_memory: list[ConfirmedFactSnapshot]
    memory_conflicts: list[MemoryConflict]
    source_message_id: int | None = None

    @computed_field
    @property
    def routing(self) -> ReplyRouting:
        intents = list(dict.fromkeys(self.reply.topics))
        risks = [topic for topic in RISK_TOPICS if topic in intents]
        if risks:
            return ReplyRouting(
                intents=intents,
                risk_flags=risks,
                action="human_handoff",
                handoff_reason=risks[0],
            )
        return ReplyRouting(
            intents=intents,
            risk_flags=[],
            action="clarify_product" if "product_clarification" in intents else "suggest_reply",
        )
