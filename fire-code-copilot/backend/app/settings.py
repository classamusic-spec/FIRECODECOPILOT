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
    # "local"    = OpenAI-compatible server (LM Studio / mlx_lm.server / Ollama)
    # "openai"   = the OpenAI API (or an OpenAI-compatible endpoint via OPENAI_BASE_URL)
    # "anthropic"= Claude API
    # "llamacpp" = a local .gguf file loaded directly via llama-cpp-python
    # "mlx"      = an MLX model loaded directly via mlx_lm (Apple Silicon only)
    generation_provider: str = "local"
    local_base_url: str = "http://localhost:1234/v1"
    local_model: str = "glm-5.2"
    anthropic_api_key: str = ""
    answer_model: str = "claude-sonnet-4-6"          # only used if provider == anthropic

    # --- openai provider (the OpenAI API, or an OpenAI-compatible endpoint) ---
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    openai_base_url: str = ""                         # blank = api.openai.com; set for Azure/compatible

    # --- llamacpp provider (direct .gguf via llama-cpp-python) ---
    gguf_model_path: str = ""                        # path to a .gguf file (relative paths anchored to root)
    gguf_n_ctx: int = 8192                           # context window the model is loaded with
    gguf_n_gpu_layers: int = -1                      # layers to offload to GPU; -1 = offload all if possible

    # --- mlx provider (direct MLX model via mlx_lm; Apple Silicon only) ---
    mlx_model: str = ""                              # HF repo id (e.g. mlx-community/...) or local path

    # Optional escalation for hard questions (kept local by default).
    deep_provider: str = "local"
    deep_model: str = "glm-5.2"

    # --- Embeddings ---
    embedding_provider: str = "local"                # "local" | "voyage"
    local_embedding_model: str = "BAAI/bge-m3"
    voyage_api_key: str = ""
    voyage_model: str = "voyage-law-2"
    cache_embeddings: bool = True                     # reuse embeddings of identical text (data/embed_cache.sqlite)
    # Optional role prefixes for asymmetric-search embedders (e.g. BGE v1.5). Default off (BGE-M3
    # needs none); a v1.5 user can set the query prefix to the model's search instruction.
    embedding_query_prefix: str = ""                 # prepended to queries only (input_type="query")
    embedding_passage_prefix: str = ""               # prepended to documents only (input_type="document")

    # --- Parent-document retrieval ---
    # Match a precise child window, but hand the model back the whole section it came from (better
    # context without losing citation granularity). Only affects sections long enough to be split.
    parent_retrieval: bool = True

    # --- Reranker (two-stage retrieval) ---
    use_reranker: bool = True
    reranker_model: str = "BAAI/bge-reranker-v2-m3"  # or "Qwen/Qwen3-Reranker-4B"
    retrieve_before_rerank: int = 20
    keep_after_rerank: int = 6

    # --- Query expansion (recall) ---
    expand_queries: bool = True                      # spell out occupancy codes/acronyms before embedding

    # --- Hybrid retrieval (dense + BM25 lexical, reciprocal-rank fused) ---
    use_hybrid: bool = True                          # fuse a BM25 channel for exact-token lookups
    bm25_candidates: int = 20                        # lexical candidates to fuse with the dense set

    # --- Citation safety ---
    validate_citations: bool = True

    # --- Paths / app ---
    jurisdiction: str = "City of Hartford, Connecticut"
    code_books_dir: str = "./code_books"
    data_dir: str = "./data"
    code_cycles_config: str = "./config/code_cycles.yaml"
    chroma_dir: str = "./data/chroma"
    active_collection: str = "csfsc_2022"            # set per active edition
    verified_collection: str = "verified_answers"    # marshal-confirmed answers (learning loop)
    # Max embedding distance for a verified answer to surface as relevant (normalized vectors,
    # L2: 1.0 ≈ cosine 0.5). Chroma always returns the k nearest regardless of how far — without
    # this cutoff an unrelated confirmed answer fronts every query as [VERIFIED].
    verified_max_distance: float = 1.0
    feedback_db: str = "./data/feedback.sqlite"      # 👍/👎 + corrections

    # --- Deep-mode escalation ---
    # When the reranker is on and the top relevance score is below this, a non-deep "answer"
    # auto-escalates to DEEP_PROVIDER/DEEP_MODEL (a stronger model) for one retry.
    deep_escalate_below: float = 0.2

    # --- Confidence surfacing (heuristic; needs the reranker for a numeric signal) ---
    confidence_high_above: float = 0.6              # top rerank score >= this -> "high"
    # (low band uses deep_escalate_below; between the two is "medium".)
    auto_flag_low_confidence: bool = True           # log low-confidence answers to the review queue

    # --- Table extraction ---
    extract_tables: bool = True                     # emit ruled tables as their own markdown chunks

    # --- OCR (scanned books) ---
    use_ocr: bool = False                           # OCR image-only pages (needs tesseract; see docs)
    ocr_language: str = "eng"                        # Tesseract language pack(s), e.g. "eng"

    # Generation tuning
    temperature: float = 0.1                         # low for code work

    @model_validator(mode="after")
    def _anchor_paths(self):
        """Resolve relative path settings against the project root (not the current dir), so
        `./code_books` and `./data` always point at the same place regardless of where you run."""
        # gguf_model_path is a real file path -> anchor it. mlx_model is intentionally NOT here:
        # it may be a HF repo id (e.g. "mlx-community/...") which must never be path-anchored.
        anchored = ("code_books_dir", "data_dir", "code_cycles_config", "chroma_dir", "feedback_db",
                    "gguf_model_path")
        for field in anchored:
            raw = getattr(self, field)
            if not raw:            # empty (e.g. unset gguf path) — leave as-is, don't anchor "" to root
                continue
            val = Path(raw).expanduser()
            if not val.is_absolute():
                val = _ROOT / val
            setattr(self, field, str(val))
        return self


settings = Settings()
