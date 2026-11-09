"""Extract candidates without persisting or confirming model output."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import Conversation, Message
from app.llm import ModelCallError, ModelGateway
from app.schemas.memory import ExtractMemoryRequest, ExtractMemoryResponse
from app.services.errors import ServiceError


def extract_memory_candidates(
    conversation_id: str,
    body: ExtractMemoryRequest,
    db: Session,
    *,
    gateway: ModelGateway,
) -> ExtractMemoryResponse:
    conversation = db.get(Conversation, conversation_id)

    if conversation is None:
        raise ServiceError(
            status_code=404,
            detail="Conversation not found",
        )

    if conversation.version != body.based_on_version:
        raise ServiceError(
            status_code=409,
            detail="Conversation changed; refresh before extracting",
        )

    source = db.get(Message, body.source_message_id)

    # 不接受其他会话的消息作为来源。
    if source is None or source.conversation_id != conversation_id:
        raise ServiceError(
            status_code=404,
            detail="Source message not found",
        )

    if source.actor != "customer":
        raise ServiceError(
            status_code=422,
            detail="Source message must be from the customer",
        )

    # 复制原文后结束读取事务，再等待模型。
    source_text = source.text
    db.rollback()

    try:
        batch = gateway.extract_memory_candidates(
            source_text=source_text,
        )
    except ModelCallError as exc:
        raise ServiceError(
            status_code=503,
            detail=str(exc),
        ) from exc

    # 提取期间可能出现新消息或记忆更正。
    current_version = db.scalar(
        select(Conversation.version).where(Conversation.id == conversation_id)
    )

    if current_version != body.based_on_version:
        raise ServiceError(
            status_code=409,
            detail="Conversation changed while extracting",
        )

    return ExtractMemoryResponse(
        conversation_id=conversation_id,
        based_on_version=body.based_on_version,
        source_message_id=body.source_message_id,
        source_text=source_text,
        candidates=batch.candidates,
    )
