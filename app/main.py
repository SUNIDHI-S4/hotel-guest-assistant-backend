import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import chat, conversation, health
from app.config import get_settings
from app.exceptions import AppError
from app.models.responses import ErrorDetail, ErrorResponse

API_PREFIX = "/api/v1"


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    body = ErrorResponse(error=ErrorDetail(code=code, message=message))
    return JSONResponse(status_code=status_code, content=body.model_dump())


def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
    return _error_response(exc.status_code, exc.code, exc.message)


def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    """Report bad input in the same shape as every other error."""
    first = exc.errors()[0]
    field = ".".join(str(part) for part in first["loc"][1:])  # drop "path" / "query" / "body"
    message = f"Invalid request: {field} - {first['msg']}" if field else "Invalid request."
    return _error_response(422, "invalid_request", message)


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
    app.add_exception_handler(RequestValidationError, handle_validation_error)

    for module in (health, conversation, chat):
        app.include_router(module.router, prefix=API_PREFIX)

    return app


app = create_app()
