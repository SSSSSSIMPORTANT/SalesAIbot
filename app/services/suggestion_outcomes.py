from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.database import Message, SuggestionCopyEvent, Conversation, SuggestionAbandonment
from app.schemas.suggestions import (
    ReportedSuggestionMessage,
    SuggestionOutcomeResponse,
    AbandonSuggestionRequest,
    SuggestionAbandonmentResponse,
)
from app.services.suggestions import get_suggestion
from app.services.errors import ServiceError


def read_suggestion_outcome(
        conversation_id: str,
        suggestion_id: str,
        db: Session,
) -> SuggestionOutcomeResponse:
    get_suggestion(conversation_id, suggestion_id, db)

    copy_count = db.scalar(
        select(func.count())
        .select_from(SuggestionCopyEvent)
        .where(SuggestionCopyEvent.suggestion_id == suggestion_id)
    ) or 0

    rows = db.execute(
        select(Message.id, Message.adoption_mode, Message.created_at)
        .where(
            Message.conversation_id == conversation_id,
            Message.source_suggestion_id == suggestion_id,
        )
        .order_by(Message.id)
    ).all()
    reported_messages = [
        ReportedSuggestionMessage(
            message_id=message_id,
            adoption_mode=adoption_mode,
            recorded_at=created_at,
        )
        for message_id, adoption_mode, created_at in rows
    ]

    abandonment = db.get(SuggestionAbandonment, suggestion_id)

    if reported_messages:
        status = "reported_sent"
    elif abandonment is not None:
        status = "abandoned"
    elif copy_count:
        status = "copied"
    else:
        status = "unknown"

    return SuggestionOutcomeResponse(
        suggestion_id=suggestion_id,
        status=status,
        copy_count=copy_count,
        reported_messages=reported_messages,
        abandonment=(
            SuggestionAbandonmentResponse.model_validate(abandonment)
            if abandonment is not None
            else None
        ),
    )


def abandon_suggestion(
        db: Session,
        *,
        conversation_id: str,
        suggestion_id: str,
        operator_id: str,
        body: AbandonSuggestionRequest,
) -> SuggestionAbandonmentResponse:
    with db.begin():
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

        get_suggestion(conversation_id, suggestion_id, db)

        existing = db.get(SuggestionAbandonment, suggestion_id)
        if existing is not None:
            if existing.reason != body.reason:
                raise ServiceError(
                    status_code=409,
                    detail={"code": "abandonment_already_recorded"},
                )
            return SuggestionAbandonmentResponse.model_validate(existing)

        sent_message_id = db.scalar(
            select(Message.id)
            .where(
                Message.conversation_id == conversation_id,
                Message.source_suggestion_id == suggestion_id,
            )
            .limit(1)
        )
        if sent_message_id is not None:
            raise ServiceError(
                status_code=409,
                detail={"code": "suggestion_already_reported_sent"},
            )

        record = SuggestionAbandonment(
            suggestion_id=suggestion_id,
            operator_id=operator_id,
            reason=body.reason,
        )
        db.add(record)
        db.flush()
        return SuggestionAbandonmentResponse.model_validate(record)
