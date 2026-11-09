from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.services.errors import ServiceError


async def service_error_handler(request: Request, exc: ServiceError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


def register_error_handlers(application: FastAPI) -> None:
    application.add_exception_handler(ServiceError, service_error_handler)
