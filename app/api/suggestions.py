from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import AppRuntime, get_runtime
from app.schemas.suggestions import (
    CopyEventResponse,
    CopyReadyResponse,
    CopyReportRequest,
    CreateSuggestionRequest,
    SuggestionOutcomeResponse,
    SuggestionResponse,
    GenerationRequestResponse,
    AbandonSuggestionRequest,
    SuggestionAbandonmentResponse,
)
from app.services import generation_requests, suggestions
from app.services.suggestion_outcomes import read_suggestion_outcome, abandon_suggestion
from app.services.suggestion_validity import SuggestionValidity
from app.api.auth import require_operator
from app.schemas.auth import OperatorIdentity


router = APIRouter()


@router.post(
    "/conversations/{conversation_id}/suggestions",
    response_model=SuggestionResponse,
    status_code=201,
    tags=["suggestions"],
)
def create_suggestion(
    conversation_id: str,
    body: CreateSuggestionRequest,
    response: Response,
    db: Session = Depends(get_db),
    runtime: AppRuntime = Depends(get_runtime),
):
    result = suggestions.create_suggestion(
        conversation_id,
        body,
        db,
        turn_engine=runtime.turn_engine,
        tool_executor=runtime.tool_executor,
    )
    response.status_code = 201 if result.created else 200
    return result.suggestion


@router.get(
    "/conversations/{conversation_id}/suggestions",
    response_model=list[SuggestionResponse],
    tags=["suggestions"],
)
def list_suggestions(
    conversation_id: str,
    db: Session = Depends(get_db),
):
    return suggestions.list_suggestions(
        conversation_id,
        db,
    )


@router.get(
    "/conversations/{conversation_id}/suggestions/{suggestion_id}",
    response_model=SuggestionResponse,
    tags=["suggestions"],
)
def get_suggestion(
    conversation_id: str,
    suggestion_id: str,
    db: Session = Depends(get_db),
):
    return suggestions.get_suggestion(
        conversation_id,
        suggestion_id,
        db,
    )


@router.get(
    "/conversations/{conversation_id}/suggestions/{suggestion_id}/outcome",
    response_model=SuggestionOutcomeResponse,
    tags=["suggestions"],
)
def get_suggestion_outcome(
    conversation_id: str,
    suggestion_id: str,
    db: Session = Depends(get_db),
) -> SuggestionOutcomeResponse:
    return read_suggestion_outcome(conversation_id, suggestion_id, db)


@router.get(
    "/conversations/{conversation_id}/suggestions/{suggestion_id}/validity",
    response_model=SuggestionValidity,
    tags=["suggestions"],
)
def get_suggestion_validity(
    conversation_id: str,
    suggestion_id: str,
    db: Session = Depends(get_db),
    runtime: AppRuntime = Depends(get_runtime),
):
    return suggestions.get_suggestion_validity(
        conversation_id,
        suggestion_id,
        db,
        repository=runtime.repository,
    )


@router.post(
    "/conversations/{conversation_id}/suggestions/{suggestion_id}/copy-ready",
    response_model=CopyReadyResponse,
    tags=["suggestions"],
)
def prepare_suggestion_copy(
    conversation_id: str,
    suggestion_id: str,
    db: Session = Depends(get_db),
    runtime: AppRuntime = Depends(get_runtime),
):
    return suggestions.prepare_suggestion_copy(
        conversation_id,
        suggestion_id,
        db,
        repository=runtime.repository,
    )


@router.post(
    "/conversations/{conversation_id}/suggestions/{suggestion_id}/copy-events",
    response_model=CopyEventResponse,
    status_code=201,
    tags=["suggestions"],
)
def report_suggestion_copy(
    conversation_id: str,
    suggestion_id: str,
    body: CopyReportRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    result = suggestions.report_suggestion_copy(
        conversation_id,
        suggestion_id,
        body,
        db,
    )
    response.status_code = 201 if result.created else 200
    return result.event


@router.get(
    "/conversations/{conversation_id}/suggestions/{suggestion_id}/copy-events",
    response_model=list[CopyEventResponse],
    tags=["suggestions"],
)
def list_suggestion_copy_events(
    conversation_id: str,
    suggestion_id: str,
    db: Session = Depends(get_db),
):
    return suggestions.list_suggestion_copy_events(
        conversation_id,
        suggestion_id,
        db,
    )


@router.get(
    "/conversations/{conversation_id}/generation-requests/by-key",
    response_model=GenerationRequestResponse,
    tags=["suggestions"],
)
def get_generation_request(
    conversation_id: str,
    request_key: str = Query(
        min_length=1,
        max_length=64,
        pattern=r"\S",
    ),
    db: Session = Depends(get_db),
):
    return generation_requests.get_generation_request(
        conversation_id,
        request_key.strip(),
        db,
    )


@router.put(
    "/conversations/{conversation_id}/suggestions/{suggestion_id}/abandonment",
    response_model=SuggestionAbandonmentResponse,
    tags=["suggestions"],
)
def put_suggestion_abandonment(
    conversation_id: str,
    suggestion_id: str,
    body: AbandonSuggestionRequest,
    db: Session = Depends(get_db),
    operator: OperatorIdentity = Depends(require_operator),
) -> SuggestionAbandonmentResponse:
    return abandon_suggestion(
        db,
        conversation_id=conversation_id,
        suggestion_id=suggestion_id,
        operator_id=operator.id,
        body=body,
    )
