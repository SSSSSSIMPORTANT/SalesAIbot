"""Register each implemented API module exactly once."""

from fastapi import APIRouter, Depends, Request

from app.api import (
    auth,
    conversations,
    customers,
    health,
    memory,
    messages,
    replies,
    screenshots,
    suggestions,
    products,
)
from app.api.ownership import require_owned_path


def require_write_origin(request: Request) -> None:
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        auth.require_same_origin(request)


api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)

for router in (
    customers.router,
    conversations.router,
    messages.router,
    memory.router,
    replies.router,
    screenshots.router,
    suggestions.router,
    products.router,
):
    api_router.include_router(
        router,
        dependencies=[
            Depends(require_owned_path),
            Depends(require_write_origin),
        ],
    )
