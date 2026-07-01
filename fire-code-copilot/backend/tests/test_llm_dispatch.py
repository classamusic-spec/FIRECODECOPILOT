"""Provider dispatch for llm.chat — verifies each GENERATION_PROVIDER routes to the right
per-provider helper. We monkeypatch the helpers so NO heavy deps (llama_cpp, mlx_lm, openai,
anthropic) are needed and no real inference happens. Also smoke-tests `--check`.
"""
import app.llm as llm


def _spy(monkeypatch, name: str):
    """Replace a per-provider helper with a recorder; return the call-log list."""
    calls = []
    # All helpers share the (system, user, ...) shape; record args and return a marker.
    monkeypatch.setattr(llm, name, lambda *a, **k: calls.append((a, k)) or f"<{name}>")
    return calls


def test_routes_to_local(monkeypatch):
    calls = _spy(monkeypatch, "_chat_openai_compatible")
    assert llm.chat("sys", "usr", provider="local") == "<_chat_openai_compatible>"
    assert calls


def test_routes_to_anthropic(monkeypatch):
    calls = _spy(monkeypatch, "_chat_anthropic")
    assert llm.chat("sys", "usr", provider="anthropic") == "<_chat_anthropic>"
    assert calls


def test_routes_to_llamacpp(monkeypatch):
    calls = _spy(monkeypatch, "_chat_llamacpp")
    assert llm.chat("sys", "usr", provider="llamacpp") == "<_chat_llamacpp>"
    assert calls


def test_routes_to_mlx(monkeypatch):
    calls = _spy(monkeypatch, "_chat_mlx")
    assert llm.chat("sys", "usr", provider="mlx") == "<_chat_mlx>"
    assert calls


def test_unknown_provider_raises():
    import pytest
    with pytest.raises(ValueError):
        llm.chat("sys", "usr", provider="does-not-exist")


def test_default_provider_comes_from_settings(monkeypatch):
    # No explicit provider -> falls back to settings.generation_provider.
    monkeypatch.setattr(llm.settings, "generation_provider", "mlx")
    calls = _spy(monkeypatch, "_chat_mlx")
    llm.chat("sys", "usr")
    assert calls


# --- llamacpp missing-config errors (no heavy deps loaded; only reached if importable) ---

def test_llamacpp_missing_path_raises(monkeypatch):
    # Pretend llama_cpp is importable so we get past the ImportError guard to the path check.
    import sys, types
    fake = types.ModuleType("llama_cpp")
    fake.Llama = lambda **k: None
    monkeypatch.setitem(sys.modules, "llama_cpp", fake)
    monkeypatch.setattr(llm.settings, "gguf_model_path", "")
    monkeypatch.setattr(llm, "_llama", None)
    import pytest
    with pytest.raises(ValueError, match="GGUF_MODEL_PATH"):
        llm._get_llama()


def test_mlx_missing_model_raises(monkeypatch):
    import sys, types
    fake = types.ModuleType("mlx_lm")
    fake.load = lambda mid: (None, None)
    monkeypatch.setitem(sys.modules, "mlx_lm", fake)
    monkeypatch.setattr(llm.settings, "mlx_model", "")
    monkeypatch.setattr(llm, "_mlx", None)
    import pytest
    with pytest.raises(ValueError, match="MLX_MODEL"):
        llm._get_mlx()


# --- --check diagnostic runs for a couple of configs without crashing ---

def test_check_runs_for_local(monkeypatch):
    monkeypatch.setattr(llm.settings, "generation_provider", "local")
    out = llm.check()
    assert isinstance(out, list) and any("local" in line for line in out)


def test_check_runs_for_llamacpp(monkeypatch):
    monkeypatch.setattr(llm.settings, "generation_provider", "llamacpp")
    monkeypatch.setattr(llm.settings, "gguf_model_path", "/nope/missing.gguf")
    out = llm.check()
    assert any("GGUF_MODEL_PATH" in line for line in out)


def test_check_runs_for_mlx(monkeypatch):
    monkeypatch.setattr(llm.settings, "generation_provider", "mlx")
    monkeypatch.setattr(llm.settings, "mlx_model", "")
    out = llm.check()
    assert any("MLX_MODEL" in line for line in out)


def test_check_runs_for_anthropic(monkeypatch):
    monkeypatch.setattr(llm.settings, "generation_provider", "anthropic")
    out = llm.check()
    assert any("ANTHROPIC_API_KEY" in line for line in out)
