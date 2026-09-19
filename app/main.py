import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import chat, conversation, health
from app.config import get_settings

API_PREFIX = "/api/v1"


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

    for module in (health, conversation, chat):
        app.include_router(module.router, prefix=API_PREFIX)

    return app


app = create_app()
