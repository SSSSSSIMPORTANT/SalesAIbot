from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.memory_candidates import FactKey, MemoryCandidate


class ExtractMemoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    based_on_version: int = Field(ge=0, strict=True)
    source_message_id: int = Field(gt=0, strict=True)


class ExtractMemoryResponse(BaseModel):
    conversation_id: str
    based_on_version: int
    source_message_id: int
    source_text: str
    candidates: list[MemoryCandidate]


class RevokeFactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    based_on_version: int = Field(ge=0, strict=True)


class SaveFactRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    based_on_version: int = Field(ge=0, strict=True)
    fact_key: FactKey
    value: str = Field(min_length=1, max_length=500)
    source_message_id: int = Field(gt=0, strict=True)


class FactResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    conversation_id: str
    fact_key: FactKey
    value: str
    source_message_id: int
    status: Literal["confirmed", "superseded", "revoked"]
    created_at: str
    revoked_at: str | None
