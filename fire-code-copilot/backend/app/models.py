"""Pydantic request schemas for the FastAPI server."""
from __future__ import annotations
from pydantic import BaseModel


class AskRequest(BaseModel):
    question: str
    mode: str = "answer"            # "answer" | "retrieve"
    building_context: str = ""      # occupancy, new/existing, type, height, area, sprinklered...
    deep: bool = False              # escalate to DEEP_PROVIDER/DEEP_MODEL for hard questions


class IngestRequest(BaseModel):
    force: bool = False
