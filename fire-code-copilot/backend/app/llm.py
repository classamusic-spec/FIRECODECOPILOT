"""Provider-agnostic chat. One interface, two backends:
  - "local": any OpenAI-compatible server (LM Studio, mlx_lm.server, Ollama, vLLM)
  - "anthropic": the Claude API (optional escalation)

Keeping this thin means agent.py never cares which model is doing the work — so you can
run fully local and only flip a config value to escalate a hard question to Claude.
"""
from __future__ import annotations
from .settings import settings


def chat(system: str, user: str, *, provider: str | None = None,
         model: str | None = None, temperature: float | None = None) -> str:
    """Return the model's text response. Raises on transport errors so callers can fall back."""
    provider = provider or settings.generation_provider
    temperature = settings.temperature if temperature is None else temperature

    if provider == "local":
        return _chat_openai_compatible(system, user, model or settings.local_model, temperature)
    if provider == "anthropic":
        return _chat_anthropic(system, user, model or settings.answer_model, temperature)
    raise ValueError(f"Unknown generation provider: {provider}")


def _chat_openai_compatible(system: str, user: str, model: str, temperature: float) -> str:
    from openai import OpenAI
    client = OpenAI(base_url=settings.local_base_url, api_key="not-needed")
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
        temperature=temperature,
    )
    return resp.choices[0].message.content or ""


def _chat_anthropic(system: str, user: str, model: str, temperature: float) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    resp = client.messages.create(
        model=model,
        max_tokens=2048,
        temperature=temperature,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    # Concatenate text blocks.
    return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
