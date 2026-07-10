"""Persisted oMLX generator selection; no model load/restart is performed here."""
from __future__ import annotations
import json
from pathlib import Path
from urllib.request import Request, urlopen
from .settings import settings


def available_omlx_models() -> set[str]:
    headers = {"Authorization": f"Bearer {settings.local_api_key}"} if settings.local_api_key else {}
    req = Request(settings.local_base_url.rstrip("/") + "/models", headers=headers)
    with urlopen(req, timeout=10) as response:
        data = json.loads(response.read().decode("utf-8"))
    return {str(row.get("id")) for row in data.get("data", []) if isinstance(row, dict) and row.get("id")}


def select(model: str) -> dict:
    model = settings.assert_allowed_generator(model)
    available = available_omlx_models()
    if model not in available:
        raise ValueError(f"Generator is configured but not pinned by oMLX: {model}")
    settings.generator_model = model
    settings.local_model = model
    path = Path(settings.runtime_state_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"generator_model": model, "mlx_thinking": "off"}, indent=2))
    return {"active_generator": model, "thinking": "off", "available": sorted(available)}


def restore() -> None:
    path = Path(settings.runtime_state_file)
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text())
        chosen = str(data.get("generator_model", ""))
        if chosen in settings.generator_model_list:
            settings.generator_model = chosen
            settings.local_model = chosen
    except Exception:
        pass
