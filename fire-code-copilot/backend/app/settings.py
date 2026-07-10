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

    # --- Generation (oMLX-only runtime) ---
    # "local" = the one OpenAI-compatible oMLX endpoint at LOCAL_BASE_URL.
    # The answer path never uses in-process MLX/GGUF or a local reasoning/deep model.
    generation_provider: str = "local"
    local_base_url: str = "http://localhost:8000/v1"
    local_api_key: str = "not-needed"                 # local oMLX bearer token, if configured
    generator_model: str = "granite-4.0-h-small-MLX-8bit"
    generator_models: str = "granite-4.0-h-small-MLX-8bit,gemma-4-26b-a4b-it-4bit,Ornith-1.0-35B-bf16"
    # Back-compat for older callers/UI fields; kept in sync with GENERATOR_MODEL below.
    local_model: str = "granite-4.0-h-small-MLX-8bit"
    mlx_thinking: str = "off"                         # off = no reasoning/thinking on answer path
    runtime_state_file: str = "./data/runtime_models.json"
    anthropic_api_key: str = ""
    answer_model: str = "claude-opus-4-8"             # optional <2% cloud tier, disabled by DEEP_PROVIDER=off

    # --- openai provider (the OpenAI API, or an OpenAI-compatible endpoint) ---
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    openai_base_url: str = ""                         # blank = api.openai.com; set for Azure/compatible

    # Legacy config keys retained so old .env files do not break settings parsing.
    # They are NOT used by the runtime; local inference is always through oMLX LOCAL_BASE_URL.
    gguf_model_path: str = ""
    gguf_n_ctx: int = 8192
    gguf_n_gpu_layers: int = -1
    mlx_model: str = ""

    # Deep/escalation is off by default. Never point this at a local reasoning model.
    deep_provider: str = "off"
    deep_model: str = "claude-opus-4-8"

    # --- Embeddings (oMLX endpoint) ---
    embedding_provider: str = "local"                # local == oMLX /v1/embeddings
    embedding_model: str = "bge-m3-mlx-fp16"
    local_embedding_model: str = "bge-m3-mlx-fp16"       # legacy env alias
    voyage_api_key: str = ""
    voyage_model: str = "voyage-law-2"
    cache_embeddings: bool = True                     # reuse embeddings of identical text (data/embed_cache.sqlite)
    # Optional role prefixes for asymmetric-search embedders (e.g. BGE v1.5). Default off unless configured.
    embedding_query_prefix: str = ""                 # prepended to queries only (input_type="query")
    embedding_passage_prefix: str = ""               # prepended to passages/doc chunks

    # --- Parent-document retrieval ---
    # Match a precise child window, but hand the model back the whole section it came from (better
    # context without losing citation granularity). Only affects sections long enough to be split.
    parent_retrieval: bool = True

    # --- Reranker (two-stage retrieval) ---
    use_reranker: bool = True
    reranker_model: str = "BAAI-bge-reranker-v2-m3-mlx-fp16"  # optional alternate if installed: Qwen3-Reranker-4B
    retrieve_before_rerank: int = 20
    keep_after_rerank: int = 6
    rerank_min_score: float = 0.35
    max_retrieval_retries: int = 2

    # --- Query expansion (recall) ---
    expand_queries: bool = True                      # spell out occupancy codes/acronyms before embedding

    # --- Hybrid retrieval (dense + BM25 lexical, reciprocal-rank fused) ---
    use_hybrid: bool = False                         # BM25 can be enabled later; oMLX rerank is primary
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
    verified_match_threshold: float = 0.82
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
    extract_tables: bool = False                    # optional table OCR is off by default

    # --- OCR (oMLX VLM/OCR models; ingest-time) ---
    use_ocr: bool = False                           # OCR image-only pages when the OCR bridge is enabled
    ocr_model: str = "olmOCR-2-7B-1025-8bit"
    ocr_table_model: str = "mlx-community/PaddleOCR-VL-8bit"
    ocr_table_enabled: bool = False
    ocr_dpi: int = 200
    ocr_cache_version: str = "omlx-md-v1"
    ingest_version: str = "ocr-bgem3-v1"
    index_version_suffix: str = ""  # set per run to create a new A/B collection, e.g. ocr-bgem3-v1
    ocr_language: str = "eng"                        # legacy tesseract path fallback; not used by oMLX

    # Generation tuning
    temperature: float = 0.1                         # low for code work

    @model_validator(mode="after")
    def _anchor_paths(self):
        """Resolve relative path settings against the project root (not the current dir), so
        `./code_books` and `./data` always point at the same place regardless of where you run."""
        # gguf_model_path is a real file path -> anchor it. mlx_model is intentionally NOT here:
        # it may be a HF repo id (e.g. "mlx-community/...") which must never be path-anchored.
        anchored = ("code_books_dir", "data_dir", "code_cycles_config", "chroma_dir", "feedback_db",
                    "runtime_state_file", "gguf_model_path")
        for field in anchored:
            raw = getattr(self, field)
            if not raw:            # empty (e.g. unset gguf path) — leave as-is, don't anchor "" to root
                continue
            val = Path(raw).expanduser()
            if not val.is_absolute():
                val = _ROOT / val
            setattr(self, field, str(val))

        # New GENERATOR_MODEL is the source of truth, but support legacy LOCAL_MODEL.
        if self.generator_model == type(self).model_fields["generator_model"].default and self.local_model:
            # If a legacy .env only sets LOCAL_MODEL, honor it; otherwise defaults are identical.
            self.generator_model = self.local_model
        self.local_model = self.generator_model

        # EMBEDDING_MODEL replaces LOCAL_EMBEDDING_MODEL; honor the old env when explicitly set.
        if self.embedding_model == type(self).model_fields["embedding_model"].default and self.local_embedding_model:
            self.embedding_model = self.local_embedding_model
        self.local_embedding_model = self.embedding_model
        return self

    @property
    def generator_model_list(self) -> list[str]:
        configured = [m.strip() for m in (self.generator_models or self.generator_model).split(",") if m.strip()]
        # The runtime picker has three explicitly supported local generators. Keep legacy .env
        # files usable while allowing a verified, user-loaded Ornith selection to answer queries.
        managed = ["granite-4.0-h-small-MLX-8bit", "gemma-4-26b-a4b-it-4bit", "Ornith-1.0-35B-bf16"]
        return list(dict.fromkeys([*configured, *managed]))

    def assert_allowed_generator(self, model: str | None) -> str:
        chosen = (model or self.generator_model).strip()
        allowed = self.generator_model_list
        if chosen not in allowed:
            raise ValueError(f"Unknown generator model: {chosen}. Allowed: {', '.join(allowed)}")
        return chosen


settings = Settings()
# A validated hot-swap survives process restarts without touching .env or reloading any model.
try:
    from .runtime_models import restore as _restore_runtime_model
    _restore_runtime_model()
except Exception:
    pass
