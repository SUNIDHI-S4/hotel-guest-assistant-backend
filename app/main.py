import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import chat, conversation, health
from app.config import get_settings
from app.exceptions import AppError
from app.models.responses import ErrorDetail, ErrorResponse

API_PREFIX = "/api/v1"


def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
    body = ErrorResponse(error=ErrorDetail(code=exc.code, message=exc.message))
    return JSONResponse(status_code=exc.status_code, content=body.model_dump())


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    app = FastAPI(title="Hotel Guest Assistant API", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    app.add_exception_handler(AppError, handle_app_error)

    for module in (health, conversation, chat):
        app.include_router(module.router, prefix=API_PREFIX)

    return app


app = create_app()
