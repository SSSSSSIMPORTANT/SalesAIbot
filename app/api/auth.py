from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import AppRuntime, get_runtime
from app.schemas.auth import LoginRequest, OperatorIdentity
from app.services.operator_sessions import (
    SESSION_COOKIE,
    SESSION_TTL_SECONDS,
    LoginRejectedError,
    find_session_operator,
    login_operator,
    revoke_session,
)


class AuthRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handle(request: Request) -> Response:
            try:
                return await original(request)
            except RequestValidationError:
                raise HTTPException(
                    status_code=422,
                    detail="Invalid authentication request",
                ) from None

        return handle


router = APIRouter(route_class=AuthRoute, tags=["auth"])


def require_same_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    expected = f"{request.url.scheme}://{request.url.netloc}"
    if origin != expected:
        raise HTTPException(status_code=403, detail="Invalid origin")


def cookie_options(runtime: AppRuntime) -> dict:
    return {
        "path": "/",
        "httponly": True,
        "samesite": "lax",
        "secure": runtime.settings.app_env == "production",
    }


def require_operator(
    request: Request,
    db: Session = Depends(get_db),
) -> OperatorIdentity:
    account = find_session_operator(db, request.cookies.get(SESSION_COOKIE))
    if account is None:
        raise HTTPException(status_code=401, detail="Login required")
    identity = OperatorIdentity.model_validate(account)
    db.rollback()

    page_operator_id = request.headers.get("x-workbench-operator")
    if page_operator_id is not None and page_operator_id != identity.id:
        raise HTTPException(status_code=401, detail="Session identity changed")

    return identity


@router.post(
    "/auth/login",
    response_model=OperatorIdentity,
    dependencies=[Depends(require_same_origin)],
)
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    runtime: AppRuntime = Depends(get_runtime),
):
    try:
        identity, token = login_operator(
            db,
            username=body.username,
            password=body.password.get_secret_value(),
            previous_token=request.cookies.get(SESSION_COOKIE),
        )
    except LoginRejectedError:
        raise HTTPException(status_code=401, detail="Invalid credentials") from None

    response.headers["Cache-Control"] = "no-store"
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_TTL_SECONDS,
        **cookie_options(runtime),
    )
    return identity


@router.get("/auth/me", response_model=OperatorIdentity)
def get_me(
    response: Response,
    operator: OperatorIdentity = Depends(require_operator),
):
    response.headers["Cache-Control"] = "no-store"
    return operator


@router.post(
    "/auth/logout",
    status_code=204,
    response_class=Response,
    dependencies=[Depends(require_same_origin)],
)
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    runtime: AppRuntime = Depends(get_runtime),
):
    revoke_session(db, request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE, **cookie_options(runtime))
    response.headers["Cache-Control"] = "no-store"
