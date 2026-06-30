"""Provider-agnostic chat. One interface, four backends:
  - "local":     any OpenAI-compatible server (LM Studio, mlx_lm.server, Ollama, vLLM)
  - "llamacpp":  a local .gguf file loaded directly via llama-cpp-python (no server)
  - "mlx":       an MLX model loaded directly via mlx_lm (Apple Silicon only, no server)
  - "anthropic": the Claude API (optional escalation)

Keeping this thin means agent.py never cares which model is doing the work — so you can
run fully local and only flip a config value to escalate a hard question to Claude.

The "llamacpp" and "mlx" backends import their heavy deps LAZILY (only when first used) and
cache the loaded model in a module global, so importing this module stays cheap and the model
loads exactly once. Those deps are NOT in the core install — see requirements-local-llm.txt.
"""
from __future__ import annotations
from .settings import settings

# Lazy singletons for the direct-load backends (mirrors embeddings.py / reranker.py).
_llama = None        # cached llama_cpp.Llama instance
_mlx = None          # cached (model, tokenizer) tuple from mlx_lm.load


def chat(system: str, user: str, *, provider: str | None = None,
         model: str | None = None, temperature: float | None = None) -> str:
    """Return the model's text response. Raises on transport errors so callers can fall back."""
    provider = provider or settings.generation_provider
    temperature = settings.temperature if temperature is None else temperature

    if provider == "local":
        return _chat_openai_compatible(system, user, model or settings.local_model, temperature)
    if provider == "llamacpp":
        return _chat_llamacpp(system, user, temperature)
    if provider == "mlx":
        return _chat_mlx(system, user, temperature)
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


def _get_llama():
    """Lazy-load the .gguf via llama-cpp-python, once. Loads the whole model into memory."""
    global _llama
    if _llama is None:
        try:
            from llama_cpp import Llama
        except ImportError as e:
            raise ImportError(
                "The 'llamacpp' provider needs llama-cpp-python, which isn't installed.\n"
                "  Install it:   pip install llama-cpp-python\n"
                "  GPU builds:   CMAKE_ARGS=\"-DLLAMA_METAL=on\"  pip install llama-cpp-python   # Apple Silicon\n"
                "                CMAKE_ARGS=\"-DLLAMA_CUBLAS=on\" pip install llama-cpp-python   # NVIDIA/CUDA\n"
                "  (see backend/requirements-local-llm.txt)"
            ) from e
        path = settings.gguf_model_path
        if not path:
            raise ValueError("GGUF_MODEL_PATH is not set — point it at your .gguf file (settings.gguf_model_path).")
        from pathlib import Path
        if not Path(path).is_file():
            raise FileNotFoundError(f"GGUF_MODEL_PATH does not point at a file: {path}")
        _llama = Llama(
            model_path=path,
            n_ctx=settings.gguf_n_ctx,
            n_gpu_layers=settings.gguf_n_gpu_layers,
            verbose=False,
        )
    return _llama


def _chat_llamacpp(system: str, user: str, temperature: float) -> str:
    """Generate via a directly-loaded .gguf using llama.cpp's chat-completion API."""
    llama = _get_llama()
    resp = llama.create_chat_completion(
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
        temperature=temperature,
    )
    return resp["choices"][0]["message"]["content"] or ""


def _get_mlx():
    """Lazy-load an MLX model + tokenizer via mlx_lm, once (Apple Silicon only)."""
    global _mlx
    if _mlx is None:
        try:
            from mlx_lm import load
        except ImportError as e:
            raise ImportError(
                "The 'mlx' provider needs mlx-lm, which isn't installed (Apple Silicon only).\n"
                "  Install it:   pip install mlx-lm\n"
                "  (see backend/requirements-local-llm.txt)"
            ) from e
        model_id = settings.mlx_model
        if not model_id:
            raise ValueError("MLX_MODEL is not set — set it to a HF repo id or local path (settings.mlx_model).")
        _mlx = load(model_id)
    return _mlx


