from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.services.reply_rendering import HandoffReason


class CreateHandoffRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: HandoffReason


class ResolveHandoffRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    resolution: str = Field(min_length=1, max_length=500)


class HandoffResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source_message_id: int
    reason: HandoffReason
    created_by_operator_id: str
    created_at: str
    resolved_by_operator_id: str | None
    resolved_at: str | None
    resolution: str | None

    @computed_field
    @property
    def status(self) -> Literal["pending", "resolved"]:
        return "resolved" if self.resolved_at is not None else "pending"
