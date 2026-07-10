"""Runtime-control behavior: explicit oMLX lifecycle and model load gates."""
from __future__ import annotations

from fastapi.testclient import TestClient
import app.main as main


def test_catalog_exposes_only_the_three_fire_code_generator_choices():
    from app import runtime_control

    models = runtime_control.catalog()
    assert [m["id"] for m in models] == [
        "granite-4.0-h-small-MLX-8bit",
        "gemma-4-26b-a4b-it-4bit",
        "Ornith-1.0-35B-bf16",
    ]
    assert [m["label"] for m in models] == ["Granite", "Gemma 4", "Ornith 35B"]


def test_load_starts_runtime_then_warms_exact_selected_model(monkeypatch):
    from app import runtime_control

    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(runtime_control, "start", lambda: calls.append(("start", None)) or {"running": True})
    monkeypatch.setattr(runtime_control, "_available_model_ids", lambda: {"Ornith-1.0-35B-bf16"})
    monkeypatch.setattr(
        runtime_control,
        "_warm_generator",
        lambda model: calls.append(("warm", model)) or {"model": model, "reply": "READY"},
    )

    result = runtime_control.load("Ornith-1.0-35B-bf16")

    assert calls == [("start", None), ("warm", "Ornith-1.0-35B-bf16")]
    assert result["active_model"] == "Ornith-1.0-35B-bf16"
    assert result["loaded"] is True


def test_stop_delegates_only_to_managed_omlx_command(monkeypatch):
    from app import runtime_control

    seen: list[list[str]] = []
    monkeypatch.setattr(runtime_control, "_run_omlx", lambda args, timeout: seen.append(args) or "stopped")

    result = runtime_control.stop()

    assert seen == [["stop", "--timeout", "30"]]
    assert result == {"running": False, "message": "Local model server stopped."}


def test_runtime_routes_expose_status_load_and_stop(monkeypatch):
    from app import runtime_control

    monkeypatch.setattr(runtime_control, "status", lambda: {"running": False, "models": []})
    monkeypatch.setattr(runtime_control, "load", lambda model: {"loaded": True, "active_model": model})
    monkeypatch.setattr(runtime_control, "stop", lambda: {"running": False, "message": "Local model server stopped."})
    client = TestClient(main.app)

    assert client.get("/runtime").json() == {"running": False, "models": []}
    assert client.post("/runtime/load", json={"model": "Gemma 4"}).json() == {
        "loaded": True,
        "active_model": "Gemma 4",
    }
    assert client.post("/runtime/stop").json()["running"] is False
