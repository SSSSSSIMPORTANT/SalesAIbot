from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import Conversation, get_db
from app.dependencies import AppRuntime, get_runtime
from app.schemas.memory import (
    ExtractMemoryRequest,
    ExtractMemoryResponse,
    FactResponse,
    RevokeFactRequest,
    SaveFactRequest,
)
from app.services.memory import (
    FactConflictError,
    FactNotFoundError,
    FactSourceError,
    list_confirmed_facts,
    revoke_confirmed_fact,
    save_confirmed_fact,
)
from app.services.memory_extraction import extract_memory_candidates
from app.services.memory_recall import (
    MemoryRecallResponse,
    RecallConversationNotFoundError,
    recall_memory,
)


router = APIRouter()


@router.post(
    "/conversations/{conversation_id}/facts",
    response_model=FactResponse,
    status_code=201,
    tags=["memory"],
)
def confirm_fact(
    conversation_id: str,
    body: SaveFactRequest,
    db: Session = Depends(get_db),
):
    try:
        return save_confirmed_fact(
            db,
            conversation_id=conversation_id,
            based_on_version=body.based_on_version,
            fact_key=body.fact_key,
            value=body.value,
            source_message_id=body.source_message_id,
        )
    except FactConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc
    except FactSourceError as exc:
        status = 404 if str(exc) == "conversation_not_found" else 422
        raise HTTPException(
            status_code=status,
            detail=str(exc),
        ) from exc


@router.get(
    "/conversations/{conversation_id}/facts",
    response_model=list[FactResponse],
    tags=["memory"],
)
def get_facts(
    conversation_id: str,
    db: Session = Depends(get_db),
):
    if db.get(Conversation, conversation_id) is None:
        raise HTTPException(
            status_code=404,
            detail="Conversation not found",
        )

    return list_confirmed_facts(
        db,
        conversation_id=conversation_id,
    )


@router.post(
    "/conversations/{conversation_id}/facts/{fact_id}/revoke",
    response_model=FactResponse,
    tags=["memory"],
)
def revoke_fact(
    conversation_id: str,
    fact_id: int,
    body: RevokeFactRequest,
    db: Session = Depends(get_db),
):
    try:
        return revoke_confirmed_fact(
            db,
            conversation_id=conversation_id,
            fact_id=fact_id,
            based_on_version=body.based_on_version,
        )
    except FactNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc
    except FactConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc


@router.get(
    "/conversations/{conversation_id}/memory-recall",
    response_model=MemoryRecallResponse,
    tags=["memory"],
)
def get_recalled_memory(
    conversation_id: str,
    db: Session = Depends(get_db),
):
    try:
        return recall_memory(
            db,
            conversation_id=conversation_id,
        )
    except RecallConversationNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc


@router.post(
    "/conversations/{conversation_id}/memory-candidates",
    response_model=ExtractMemoryResponse,
    tags=["memory"],
)
def extract_memory(
    conversation_id: str,
    body: ExtractMemoryRequest,
    db: Session = Depends(get_db),
    runtime: AppRuntime = Depends(get_runtime),
):
    return extract_memory_candidates(
        conversation_id,
        body,
        db,
        gateway=runtime.gateway,
    )
