from fastapi import APIRouter, Depends

from app.dependencies import AppRuntime, get_runtime
from app.schemas.health import HealthResponse
from app.version import APP_VERSION


router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["health"])
def health(runtime: AppRuntime = Depends(get_runtime)) -> HealthResponse:
    # 这里只表示应用能响应请求，后续另建数据库/模型就绪检查。
    return HealthResponse(
        app=runtime.settings.app_name,
        environment=runtime.settings.app_env,
        version=APP_VERSION,
    )
