import pytest
from pydantic import ValidationError

from app.config import Settings


def test_live_mode_requires_connection_settings():
    with pytest.raises(
        ValidationError,
        match="Live 模式缺少配置",
    ):
        Settings(llm_mode="live")