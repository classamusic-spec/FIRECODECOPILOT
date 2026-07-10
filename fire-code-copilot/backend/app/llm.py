"""oMLX-only chat boundary for grounded answer generation.

The production answer path uses exactly one OpenAI-compatible endpoint: settings.LOCAL_BASE_URL.
Two non-reasoning generator models are switchable per request. When MLX_THINKING=off, the
client sends no-think request hints and strips accidental reasoning preambles before returning
text to the app.

The only non-oMLX generation path retained is an explicitly configured cloud Claude escalation
for the hardest edge cases. It is disabled by default via DEEP_PROVIDER=off and is never a local
reasoning model.
"""
from __future__ import annotations

from typing import Iterator
from .settings import settings


def _provider_allowed(provider: str) -> None:
    if provider == "local":
        return
    if provider == "anthropic" and settings.deep_provider == "anthropic":
        return
    raise ValueError(
        f"Unsupported generation provider '{provider}'. Fire Code CoPilot is standardized on "
        "GENERATION_PROVIDER=local (oMLX). Optional cloud deep tier requires DEEP_PROVIDER=anthropic."
    )


def chat(system: str, user: str, *, provider: str | None = None,
         model: str | None = None, temperature: float | None = None) -> str:
    """Return generated text. Grounded answer generation always routes through oMLX local."""
    provider = provider or settings.generation_provider
    temperature = settings.temperature if temperature is None else temperature
    _provider_allowed(provider)
    if provider == "anthropic":
        return _chat_anthropic(system, user, model or settings.answer_model, temperature)
    return _chat_openai_compatible(system, user, settings.assert_allowed_generator(model), temperature)


def chat_stream(system: str, user: str, *, provider: str | None = None,
                model: str | None = None, temperature: float | None = None) -> Iterator[str]:
    """Yield generated deltas. Grounded answer streaming always routes through oMLX local."""
    provider = provider or settings.generation_provider
    temperature = settings.temperature if temperature is None else temperature
    _provider_allowed(provider)
    if provider == "anthropic":
        yield from _stream_anthropic(system, user, model or settings.answer_model, temperature)
    else:
        yield from _stream_openai_compatible(system, user, settings.assert_allowed_generator(model), temperature)


def _thinking_off() -> bool:
    return (settings.mlx_thinking or "off").strip().lower() in {"off", "false", "0", "no", "none"}


def _messages(system: str, user: str) -> list[dict]:
    if _thinking_off():
        system = (
            system.rstrip()
            + "\n\nLOCAL MODEL CONTROL: Reasoning/thinking mode is OFF. "
            + "Do not emit hidden reasoning, <think> blocks, analysis preambles, or chain-of-thought. "
            + "Answer only from the retrieved source text and cite only verified sections."
        )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _no_think_extra_body() -> dict:
    if not _thinking_off():
        return {}
    # oMLX/MLX chat-template implementations use different names; servers that do not support
    # one of these fields should ignore it under OpenAI-compatible extra_body handling.
    return {
        "enable_thinking": False,
        "thinking": False,
        "reasoning": {"effort": "none"},
        "chat_template_kwargs": {"enable_thinking": False},
    }


def _strip_reasoning(text: str) -> str:
    if not _thinking_off() or not text:
        return text
    import re
    text = re.sub(r"(?is)<think>.*?</think>", "", text)
    text = re.sub(
        r"(?is)^\s*(thinking|reasoning|analysis)\s*:\s*.*?(?=\n\s*(direct answer|answer|1\.|##|#|\*\*))",
        "",
        text,
    )
    return text.lstrip()


def _filter_reasoning_stream(chunks: Iterator[str]) -> Iterator[str]:
    if not _thinking_off():
        yield from chunks
        return
    in_think = False
    pending = ""
    import re
    for delta in chunks:
        pending += delta
        out = ""
        while pending:
            if in_think:
                end = pending.lower().find("</think>")
                if end == -1:
                    pending = ""
                    break
                pending = pending[end + len("</think>"):]
                in_think = False
                continue
            start = pending.lower().find("<think>")
            if start == -1:
                out += pending
                pending = ""
            else:
                out += pending[:start]
                pending = pending[start + len("<think>"):]
                in_think = True
        out = re.sub(r"(?im)^\s*(thinking|reasoning|analysis)\s*:\s*$", "", out)
        if out:
            yield out


def _chat_openai_compatible(system: str, user: str, model: str, temperature: float) -> str:
    from openai import OpenAI
    client = OpenAI(base_url=settings.local_base_url, api_key=settings.local_api_key or "not-needed")
    resp = client.chat.completions.create(
        model=model,
        messages=_messages(system, user),
        temperature=temperature,
        extra_body=_no_think_extra_body() or None,
    )
    return _strip_reasoning(resp.choices[0].message.content or "")


def _stream_openai_compatible(system: str, user: str, model: str, temperature: float) -> Iterator[str]:
    from openai import OpenAI
    client = OpenAI(base_url=settings.local_base_url, api_key=settings.local_api_key or "not-needed")
    stream = client.chat.completions.create(
        model=model,
        messages=_messages(system, user),
        temperature=temperature,
        stream=True,
        extra_body=_no_think_extra_body() or None,
    )

    def raw():
        for chunk in stream:
            delta = (chunk.choices[0].delta.content if chunk.choices else None) or ""
            if delta:
                yield delta

    yield from _filter_reasoning_stream(raw())


