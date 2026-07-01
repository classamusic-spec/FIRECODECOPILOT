"""Pydantic request schemas for the FastAPI server."""
from __future__ import annotations
from pydantic import BaseModel


class AskRequest(BaseModel):
    question: str
    mode: str = "answer"            # "answer" | "retrieve"
    building_context: str = ""      # occupancy, new/existing, type, height, area, sprinklered...
    deep: bool = False              # escalate to DEEP_PROVIDER/DEEP_MODEL for hard questions
    provider: str | None = None     # override generation backend: "local" | "anthropic"
    collection: str | None = None   # query a specific edition/cycle collection (default: active)


class ClarifyRequest(BaseModel):
    """Continue a thread after the marshal answers the clarifying questions. `answers` are folded
    into building_context so the next pass has the decisive facts."""
    question: str
    answers: str = ""               # the marshal's replies to the clarifying questions
    building_context: str = ""      # any context already gathered earlier in the thread
    deep: bool = False
    provider: str | None = None
    collection: str | None = None


class IngestRequest(BaseModel):
    force: bool = False


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
