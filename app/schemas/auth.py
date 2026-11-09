from pydantic import BaseModel, ConfigDict, Field, SecretStr


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=128)
    password: SecretStr = Field(min_length=1, max_length=128)


class OperatorIdentity(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    username: str
