from pydantic import BaseModel, ConfigDict, Field

from app.knowledge import ProductKnowledge
from app.llm import ConfirmedFactSnapshot, ModelReply
from app.services.memory_recall import MemoryConflict
from app.services.turn_engine import TurnTraceStep


class ReplyPreviewRequest(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    based_on_version: int = Field(ge=0, strict=True)
    product_id: str = Field(min_length=1, max_length=100)


class ReplyPreviewResponse(BaseModel):
    conversation_id: str
    based_on_version: int
    reply: ModelReply
    retrieved_knowledge: ProductKnowledge
    trace: list[TurnTraceStep]
    recalled_memory: list[ConfirmedFactSnapshot]
    memory_conflicts: list[MemoryConflict]