def _chat_anthropic(system: str, user: str, model: str, temperature: float) -> str:
    if not settings.anthropic_api_key:
        raise ValueError("ANTHROPIC_API_KEY is not set.")
    import anthropic
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    resp = client.messages.create(
        model=model,
        system=system,
        messages=[{"role": "user", "content": user}],
        max_tokens=1600,
        temperature=temperature,
    )
    return "".join(getattr(block, "text", "") for block in resp.content)


def _stream_anthropic(system: str, user: str, model: str, temperature: float) -> Iterator[str]:
    if not settings.anthropic_api_key:
        raise ValueError("ANTHROPIC_API_KEY is not set.")
    import anthropic
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    with client.messages.stream(
        model=model,
        system=system,
        messages=[{"role": "user", "content": user}],
        max_tokens=1600,
        temperature=temperature,
    ) as stream:
        for text in stream.text_stream:
            if text:
                yield text


def _dep_importable(name: str) -> bool:
    import importlib.util
    return importlib.util.find_spec(name) is not None


def check() -> list[str]:
    """Human-readable local runtime preflight."""
    lines = [f"Generation provider (GENERATION_PROVIDER): {settings.generation_provider}"]
    if settings.generation_provider != "local":
        lines.append("  ERROR: Fire Code CoPilot expects GENERATION_PROVIDER=local for the oMLX stack.")
    lines.append(f"  Dependency 'openai' installed: {_dep_importable('openai')}")
    lines.append(f"  LOCAL_BASE_URL:   {settings.local_base_url}")
    lines.append(f"  GENERATOR_MODEL:  {settings.generator_model}")
    lines.append(f"  GENERATOR_MODELS: {', '.join(settings.generator_model_list)}")
    lines.append(f"  EMBEDDING_MODEL:  {settings.embedding_model}")
    lines.append(f"  RERANKER_MODEL:   {settings.reranker_model}")
    lines.append(f"  USE_RERANKER:     {settings.use_reranker}")
    lines.append(f"  MLX_THINKING:     {settings.mlx_thinking}")
    lines.append(f"  DEEP_PROVIDER:    {settings.deep_provider}")
    lines.append("  Next: ensure oMLX is running at LOCAL_BASE_URL with both generators, embeddings, and reranker pinned.")
    return lines


def model_check() -> list[str]:
    """Live oMLX readiness check: models endpoint + generators + embeddings + reranker + no-think chat."""
    import json
    import urllib.request

    base = settings.local_base_url.rstrip("/")
    headers = {"Content-Type": "application/json"}
    if settings.local_api_key:
        headers["Authorization"] = f"Bearer {settings.local_api_key}"

    def req(path: str, payload: dict | None = None, timeout: int = 45):
        data = json.dumps(payload).encode() if payload is not None else None
        r = urllib.request.Request(base + path, data=data, headers=headers, method="POST" if payload is not None else "GET")
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return json.loads(body) if body else {}

    lines: list[str] = [f"oMLX endpoint: {base}"]
    ok = True
    try:
        models = req("/models")
        ids = {m.get("id") for m in models.get("data", []) if isinstance(m, dict)}
        lines.append(f"/models reachable: yes ({len(ids)} models)")
    except Exception as e:
        return [*lines, f"/models reachable: no ({type(e).__name__}: {e})", "MODEL-CHECK: FAIL"]

    for mid in settings.generator_model_list:
        present = mid in ids
        ok = ok and present
        lines.append(f"generator pinned: {mid}: {'yes' if present else 'NO'}")
    for mid in [settings.embedding_model, settings.reranker_model]:
        present = mid in ids
        ok = ok and present
        lines.append(f"retrieval model pinned: {mid}: {'yes' if present else 'NO'}")

    try:
        emb = req("/embeddings", {"model": settings.embedding_model, "input": ["warm fire code retrieval"]})
        dim = len(emb.get("data", [{}])[0].get("embedding", []))
        lines.append(f"embedding reachable: yes (dim={dim})")
    except Exception as e:
        ok = False
        lines.append(f"embedding reachable: NO ({type(e).__name__}: {e})")

    try:
        rr = req("/rerank", {"model": settings.reranker_model, "query": "sprinkler", "documents": ["automatic sprinkler system", "unrelated"], "top_n": 2})
        lines.append(f"reranker reachable: yes ({len(rr.get('results', rr.get('data', [])))} results)")
    except Exception as e:
        ok = False
        lines.append(f"reranker reachable: NO ({type(e).__name__}: {e})")

    for mid in settings.generator_model_list:
        try:
            chat = req("/chat/completions", {
                "model": mid,
                "messages": _messages("Answer without reasoning.", "Reply with exactly: OK"),
                "temperature": 0,
                **_no_think_extra_body(),
            }, timeout=120)
            text = _strip_reasoning(chat.get("choices", [{}])[0].get("message", {}).get("content", ""))
            no_think = "<think" not in text.lower() and "reasoning:" not in text.lower() and "analysis:" not in text.lower()
            ok = ok and no_think and bool(text.strip())
            active = " active" if mid == settings.generator_model else ""
            lines.append(f"generator chat{active}: {mid}: {'yes' if text.strip() else 'NO'} ({text[:80]!r})")
            lines.append(f"thinking disabled{active}: {mid}: {'yes' if no_think else 'NO'}")
        except Exception as e:
            ok = False
            lines.append(f"generator chat: {mid}: NO ({type(e).__name__}: {e})")

    lines.append(f"MODEL-CHECK: {'PASS' if ok else 'FAIL'}")
    return lines


if __name__ == "__main__":
    import sys
    if "--model-check" in sys.argv:
        print("\n".join(model_check()))
    elif "--check" in sys.argv:
        print("\n".join(check()))
    else:
        print("usage: python -m app.llm --check | --model-check")
