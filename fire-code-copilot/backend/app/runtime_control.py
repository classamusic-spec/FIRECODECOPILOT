"""Explicit, local-only oMLX runtime controls for Fire Code CoPilot.

A model is never loaded simply because it was selected in the UI. The user must press
"Load selected"; that starts the managed oMLX service if necessary, then sends one bounded
warm-up request for the exact chosen generator. Stopping uses only `omlx stop` — no shell
interpolation and no process-wide kill by port.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from .settings import settings

# These are the only chat generators exposed by the Fire Code CoPilot runtime surface.
# IDs match the oMLX model discovery names on this workstation.
_MODEL_CATALOG = (
    {
        "id": "granite-4.0-h-small-MLX-8bit",
        "label": "Granite",
        "memory_gb": 33.5,
        "description": "Balanced grounded-code generator.",
    },
    {
        "id": "gemma-4-26b-a4b-it-4bit",
        "label": "Gemma 4",
        "memory_gb": 15.0,
        "description": "Lighter local generator for responsive research.",
    },
    {
        "id": "Ornith-1.0-35B-bf16",
        "label": "Ornith 35B",
        "memory_gb": 68.7,
        "description": "Largest option; load only when its extra capacity is needed.",
    },
)


def catalog() -> list[dict]:
    """UI-safe model metadata. This is a catalog only — it loads no weights."""
    return [dict(model) for model in _MODEL_CATALOG]


def _profile(model: str) -> dict:
    for profile in _MODEL_CATALOG:
        if profile["id"] == model:
            return profile
    allowed = ", ".join(profile["label"] for profile in _MODEL_CATALOG)
    raise ValueError(f"Unknown Fire Code CoPilot model. Choose one of: {allowed}.")


def _run_omlx(args: list[str], timeout: int) -> str:
    """Call the user-managed oMLX CLI without a shell or interpolated user input."""
    binary = os.environ.get("OMLX_BIN") or shutil.which("omlx")
    if not binary:
        raise RuntimeError("oMLX is not installed or is not on PATH.")
    result = subprocess.run(
        [binary, *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    output = "\n".join(part for part in (result.stdout.strip(), result.stderr.strip()) if part).strip()
    if result.returncode != 0:
        raise RuntimeError(output or f"oMLX exited with status {result.returncode}.")
    return output


def _headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if settings.local_api_key:
        headers["Authorization"] = f"Bearer {settings.local_api_key}"
    return headers


def _request(path: str, payload: dict | None = None, timeout: int = 12) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = Request(
        settings.local_base_url.rstrip("/") + path,
        data=data,
        headers=_headers(),
        method="POST" if payload is not None else "GET",
    )
    with urlopen(req, timeout=timeout) as response:
        body = response.read().decode("utf-8")
    return json.loads(body) if body else {}


def _available_model_ids() -> set[str] | None:
    try:
        models = _request("/models")
    except (URLError, TimeoutError, OSError, ValueError):
        return None
    return {
        str(row.get("id"))
        for row in models.get("data", [])
        if isinstance(row, dict) and row.get("id")
    }


def status() -> dict:
    """Return readiness without starting the service or loading any model."""
    available = _available_model_ids()
    running = available is not None
    # A stopped server cannot truthfully tell us which catalog entries it has discovered. Keep
    # the explicit Load action available in that state; load() starts oMLX and performs the real
    # availability check before weights are allocated.
    return {
        "running": running,
        "active_model": settings.generator_model,
        "models": [{**profile, "available": (not running) or profile["id"] in (available or set())} for profile in _MODEL_CATALOG],
    }


def start() -> dict:
    """Start the managed oMLX service only; model weights still stay unloaded."""
    before = _available_model_ids()
    if before:
        return {"running": True, "message": "Local model server is already running."}
    _run_omlx(["start", "--timeout", "90"], timeout=100)
    if not _available_model_ids():
        raise RuntimeError("oMLX reported a start, but its model endpoint is still unavailable.")
    return {"running": True, "message": "Local model server started. Select a model, then load it explicitly."}


def _warm_generator(model: str) -> dict:
    """Bounded one-token request that makes oMLX load only the selected generator."""
    response = _request(
        "/chat/completions",
        {
            "model": model,
            "messages": [{"role": "user", "content": "Reply with exactly READY."}],
            "temperature": 0,
            "max_tokens": 2,
            "enable_thinking": False,
            "thinking": False,
        },
        timeout=180,
    )
    text = str(response.get("choices", [{}])[0].get("message", {}).get("content", "")).strip()
    return {"model": model, "reply": text}


def _persist_active_model(model: str) -> None:
    """Persist the explicit runtime choice without changing .env or auto-loading anything."""
    settings.generator_model = model
    settings.local_model = model
    path = Path(settings.runtime_state_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"generator_model": model, "mlx_thinking": "off"}, indent=2))


def load(model: str) -> dict:
    """Explicitly load the selected catalog model after ensuring oMLX is running."""
    _profile(model)
    start()
    available = _available_model_ids()
    if not available or model not in available:
        raise RuntimeError(f"{model} is not available in the running oMLX model directory.")
    _warm_generator(model)
    _persist_active_model(model)
    return {"loaded": True, "active_model": model, "message": f"{_profile(model)['label']} is loaded and selected for new questions."}


def stop() -> dict:
    """Stop the managed oMLX service and release all model memory."""
    _run_omlx(["stop", "--timeout", "30"], timeout=40)
    return {"running": False, "message": "Local model server stopped."}
