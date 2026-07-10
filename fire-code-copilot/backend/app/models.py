"""Pydantic request schemas for the FastAPI server."""
from __future__ import annotations
from pydantic import BaseModel


class Exchange(BaseModel):
    """One prior Q&A exchange from the current conversation, oldest-first in the list. Lets a
    follow-up like "what about existing buildings?" retrieve and answer with the topic it refers
    to. The client sends only the last few; the server also caps how much it uses."""
    question: str
    answer: str = ""


class AskRequest(BaseModel):
    question: str
    mode: str = "answer"            # "answer" | "retrieve"
    building_context: str = ""      # occupancy, new/existing, type, height, area, sprinklered...
    deep: bool = False              # escalate to DEEP_PROVIDER/DEEP_MODEL for hard questions
    provider: str | None = None     # legacy override; answer path is oMLX local by default
    generator_model: str | None = None  # runtime switch among GENERATOR_MODELS
    collection: str | None = None   # query a specific edition/cycle collection (default: active)
    history: list[Exchange] = []    # prior exchanges in this conversation (follow-up memory)


class ClarifyRequest(BaseModel):
    """Continue a thread after the marshal answers the clarifying questions. `answers` are folded
    into building_context so the next pass has the decisive facts."""
    question: str
    answers: str = ""               # the marshal's replies to the clarifying questions
    building_context: str = ""      # any context already gathered earlier in the thread
    deep: bool = False
    provider: str | None = None
    generator_model: str | None = None
    collection: str | None = None
    history: list[Exchange] = []    # prior exchanges in this conversation (follow-up memory)


class IngestRequest(BaseModel):
    force: bool = False
    use_ocr: bool | None = None
    version_suffix: str | None = None


class FeedbackRequest(BaseModel):
    question: str
    answer: str = ""
    rating: str                     # "up" | "down"
    note: str = ""                  # optional "correct this" text
    building_context: str = ""
    sources: list[dict] = []        # the source chunks the answer was built on


class VerifyRequest(BaseModel):
    """Promote a confirmed/corrected answer into the Verified Answer Library."""
    question: str
    corrected_answer: str
    governing_sections: list[str] = []
    edition: str = ""


class ModelSelectRequest(BaseModel):
    model: str


class RuntimeLoadRequest(BaseModel):
    """An explicit user request to load one curated local generator into oMLX."""
    model: str
