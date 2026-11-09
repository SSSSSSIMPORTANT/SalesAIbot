"""读取并校验应用配置。"""

import os
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field, SecretStr, model_validator


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseModel):
    app_name: str = Field(default="SalesAIbot", min_length=1)
    app_env: Literal["development", "test", "production"] = "development"

    llm_mode: Literal["mock", "live"] = "mock"
    llm_base_url: str = ""
    llm_model: str = ""
    llm_vision_model: str = ""

    llm_api_key: SecretStr = Field(
        default=SecretStr(""),
        exclude=True,
    )

    llm_timeout_seconds: float = Field(
        default=30,
        gt=0,
        le=120,
    )

    @model_validator(mode="after")
    def validate_live_settings(self):
        if self.llm_mode == "live":
            required = {
                "LLM_BASE_URL": self.llm_base_url.strip(),
                "LLM_MODEL": self.llm_model.strip(),
                "LLM_API_KEY": self.llm_api_key.get_secret_value().strip(),
            }

            missing = [
                name
                for name, value in required.items()
                if not value
            ]

            if missing:
                raise ValueError(
                    "Live 模式缺少配置：" + ", ".join(missing)
                )

        return self


def load_settings() -> Settings:
    load_dotenv(PROJECT_ROOT / ".env", override=False)

    return Settings(
        app_name=os.getenv("APP_NAME", "SalesAIbot"),
        app_env=os.getenv("APP_ENV", "development"),
        llm_mode=os.getenv("LLM_MODE", "mock"),
        llm_base_url=os.getenv("LLM_BASE_URL", ""),
        llm_model=os.getenv("LLM_MODEL", ""),
        llm_api_key=os.getenv("LLM_API_KEY", ""),
        llm_timeout_seconds=os.getenv("LLM_TIMEOUT_SECONDS", "30"),
        llm_vision_model=os.getenv("LLM_VISION_MODEL", ""),
    )