"""Central config. Local-first: defaults assume local LLM + local embeddings + local reranker.
Everything is overridable via .env (see .env.example)."""
from __future__ import annotations
from pathlib import Path
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root = the fire-code-copilot/ dir (this file is backend/app/settings.py). We anchor the
# .env file and all relative paths here so the app behaves the same whether you run it from the
# repo root, from backend/, or via `uvicorn`/`python -m` — cwd no longer changes where data lands.
_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ROOT / ".env"), extra="ignore")

    # --- Generation ---
    # "local" = OpenAI-compatible server (LM Studio / mlx_lm.server / Ollama). "anthropic" = Claude API.
    generation_provider: str = "local"
    local_base_url: str = "http://localhost:1234/v1"
    local_model: str = "glm-5.2"
    anthropic_api_key: str = ""
    answer_model: str = "claude-sonnet-4-6"          # only used if provider == anthropic

    # Optional escalation for hard questions (kept local by default).
    deep_provider: str = "local"
    deep_model: str = "glm-5.2"

    # --- Embeddings ---
    embedding_provider: str = "local"                # "local" | "voyage"
    local_embedding_model: str = "BAAI/bge-m3"
    voyage_api_key: str = ""
    voyage_model: str = "voyage-law-2"

    # --- Reranker (two-stage retrieval) ---
    use_reranker: bool = True
    reranker_model: str = "BAAI/bge-reranker-v2-m3"  # or "Qwen/Qwen3-Reranker-4B"
    retrieve_before_rerank: int = 20
    keep_after_rerank: int = 6

    # --- Citation safety ---
    validate_citations: bool = True

    # --- Paths / app ---
    jurisdiction: str = "City of Hartford, Connecticut"
    code_books_dir: str = "./code_books"
    data_dir: str = "./data"
    code_cycles_config: str = "./config/code_cycles.yaml"
    chroma_dir: str = "./data/chroma"
    active_collection: str = "csfsc_2022"            # set per active edition

    # Generation tuning
    temperature: float = 0.1                         # low for code work

    @model_validator(mode="after")
    def _anchor_paths(self):
        """Resolve relative path settings against the project root (not the current dir), so
        `./code_books` and `./data` always point at the same place regardless of where you run."""
        for field in ("code_books_dir", "data_dir", "code_cycles_config", "chroma_dir"):
            val = Path(getattr(self, field)).expanduser()
            if not val.is_absolute():
                val = _ROOT / val
            setattr(self, field, str(val))
        return self


settings = Settings()
