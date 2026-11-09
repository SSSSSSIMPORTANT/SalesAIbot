from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api.auth import require_operator
from app.database import get_db
from app.schemas.auth import OperatorIdentity
from app.schemas.handoffs import CreateHandoffRequest, HandoffResponse, ResolveHandoffRequest
from app.services import handoffs


router = APIRouter(tags=["handoffs"])


@router.get("/conversations/{conversation_id}/handoffs", response_model=list[HandoffResponse])
def get_handoffs(conversation_id: str, db: Session = Depends(get_db)):
    return handoffs.list_handoffs(db, conversation_id)


@router.put(
    "/conversations/{conversation_id}/messages/{message_id}/handoff",
    response_model=HandoffResponse,
    responses={201: {"description": "Handoff created"}},
)
def put_handoff(
    conversation_id: str, message_id: int, body: CreateHandoffRequest, response: Response,
    db: Session = Depends(get_db), operator: OperatorIdentity = Depends(require_operator),
) -> HandoffResponse:
    result, created = handoffs.create_handoff(
        db, conversation_id=conversation_id, message_id=message_id,
        operator_id=operator.id, reason=body.reason,
    )
    response.status_code = 201 if created else 200
    return result


@router.put(
    "/conversations/{conversation_id}/messages/{message_id}/handoff/resolution",
    response_model=HandoffResponse,
)
def put_handoff_resolution(
    conversation_id: str, message_id: int, body: ResolveHandoffRequest,
    db: Session = Depends(get_db), operator: OperatorIdentity = Depends(require_operator),
) -> HandoffResponse:
    return handoffs.resolve_handoff(
        db, conversation_id=conversation_id, message_id=message_id,
        operator_id=operator.id, resolution=body.resolution,
    )
