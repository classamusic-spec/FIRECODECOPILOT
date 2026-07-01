"""FastAPI server for Fire Code CoPilot (standalone, fully local).

Run:  uvicorn app.main:app --reload --port 8000
Then POST /ask, or use the CLI (python -m app.cli) which calls the same agent directly.
"""
from __future__ import annotations
import json
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .settings import settings
from .models import (AskRequest, ClarifyRequest, IngestRequest, FeedbackRequest, VerifyRequest)
from .agent import ask as agent_ask, ask_stream as agent_ask_stream, result_dict
from .cycles import active_cycle_block, cycle_reminder
from . import feedback as fb

app = FastAPI(title="Fire Code CoPilot", version="1.0.0")

# Allow a local frontend (Phase 4) to call the API.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
def health():
    return {"ok": True, "jurisdiction": settings.jurisdiction,
            "generation_provider": settings.generation_provider, "model": settings.local_model}


@app.post("/ask")
def ask(req: AskRequest):
    res = agent_ask(req.question, mode=req.mode, building_context=req.building_context,
                    active_cycle_block=active_cycle_block(), deep=req.deep, provider=req.provider,
                    collection=req.collection)
    return result_dict(res)


@app.post("/ask/stream")
def ask_stream(req: AskRequest):
    """Token-by-token streaming of /ask via Server-Sent Events. Each line is
    `data: {json}\\n\\n` with a typed event (token | clarify | meta | error | done)."""
    def sse():
        try:
            for event in agent_ask_stream(
                req.question, building_context=req.building_context,
                active_cycle_block=active_cycle_block(), deep=req.deep,
                provider=req.provider, collection=req.collection):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as e:  # never leave the stream hanging on an unexpected error
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(sse(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/clarify")
def clarify(req: ClarifyRequest):
    """Continue after the marshal answers the clarifying questions: fold the answers into the
    building context and re-ask."""
    ctx = "\n".join(c for c in (req.building_context, req.answers) if c.strip())
    res = agent_ask(req.question, building_context=ctx, active_cycle_block=active_cycle_block(),
                    deep=req.deep, provider=req.provider, collection=req.collection)
    return result_dict(res)


@app.post("/ingest")
def ingest(req: IngestRequest):
    from .ingest import ingest as run_ingest
    return run_ingest(force=req.force)


@app.get("/collections")
def collections():
    """List the indexed editions/cycles (one Chroma collection each) + which is active."""
    from .ingest import list_collections
    return {"active": settings.active_collection, "collections": list_collections()}


@app.post("/feedback")
def feedback(req: FeedbackRequest):
    return fb.record_feedback(question=req.question, answer=req.answer, rating=req.rating,
                              note=req.note, building_context=req.building_context,
                              sources=req.sources)


@app.post("/verify")
def verify(req: VerifyRequest):
    return fb.promote_verified(question=req.question, corrected_answer=req.corrected_answer,
                               governing_sections=req.governing_sections, edition=req.edition)


@app.get("/review-queue")
def review_queue():
    return {"items": fb.review_queue()}


@app.get("/verified")
def verified():
    """List the Verified Answer Library entries (for review / cleanup)."""
    return {"items": fb.list_verified()}


@app.delete("/verified/{vid}")
def delete_verified(vid: str):
    """Remove a stale/wrong verified answer so it stops surfacing as [VERIFIED]."""
    return fb.delete_verified(vid)


@app.get("/cycle-status")
def cycle_status():
    return {"active": active_cycle_block(), "reminder": cycle_reminder()}
