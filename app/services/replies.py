"""Prepare a reply with bounded history, memory snapshots and freshness checks."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import Conversation, Message
from app.llm import ConfirmedFactSnapshot, ModelCallError
from app.schemas.replies import ReplyPreviewRequest, ReplyPreviewResponse, ReplyRouting
from app.services.context import MAX_RECENT_MESSAGES, build_recent_context
from app.services.errors import ServiceError
from app.services.memory_recall import recall_memory
from app.services.turn_engine import (
    ProductKnowledgeNotFoundError,
    SalesTurnEngine,
    TurnValidationError,
)
from app.tools import SalesToolExecutor, ToolExecutionError


def build_reply_preview(
    conversation_id: str,
    body: ReplyPreviewRequest,
    db: Session,
    *,
    turn_engine: SalesTurnEngine,
    tool_executor: SalesToolExecutor,
) -> ReplyPreviewResponse:
    conversation = db.get(Conversation, conversation_id)

    if conversation is None:
        raise ServiceError(
            status_code=404,
            detail="Conversation not found",
        )

    if conversation.version != body.based_on_version:
        raise ServiceError(
            status_code=409,
            detail="Conversation changed; refresh before generating",
        )

    if conversation.suggestions_paused:
        raise ServiceError(status_code=409, detail={"code": "suggestions_paused"})

    statement = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.id.desc())
        .limit(MAX_RECENT_MESSAGES)
    )

    # 数据库取最新消息，转回时间正序供模型阅读。
    history = list(reversed(db.scalars(statement).all()))

    if not history or history[-1].actor != "customer":
        raise ServiceError(
            status_code=409,
            detail="The latest message must be from the customer",
        )

    model_messages = build_recent_context(history)
    source_message_id = history[-1].id
    recall_before = recall_memory(
        db,
        conversation_id=conversation_id,
    )

    memories = tuple(
        ConfirmedFactSnapshot.model_validate(fact)
        for fact in recall_before.recalled_memory
    )

    # 输入已经复制为独立对象，先结束读取事务。
    db.rollback()

    try:
        result = turn_engine.preview(
            messages=model_messages,
            product_id=body.product_id,
            tools=tool_executor,
            memories=memories,
        )
    except ProductKnowledgeNotFoundError as exc:
        raise ServiceError(
            status_code=404,
            detail=str(exc),
        ) from exc
    except (
        ModelCallError,
        ToolExecutionError,
        TurnValidationError,
    ) as exc:
        db.rollback()
        current_version = db.scalar(
            select(Conversation.version).where(Conversation.id == conversation_id)
        )
        if current_version != body.based_on_version:
            raise ServiceError(
                status_code=409, detail="Conversation changed while generating"
            ) from exc
        routing = ReplyRouting(
            intents=[],
            risk_flags=["model_unavailable"],
            action="human_handoff",
            handoff_reason="model_unavailable",
        )
        raise ServiceError(
            status_code=503,
            detail={
                "code": str(exc),
                "message": (
                    "模型响应超时，可重试或创建人工任务。"
                    if str(exc) == "model_timeout"
                    else "本轮暂时无法生成可靠建议，可重试或创建人工任务。"
                ),
                "source_message_id": source_message_id,
                "routing": routing.model_dump(),
            },
        ) from exc

    # 结束可能存在的读取事务，从新的读取开始检查。
    db.rollback()

    # 模型运行期间可能出现新消息，再读一次最新版本。
    current_version = db.scalar(
        select(Conversation.version).where(Conversation.id == conversation_id)
    )

    if current_version != body.based_on_version:
        raise ServiceError(
            status_code=409,
            detail="Conversation changed while generating",
        )

    recall_after = recall_memory(
        db,
        conversation_id=conversation_id,
    )

    if recall_after != recall_before:
        raise ServiceError(
            status_code=409,
            detail="Customer memory changed while generating",
        )

    return ReplyPreviewResponse(
        conversation_id=conversation_id,
        based_on_version=body.based_on_version,
        reply=result.reply,
        retrieved_knowledge=result.retrieved_knowledge,
        trace=result.trace,
        recalled_memory=list(memories),
        memory_conflicts=recall_before.conflicts,
        source_message_id=source_message_id,
    )
