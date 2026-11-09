from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import Conversation, Message, get_db
from app.schemas.messages import (
    CustomerMessageRequest,
    CreateMessageRequest,
    MessageResponse,
)
from app.services.messages import (
    ConversationNotFoundError,
    MessageConflictError,
    SourceSuggestionNotFoundError,
    add_message,
)


router = APIRouter()


@router.post("/messages/preview", tags=["messages"])
def preview_message(body: CustomerMessageRequest):
    return {
        "status": "received",
        "text": body.text,
        "length": len(body.text),
    }


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=MessageResponse,
    status_code=201,
    tags=["messages"],
)
def create_message(
    conversation_id: str,
    body: CreateMessageRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    try:
        result = add_message(
            db,
            conversation_id=conversation_id,
            request_key=body.request_key,
            based_on_version=body.based_on_version,
            actor=body.actor,
            text=body.text,
            source_suggestion_id=body.source_suggestion_id,
        )

    except (ConversationNotFoundError, SourceSuggestionNotFoundError) as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc

    except MessageConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc

    response.status_code = 201 if result.created else 200

    return result.message


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=list[MessageResponse],
    tags=["messages"],
)
def list_messages(
    conversation_id: str,
    db: Session = Depends(get_db),
):
    conversation = db.get(Conversation, conversation_id)

    if conversation is None:
        raise HTTPException(
            status_code=404,
            detail="Conversation not found",
        )

    statement = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.id.asc())
    )

    return db.scalars(statement).all()
