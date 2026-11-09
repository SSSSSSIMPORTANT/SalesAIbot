"""Application assembly. Start with: uvicorn app.main:app --port 8021."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.errors import register_error_handlers
from app.api.router import api_router
from app.config import Settings, load_settings
from app.dependencies import AppRuntime
from app.knowledge import KnowledgeRepository
from app.llm import ModelGateway, build_model_gateway
from app.services.turn_engine import SalesTurnEngine
from app.tools import SalesToolExecutor
from app.version import APP_VERSION


def create_app(
    settings: Settings | None = None,
    model_gateway: ModelGateway | None = None,
    knowledge_repository: KnowledgeRepository | None = None,
) -> FastAPI:
    """Build an application with its own settings, model and knowledge sources."""
    settings = settings if settings is not None else load_settings()
    gateway = (
        model_gateway if model_gateway is not None else build_model_gateway(settings)
    )
    repository = (
        knowledge_repository
        if knowledge_repository is not None
        else KnowledgeRepository()
    )
    application = FastAPI(
        title=settings.app_name,
        description="销售 Agent 学习项目：从会话、知识、工具和记忆逐步搭建。",
        version=APP_VERSION,
    )
    application.state.runtime = AppRuntime(
        settings=settings,
        gateway=gateway,
        repository=repository,
        turn_engine=SalesTurnEngine(gateway),
        tool_executor=SalesToolExecutor(repository),
    )
    register_error_handlers(application)
    application.include_router(api_router)
    application.mount(
        "/workbench",
        StaticFiles(directory=Path(__file__).resolve().parent / "workbench", html=True),
        name="workbench",
    )
    return application


app = create_app()
