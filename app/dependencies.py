"""Per-application dependencies exposed to HTTP routers."""

from dataclasses import dataclass

from fastapi import Request

from app.config import Settings
from app.knowledge import KnowledgeRepository
from app.llm import ModelGateway
from app.services.turn_engine import SalesTurnEngine
from app.tools import SalesToolExecutor


@dataclass(frozen=True)
class AppRuntime:
    settings: Settings
    gateway: ModelGateway
    repository: KnowledgeRepository
    turn_engine: SalesTurnEngine
    tool_executor: SalesToolExecutor


def get_runtime(request: Request) -> AppRuntime:
    return request.app.state.runtime
