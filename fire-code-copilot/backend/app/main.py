"""FastAPI server for Fire Code CoPilot (standalone, fully local).

Run:  uvicorn app.main:app --reload --port 8000
Then POST /ask, or use the CLI (python -m app.cli) which calls the same agent directly.
"""
from __future__ import annotations
import json
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse

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
    from .warm import status
    return {"ok": True, "jurisdiction": settings.jurisdiction,
            "generation_provider": settings.generation_provider, "model": settings.local_model,
            "ready": status()}


@app.post("/warm")
def warm():
    """Pre-load the local embedder (+ reranker) so the first question isn't a cold-start hang."""
    from .warm import warm as run_warm
    return run_warm()


def _http_errors(fn):
    """Map known failure classes to proper HTTP errors instead of bare 500s + leaked tracebacks:
    an unknown collection is the caller's mistake (404); an unreachable/failing model is an
    upstream problem (502 with a plain-language hint)."""
    def wrapped():
        try:
            return fn()
        except Exception as e:
            name = type(e).__name__
            if "NotFound" in name and "collection" in str(e).lower():
                raise HTTPException(status_code=404, detail=str(e))
            if "Connection" in name or "APIConnection" in name:
                raise HTTPException(status_code=502,
                                    detail=f"The model backend is unreachable: {e}. "
                                           f"Check that your model server is running (see /health).")
            raise
    return wrapped()


def _hist(req) -> list[dict]:
    """History exchanges as plain dicts for the agent."""
    return [e.model_dump() for e in (req.history or [])]


@app.post("/ask")
def ask(req: AskRequest):
    return _http_errors(lambda: result_dict(agent_ask(
        req.question, mode=req.mode, building_context=req.building_context,
        active_cycle_block=active_cycle_block(), deep=req.deep, provider=req.provider,
        collection=req.collection, history=_hist(req))))


@app.post("/ask/stream")
def ask_stream(req: AskRequest):
    """Token-by-token streaming of /ask via Server-Sent Events. Each line is
    `data: {json}\\n\\n` with a typed event (token | clarify | meta | error | done)."""
    def sse():
        try:
            if req.mode == "retrieve":
                # Retrieve-only needs no LLM: emit the sources as a meta event and finish.
                res = agent_ask(req.question, mode="retrieve",
                                building_context=req.building_context,
                                active_cycle_block=active_cycle_block(),
                                collection=req.collection, history=_hist(req))
                d = result_dict(res)
                yield f"data: {json.dumps({'type': 'meta', 'sources': d['sources'], 'citations_ok': True, 'unverified': [], 'answer_suffix': '', 'escalated': False, 'confidence': d.get('confidence'), 'confidence_band': d.get('confidence_band')})}\n\n"
                yield f"data: {json.dumps({'type': 'done'})}\n\n"
                return
            for event in agent_ask_stream(
                req.question, building_context=req.building_context,
                active_cycle_block=active_cycle_block(), deep=req.deep,
                provider=req.provider, collection=req.collection, history=_hist(req)):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as e:  # never leave the stream hanging on an unexpected error
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(sse(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/clarify")
def clarify(req: ClarifyRequest):
    """Continue after the marshal answers the clarifying questions: fold the answers into the
    building context and re-ask."""
    ctx = "\n".join(c for c in (req.building_context, req.answers) if c.strip())
    return _http_errors(lambda: result_dict(agent_ask(
        req.question, building_context=ctx, active_cycle_block=active_cycle_block(),
        deep=req.deep, provider=req.provider, collection=req.collection, history=_hist(req))))


@app.post("/ingest")
def ingest(req: IngestRequest):
    from .ingest import ingest as run_ingest
    return run_ingest(force=req.force)


@app.post("/ingest/stream")
def ingest_stream(req: IngestRequest):
    """Ingest with LIVE progress via SSE (`data: {json}\\n\\n` events: start | file | file_done |
    removed | done | error). The plain POST /ingest blocks silently, which on a real book set
    looks like a hang — this is what the Library UI uses instead."""
    import queue
    import threading
    from .ingest import ingest as run_ingest

    q: queue.Queue = queue.Queue()

    def worker():
        try:
            result = run_ingest(force=req.force, on_event=q.put)
            if "error" in result:
                q.put({"type": "error", "message": result["error"]})
                q.put({"type": "done", "summary": result})
        except Exception as e:
            q.put({"type": "error", "message": str(e)})
            q.put({"type": "done", "summary": {}})
        q.put(None)  # sentinel: stream over

    threading.Thread(target=worker, daemon=True).start()

    def sse():
        while True:
            ev = q.get()
            if ev is None:
                break
            yield f"data: {json.dumps(ev)}\n\n"

    return StreamingResponse(sse(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/books")
def books():
    """The Library: every PDF in the books folder + manifest fields + indexed state."""
    from .ingest import list_books
    return {"books": list_books(), "active_collection": settings.active_collection}


@app.put("/books-manifest")
def put_books_manifest(entries: dict):
    """Save the books manifest (which book → which edition/collection) from the Library UI."""
    from .ingest import save_books_manifest
    return save_books_manifest(entries)


@app.get("/page-image")
def page_image(source: str, page: int):
    """Render ONE page of an ingested code book as a PNG, so the marshal can verify a citation
    against the real typeset page (not just the extracted text).

    Copyright containment: this serves a single page to the LOCAL UI on request — the same
    footprint as showing the extracted chunk text. Nothing is stored, exported, or listed;
    `source` must be a bare filename inside the code-books folder (no path traversal).
    """
    import os
    from pathlib import Path
    name = Path(source).name
    if name != source or not name.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="source must be a bare .pdf filename")
    pdf = Path(os.path.expanduser(settings.code_books_dir)) / name
    if not pdf.is_file():
        raise HTTPException(status_code=404, detail=f"{name} is not in your code-books folder")
    import fitz
    doc = fitz.open(pdf)
    try:
        if not (1 <= page <= len(doc)):
            raise HTTPException(status_code=404, detail=f"{name} has no page {page}")
        png = doc[page - 1].get_pixmap(dpi=120).tobytes("png")
    finally:
        doc.close()
    return Response(content=png, media_type="image/png",
                    headers={"Cache-Control": "private, max-age=3600"})


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
