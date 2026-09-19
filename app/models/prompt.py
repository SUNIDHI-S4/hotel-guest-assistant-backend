from typing import Literal

from pydantic import BaseModel


class ChatTurn(BaseModel):
    """One turn of dialogue. Gemini calls the assistant's role "model"."""

    role: Literal["user", "model"]
    text: str


class Prompt(BaseModel):
    system_instruction: str  # rules + hotel facts; never contains guest text
    turns: list[ChatTurn]  # earlier dialogue, ending with the guest's current question
