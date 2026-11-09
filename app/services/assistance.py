"""Change reply assistance state within the conversation's version boundary."""

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.database import Conversation
from app.schemas.conversations import ConversationResponse, SetAssistanceRequest
from app.services.errors import ServiceError


def set_assistance(
    db: Session,
    *,
    conversation_id: str,
    operator_id: str,
    body: SetAssistanceRequest,
) -> ConversationResponse:
    scope = (
        Conversation.id == conversation_id,
        Conversation.owner_operator_id == operator_id,
    )

    with db.begin():
        changed = db.execute(
            update(Conversation)
            .where(
                *scope,
                Conversation.version == body.based_on_version,
                Conversation.suggestions_paused != body.suggestions_paused,
            )
            .values(
                suggestions_paused=body.suggestions_paused,
                version=Conversation.version + 1,
            )
            .execution_options(synchronize_session=False)
        )

        conversation = db.scalar(
            select(Conversation).where(*scope).execution_options(populate_existing=True)
        )
        if conversation is None:
            raise ServiceError(status_code=404, detail="Conversation not found")

        if changed.rowcount == 0 and conversation.version != body.based_on_version:
            raise ServiceError(
                status_code=409,
                detail={"code": "conversation_version_conflict"},
            )

        return ConversationResponse.model_validate(conversation)
