"""The MCP surface for outer agents (Hermes etc.): tool signatures thread through to the
agent correctly, retrieve mode needs no LLM, and the stdio server actually starts and
answers a tools/list request."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp")

import app.mcp_server as srv  # noqa: E402  (import after the skip guard)
from app.agent import AgentResult  # noqa: E402


def test_lookup_threads_all_params_to_agent(monkeypatch):
    captured = {}

    def fake_ask(question, **kw):
        captured.update(question=question, **kw)
        return AgentResult(mode="retrieve", answer=None, citations_ok=True, unverified=[],
                           sources=[{"text": "903.2.8 …", "metadata": {"section": "903.2.8"}}])

    monkeypatch.setattr(srv, "ask", fake_ask)
    monkeypatch.setattr(srv, "active_cycle_block", lambda: "ACTIVE CYCLE …")

    out = srv.fire_code_lookup(
        question="what about existing buildings?", mode="retrieve",
        building_context="R-2, 4 stories", collection="csfsc_2018", deep=True,
        history=[{"question": "sprinklers for R-2?", "answer": "yes per 903.2.8"}])

    assert captured["question"] == "what about existing buildings?"
    assert captured["mode"] == "retrieve"
    assert captured["collection"] == "csfsc_2018"
    assert captured["deep"] is True
    assert captured["history"][0]["question"] == "sprinklers for R-2?"
    assert out["sources"][0]["metadata"]["section"] == "903.2.8"
    assert out["answer"] is None                       # retrieve mode: outer agent reasons


def test_lookup_default_mode_is_retrieve_and_needs_no_llm(monkeypatch):
    """Default must be the no-LLM path so Hermes works without oMLX running."""
    monkeypatch.setattr(srv, "active_cycle_block", lambda: "")
    import app.agent as agent
    monkeypatch.setattr(agent, "retrieve_scored", lambda q, **k: [])
    monkeypatch.setattr(agent.llm, "chat",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("LLM must not run")))
    out = srv.fire_code_lookup(question="anything")
    assert out["mode"] == "retrieve" and out["answer"] is None


def test_stdio_server_boots_and_lists_tools(tmp_path):
    """End-to-end: spawn `python -m app.mcp_server`, run the MCP handshake over stdio, and
    confirm our three tools are advertised. This is exactly what Hermes does on connect."""
    backend = Path(__file__).resolve().parents[1]
    msgs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2024-11-05",
                    "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    stdin = "".join(json.dumps(m) + "\n" for m in msgs)
    proc = subprocess.run([sys.executable, "-m", "app.mcp_server"], input=stdin,
                          capture_output=True, text=True, timeout=60, cwd=str(backend))
    tools = set()
    for line in proc.stdout.splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        for t in (payload.get("result") or {}).get("tools", []):
            tools.add(t["name"])
    assert {"fire_code_lookup", "fire_code_list_editions", "fire_code_cycle_status"} <= tools, \
        f"tools/list missing tools; stdout={proc.stdout[:500]} stderr={proc.stderr[:500]}"
