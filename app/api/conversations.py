from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import require_operator
from app.database import Conversation, Customer, get_db
from app.schemas.auth import OperatorIdentity
from app.schemas.conversations import ConversationResponse, CreateConversationRequest, SetAssistanceRequest
from app.services.assistance import set_assistance


router = APIRouter()


@router.post(
    "/conversations",
    response_model=ConversationResponse,
    status_code=201,
    tags=["conversations"],
)
def create_conversation(
    body: CreateConversationRequest,
    db: Session = Depends(get_db),
    operator: OperatorIdentity = Depends(require_operator),
):
    if body.customer_id is not None:
        customer = db.scalar(
            select(Customer).where(
                Customer.id == body.customer_id,
                Customer.owner_operator_id == operator.id,
            )
        )

        if customer is None:
            raise HTTPException(
                status_code=404,
                detail="Customer not found",
            )

        customer_name = customer.display_name
    else:
        customer_name = body.customer_name

    conversation = Conversation(
        customer_name=customer_name,
        customer_id=body.customer_id,
        owner_operator_id=operator.id,
    )

    db.add(conversation)
    db.commit()
    db.refresh(conversation)

    return conversation


@router.get(
    "/conversations",
    response_model=list[ConversationResponse],
    tags=["conversations"],
    summary="List my conversations",
)
def list_conversations(
    db: Session = Depends(get_db),
    operator: OperatorIdentity = Depends(require_operator),
):
    statement = (
        select(Conversation)
        .where(Conversation.owner_operator_id == operator.id)
        .order_by(Conversation.created_at.desc(), Conversation.id.desc())
    )

    conversations = db.scalars(statement).all()

    return conversations


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationResponse,
    tags=["conversations"],
)
def get_conversation(
    conversation_id: str,
    db: Session = Depends(get_db),
):
    conversation = db.get(Conversation, conversation_id)

    if conversation is None:
        raise HTTPException(
            status_code=404,
            detail="Conversation not found",
        )

    return conversation


@router.put(
    "/conversations/{conversation_id}/assistance",
    response_model=ConversationResponse,
    tags=["conversations"],
)
def update_assistance(
    conversation_id: str,
    body: SetAssistanceRequest,
    db: Session = Depends(get_db),
    operator: OperatorIdentity = Depends(require_operator),
):
    return set_assistance(
        db,
        conversation_id=conversation_id,
        operator_id=operator.id,
        body=body,
    )
