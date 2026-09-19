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


class DatabaseError(AppError):
    status_code = 503
    code = "database_unavailable"
    message = "We couldn't reach our database right now. Please try again in a moment."
