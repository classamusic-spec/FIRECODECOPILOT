"""oMLX-only generation dispatch tests.

The answer path is standardized on the local OpenAI-compatible oMLX endpoint. Older direct
OpenAI/llama.cpp/in-process MLX providers are intentionally unsupported for grounded answers.
"""
import pytest
import app.llm as llm


def _spy(monkeypatch, name: str):
    calls = []
    monkeypatch.setattr(llm, name, lambda *a, **k: calls.append((a, k)) or f"<{name}>")
    return calls


def test_routes_to_local_generator(monkeypatch):
    calls = _spy(monkeypatch, "_chat_openai_compatible")
    assert llm.chat("sys", "usr", provider="local") == "<_chat_openai_compatible>"
    assert calls


def test_default_provider_comes_from_settings(monkeypatch):
    monkeypatch.setattr(llm.settings, "generation_provider", "local")
    calls = _spy(monkeypatch, "_chat_openai_compatible")
    llm.chat("sys", "usr")
    assert calls


def test_runtime_rejects_non_omlx_local_providers():
    for provider in ["openai", "llamacpp", "mlx", "does-not-exist"]:
        with pytest.raises(ValueError, match="oMLX|GENERATION_PROVIDER=local"):
            llm.chat("sys", "usr", provider=provider)


def test_anthropic_only_allowed_when_deep_provider_is_anthropic(monkeypatch):
    monkeypatch.setattr(llm.settings, "deep_provider", "off")
    with pytest.raises(ValueError):
        llm.chat("sys", "usr", provider="anthropic")

    monkeypatch.setattr(llm.settings, "deep_provider", "anthropic")
    calls = _spy(monkeypatch, "_chat_anthropic")
    assert llm.chat("sys", "usr", provider="anthropic") == "<_chat_anthropic>"
    assert calls


def test_messages_add_thinking_off_control(monkeypatch):
    monkeypatch.setattr(llm.settings, "mlx_thinking", "off")
    msgs = llm._messages("Base system.", "Question?")
    assert "Reasoning/thinking mode is OFF" in msgs[0]["content"]


def test_strip_reasoning_removes_think_blocks(monkeypatch):
    monkeypatch.setattr(llm.settings, "mlx_thinking", "off")
    assert llm._strip_reasoning("<think>secret</think>Answer") == "Answer"


def test_check_reports_omlx_stack(monkeypatch):
    monkeypatch.setattr(llm.settings, "generation_provider", "local")
    out = llm.check()
    assert any("LOCAL_BASE_URL" in line for line in out)
    assert any("GENERATOR_MODELS" in line for line in out)
    assert any("MLX_THINKING" in line for line in out)
