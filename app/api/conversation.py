from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.models.responses import (
    ConversationData,
    CreateConversationResponse,
    ErrorResponse,
    MessageData,
    MessageHistoryData,
    MessageHistoryResponse,
)
from app.services.conversation_service import (
    DEFAULT_HISTORY_LIMIT,
    ConversationService,
    get_conversation_service,
)

router = APIRouter(tags=["conversations"])


@router.post(
    "/conversations",
    response_model=CreateConversationResponse,
    status_code=status.HTTP_201_CREATED,
    responses={503: {"model": ErrorResponse}},
)
def create_conversation(
    service: ConversationService = Depends(get_conversation_service),
) -> CreateConversationResponse:
    return CreateConversationResponse(data=ConversationData(conversation_id=service.create()))


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=MessageHistoryResponse,
    responses={404: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
def get_messages(
    conversation_id: UUID,
    limit: int = Query(DEFAULT_HISTORY_LIMIT, ge=1, le=200),
    service: ConversationService = Depends(get_conversation_service),
) -> MessageHistoryResponse:
    """The conversation's latest messages, oldest first, for restoring a chat after a refresh."""
    messages = service.get_messages(conversation_id, limit)
    return MessageHistoryResponse(
        data=MessageHistoryData(
            conversation_id=conversation_id,
            messages=[MessageData(**message.model_dump()) for message in messages],
        )
    )