def _chat_mlx(system: str, user: str, temperature: float) -> str:
    """Generate via a directly-loaded MLX model. Build one prompt from system+user."""
    from mlx_lm import generate
    model, tokenizer = _get_mlx()
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": user}]
    # Prefer the tokenizer's chat template (correct special tokens); fall back to plain text.
    if getattr(tokenizer, "chat_template", None):
        prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    else:
        prompt = f"{system}\n\n{user}"
    return generate(model, tokenizer, prompt=prompt, temp=temperature)


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


# --------------------------------------------------------------------------------------
#  Diagnostic:  python -m app.llm --check
#  Prints which provider is configured, whether its dependency is importable, and whether
#  the configured model looks usable — with actionable next steps. Never imports the heavy
#  deps unless present (catches ImportError) and never attempts real inference.
# --------------------------------------------------------------------------------------

def _dep_importable(module: str) -> bool:
    """True if `module` can be imported, without keeping it loaded for real work."""
    import importlib.util
    return importlib.util.find_spec(module) is not None


def check() -> list[str]:
    """Build a human-readable diagnostic report (list of lines) for the configured provider."""
    p = settings.generation_provider
    lines = [f"Generation provider (GENERATION_PROVIDER): {p}"]

    if p == "local":
        lines.append(f"  Dependency 'openai' installed: {_dep_importable('openai')}"
                     if _dep_importable('openai') else
                     "  Dependency 'openai': NOT installed  ->  pip install openai")
        lines.append(f"  LOCAL_BASE_URL: {settings.local_base_url}")
        lines.append(f"  LOCAL_MODEL:    {settings.local_model}")
        lines.append("  Next: ensure your OpenAI-compatible server (LM Studio / mlx_lm.server / Ollama) "
                     "is running at LOCAL_BASE_URL.")

    elif p == "llamacpp":
        ok = _dep_importable("llama_cpp")
        lines.append(f"  Dependency 'llama_cpp' installed: {ok}"
                     if ok else
                     "  Dependency 'llama_cpp': NOT installed  ->  pip install llama-cpp-python "
                     "(GPU: CMAKE_ARGS=\"-DLLAMA_METAL=on\" / \"-DLLAMA_CUBLAS=on\")")
        path = settings.gguf_model_path
        if not path:
            lines.append("  GGUF_MODEL_PATH: NOT set  ->  set it to your .gguf file")
        else:
            from pathlib import Path
            exists = Path(path).is_file()
            lines.append(f"  GGUF_MODEL_PATH: {path}  (file exists: {exists})")
            if not exists:
                lines.append("  Next: download a .gguf and point GGUF_MODEL_PATH at it.")
        lines.append(f"  GGUF_N_CTX: {settings.gguf_n_ctx}   GGUF_N_GPU_LAYERS: {settings.gguf_n_gpu_layers}")

    elif p == "mlx":
        ok = _dep_importable("mlx_lm")
        lines.append(f"  Dependency 'mlx_lm' installed: {ok}"
                     if ok else
                     "  Dependency 'mlx_lm': NOT installed  ->  pip install mlx-lm  (Apple Silicon only)")
        mid = settings.mlx_model
        lines.append(f"  MLX_MODEL: {mid}" if mid else
                     "  MLX_MODEL: NOT set  ->  set it to a HF repo id (mlx-community/...) or local path")
        if mid:
            lines.append("  Next: first use will download the model from HF if it's a repo id.")

    elif p == "anthropic":
        ok = _dep_importable("anthropic")
        lines.append(f"  Dependency 'anthropic' installed: {ok}"
                     if ok else
                     "  Dependency 'anthropic': NOT installed  ->  pip install anthropic")
        has_key = bool(settings.anthropic_api_key)
        lines.append(f"  ANTHROPIC_API_KEY present: {has_key}")
        lines.append(f"  ANSWER_MODEL: {settings.answer_model}")
        if not has_key:
            lines.append("  Next: set ANTHROPIC_API_KEY in your .env.")

    else:
        lines.append(f"  UNKNOWN provider '{p}'. Valid: local | llamacpp | mlx | anthropic.")

    return lines


if __name__ == "__main__":
    import sys
    if "--check" in sys.argv:
        print("\n".join(check()))
    else:
        print("usage: python -m app.llm --check")
