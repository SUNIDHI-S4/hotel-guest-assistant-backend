class AppError(Exception):
    """An expected failure that maps to a structured API error response."""

    status_code = 500
    code = "internal_error"
    message = "Something went wrong. Please try again."

    def __init__(self, message: str | None = None):
        self.message = message or self.message
        super().__init__(self.message)


class ConversationNotFound(AppError):
    status_code = 404
    code = "conversation_not_found"
    message = "We couldn't find that conversation. Please start a new chat."


class InvalidAvailabilityRequest(AppError):
    """The guest's dates or party size can't be searched; the message is safe to show them."""

    status_code = 422
    code = "invalid_availability_request"
    message = "Those dates or guest numbers don't look right."


class HotelNotFound(AppError):
    """DEFAULT_HOTEL_ID points at a hotel that isn't in the database (a setup problem)."""

    status_code = 500
    code = "hotel_not_configured"
    message = "The hotel's information isn't available right now. Please try again later."


class AssistantUnavailable(AppError):
    """Gemini could not be reached or rejected the request (timeout, 5xx, bad key...)."""

    status_code = 503
    code = "assistant_unavailable"
    message = "Our assistant is having trouble right now. Please try again in a moment."


class AssistantRateLimited(AppError):
    status_code = 429
    code = "assistant_busy"
    message = "Our assistant is very busy right now. Please try again in a few seconds."


class AssistantEmptyResponse(AppError):
    """Gemini answered with nothing usable (blocked, empty or cut off before any text)."""

    status_code = 502
    code = "assistant_no_answer"
    message = "I couldn't put together an answer to that. Could you try rephrasing your question?"


class DatabaseError(AppError):
    status_code = 503
    code = "database_unavailable"
    message = "We couldn't reach our database right now. Please try again in a moment."
