from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.database import Conversation, HumanHandoff, Message
from app.schemas.handoffs import HandoffResponse
from app.services.errors import ServiceError
from app.services.reply_rendering import HandoffReason


def list_handoffs(db: Session, conversation_id: str) -> list[HumanHandoff]:
    return list(db.scalars(
        select(HumanHandoff)
        .join(Message, Message.id == HumanHandoff.source_message_id)
        .where(Message.conversation_id == conversation_id)
        .order_by(
            HumanHandoff.resolved_at.is_not(None),
            HumanHandoff.created_at.desc(),
            HumanHandoff.source_message_id.desc(),
        )
    ))


def _lock_customer_message(
    db: Session, conversation_id: str, message_id: int, operator_id: str
) -> None:
    # 与会话中的其他写入串行，任务本身不推进对话版本。
    locked = db.execute(
        update(Conversation)
        .where(
            Conversation.id == conversation_id,
            Conversation.owner_operator_id == operator_id,
        )
        .values(version=Conversation.version)
        .execution_options(synchronize_session=False)
    )
    if locked.rowcount != 1:
        raise ServiceError(status_code=404, detail="Conversation not found")

    message = db.get(Message, message_id)
    if message is None or message.conversation_id != conversation_id:
        raise ServiceError(status_code=404, detail="Message not found")
    if message.actor != "customer":
        raise ServiceError(status_code=409, detail={"code": "handoff_requires_customer_message"})


def create_handoff(
    db: Session, *, conversation_id: str, message_id: int, operator_id: str,
    reason: HandoffReason,
) -> tuple[HandoffResponse, bool]:
    with db.begin():
        _lock_customer_message(db, conversation_id, message_id, operator_id)
        task = db.get(HumanHandoff, message_id)
        if task is not None:
            if task.reason != reason:
                raise ServiceError(status_code=409, detail={"code": "handoff_already_exists"})
            return HandoffResponse.model_validate(task), False

        task = HumanHandoff(
            source_message_id=message_id, reason=reason, created_by_operator_id=operator_id
        )
        db.add(task)
        db.flush()
        return HandoffResponse.model_validate(task), True


def resolve_handoff(
    db: Session, *, conversation_id: str, message_id: int, operator_id: str,
    resolution: str,
) -> HandoffResponse:
    with db.begin():
        _lock_customer_message(db, conversation_id, message_id, operator_id)
        task = db.get(HumanHandoff, message_id)
        if task is None:
            raise ServiceError(status_code=404, detail="Handoff not found")
        if task.resolved_at is not None:
            if task.resolution != resolution:
                raise ServiceError(status_code=409, detail={"code": "handoff_already_resolved"})
            return HandoffResponse.model_validate(task)

        task.resolved_by_operator_id = operator_id
        task.resolved_at = datetime.now(timezone.utc).isoformat()
        task.resolution = resolution
        db.flush()
        return HandoffResponse.model_validate(task)
