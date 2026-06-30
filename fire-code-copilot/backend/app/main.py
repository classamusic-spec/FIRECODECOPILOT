"""FastAPI server for Fire Code CoPilot (standalone, fully local).

Run:  uvicorn app.main:app --reload --port 8000
Then POST /ask, or use the CLI (python -m app.cli) which calls the same agent directly.
"""
from __future__ import annotations
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .settings import settings
from .models import AskRequest, IngestRequest
from .agent import ask as agent_ask, result_dict
from .cycles import active_cycle_block, cycle_reminder

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
                    active_cycle_block=active_cycle_block(), deep=req.deep)
    return result_dict(res)


@app.post("/ingest")
def ingest(req: IngestRequest):
    from .ingest import ingest as run_ingest
    return run_ingest(force=req.force)


@app.get("/cycle-status")
def cycle_status():
    return {"active": active_cycle_block(), "reminder": cycle_reminder()}
