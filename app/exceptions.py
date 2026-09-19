class AppError(Exception):
    """An expected failure that maps to a structured API error response."""

    status_code = 500
    code = "internal_error"
    message = "Something went wrong. Please try again."

    def __init__(self, message: str | None = None):
        self.message = message or self.message
        super().__init__(self.message)


class InvalidAvailabilityRequest(AppError):
    """The guest's dates or party size can't be searched; the message is safe to show them."""

    status_code = 422
    code = "invalid_availability_request"
    message = "Those dates or guest numbers don't look right."


class DatabaseError(AppError):
    status_code = 503
    code = "database_unavailable"
    message = "We couldn't reach our database right now. Please try again in a moment."
