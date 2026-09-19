from fastapi import APIRouter, Depends, status

from app.config import get_settings
from app.models.responses import ConversationData, CreateConversationResponse, ErrorResponse
from app.repositories.conversation_repository import (
    ConversationRepository,
    get_conversation_repository,
)

router = APIRouter(tags=["conversations"])


@router.post(
    "/conversations",
    response_model=CreateConversationResponse,
    status_code=status.HTTP_201_CREATED,
    responses={503: {"model": ErrorResponse}},
)
def create_conversation(
    repository: ConversationRepository = Depends(get_conversation_repository),
) -> CreateConversationResponse:
    conversation_id = repository.create(get_settings().default_hotel_id)
    return CreateConversationResponse(data=ConversationData(conversation_id=conversation_id))
