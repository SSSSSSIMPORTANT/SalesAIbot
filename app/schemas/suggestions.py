from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

from app.schemas.replies import ReplyPreviewRequest, ReplyPreviewResponse


class CreateSuggestionRequest(ReplyPreviewRequest):
    request_key: str = Field(min_length=1, max_length=64)


class SuggestionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    conversation_id: str
    based_on_version: int
    product_id: str | None
    reply_text: str
    generation_snapshot: ReplyPreviewResponse
    created_at: str


class CopyReadyResponse(BaseModel):
    suggestion_id: str
    based_on_version: int
    text: str


class CopyReportRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    request_key: str = Field(min_length=1, max_length=64)


class CopyEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    suggestion_id: str
    request_key: str
    created_at: str


class GenerationRequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    conversation_id: str
    request_key: str
    based_on_version: int
    product_id: str | None
    status: Literal["running", "succeeded", "failed"]
    suggestion_id: str | None
    error_code: str | None
    started_at: str
    finished_at: str | None


class ReportedSuggestionMessage(BaseModel):
    message_id: int
    adoption_mode: Literal["verbatim", "edited"]
    recorded_at: str


class AbandonSuggestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    reason: str = Field(min_length=1, max_length=300)


class SuggestionAbandonmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    suggestion_id: str
    operator_id: str
    reason: str
    created_at: str


class SuggestionOutcomeResponse(BaseModel):
    suggestion_id: str
    status: Literal["unknown", "copied", "abandoned", "reported_sent"]
    copy_count: int
    reported_messages: list[ReportedSuggestionMessage]
    abandonment: SuggestionAbandonmentResponse | None = None


