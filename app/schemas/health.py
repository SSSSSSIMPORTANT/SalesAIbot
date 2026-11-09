from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """约定健康接口返回哪些字段及字段类型。"""

    status: Literal["ok"] = "ok"
    app: str
    environment: Literal["development", "test", "production"]
    version: str
