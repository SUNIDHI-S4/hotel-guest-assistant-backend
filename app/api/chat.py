import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.exceptions import AppError
from app.models.chat import ChatRequest, ChatResponse, ErrorChatResponse
from app.services.chat_service import ChatService, get_chat_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])

_ERROR_RESPONSES = {
    status: {"model": ErrorChatResponse} for status in (404, 429, 500, 502, 503)
}


def _error(status_code: int, message: str, code: str) -> JSONResponse:
    body = ErrorChatResponse(message=message, code=code)
    return JSONResponse(status_code=status_code, content=body.model_dump())


@router.post("/chat", response_model=ChatResponse, responses=_ERROR_RESPONSES)
def chat(request: ChatRequest, service: ChatService = Depends(get_chat_service)):
    """Answer one guest message.

    Success is HTTP 200 with a `text`, `slot_collection` or `availability` body. Any failure
    while answering (unknown conversation, database or Gemini trouble) has the matching HTTP
    status and an `error` body, so the frontend reads the same fields either way.
    """
    try:
        return service.handle(request.conversation_id, request.message)
    except AppError as exc:
        return _error(exc.status_code, exc.message, exc.code)
    except Exception:
        logger.exception("Unexpected error while handling a chat message")
        return _error(500, "Something went wrong on our side. Please try again.", "internal_error")
