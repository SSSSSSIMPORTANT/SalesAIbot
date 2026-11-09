from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


FactKey = Literal[
    "learning_goal",
    "current_level",
    "preferred_format",
    "concern",
]


class MemoryCandidate(BaseModel):
    """尚未人工确认的记忆候选。"""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        str_strip_whitespace=True,
    )

    fact_key: FactKey
    value: str = Field(min_length=1, max_length=500)


class MemoryCandidateBatch(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
    )

    candidates: list[MemoryCandidate] = Field(max_length=4)

    @model_validator(mode="after")
    def check_unique_keys(self):
        keys = [item.fact_key for item in self.candidates]

        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate fact_key")

        return self