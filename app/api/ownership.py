"""Authorize customer and conversation path parameters for business routes."""

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import require_operator
from app.database import Conversation, Customer, get_db
from app.schemas.auth import OperatorIdentity


def require_owned_path(
    request: Request,
    operator: OperatorIdentity = Depends(require_operator),
    db: Session = Depends(get_db),
) -> None:
    for param, model, label in (
        ("conversation_id", Conversation, "Conversation"),
        ("customer_id", Customer, "Customer"),
    ):
        resource_id = request.path_params.get(param)
        if resource_id is None:
            continue

        owned_id = db.scalar(
            select(model.id).where(
                model.id == resource_id,
                model.owner_operator_id == operator.id,
            )
        )
        db.rollback()
        if owned_id is None:
            raise HTTPException(status_code=404, detail=f"{label} not found")
