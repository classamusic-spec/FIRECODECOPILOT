# Local Models: oMLX Single-Endpoint Runtime

Fire Code CoPilot is standardized on **one local OpenAI-compatible oMLX endpoint**. The app backend never loads MLX/GGUF models in-process and does not rely on LM Studio. Generation, embeddings, reranking, and OCR all route through `LOCAL_BASE_URL`.

## Required runtime shape

```env
GENERATION_PROVIDER=local
LOCAL_BASE_URL=http://localhost:8010/v1
GENERATOR_MODEL=granite-4.0-h-small-MLX-8bit
GENERATOR_MODELS=granite-4.0-h-small-MLX-8bit,gemma-4-26b-a4b-it-4bit,Ornith-1.0-35B-bf16
MLX_THINKING=off

EMBEDDING_PROVIDER=local
EMBEDDING_MODEL=BAAI/bge-m3
USE_RERANKER=true
RERANKER_MODEL=BAAI/bge-reranker-v2-m3
# Optional stronger reranker:
# RERANKER_MODEL=Qwen/Qwen3-Reranker-4B

RETRIEVE_BEFORE_RERANK=20
KEEP_AFTER_RERANK=6
VALIDATE_CITATIONS=true

OCR_MODEL=mlx-community/olmOCR-2-7B-1025-8bit
OCR_TABLE_MODEL=mlx-community/PaddleOCR-VL-8bit
OCR_TABLE_ENABLED=false

DEEP_PROVIDER=off
```

## Roles

| Role | Model | Notes |
|---|---|---|
| Generator A | `mlx-community/gemma-4-26b-a4b-it-4bit` | Default grounded answer generator. Thinking/reasoning must stay off. |
| Generator B | `lmstudio-community/granite-4.0-h-small-MLX-4bit` | Co-equal runtime switch option. Uses the same endpoint; no server switch. |
| Embedding | `BAAI/bge-m3` | Called through `/v1/embeddings`; vectors are normalized before Chroma writes/queries. |
| Reranker | `BAAI/bge-reranker-v2-m3` | Called through `/v1/rerank`; keeps precision high after dense recall. |
| Optional reranker | `Qwen/Qwen3-Reranker-4B` | Heavier option if you want to trade latency for rerank quality. |
| Page OCR | `mlx-community/olmOCR-2-7B-1025-8bit` | Ingest-time OCR for scanned pages. |
| Table OCR | `mlx-community/PaddleOCR-VL-8bit` | Optional and **off by default** because most questions do not require table OCR. |

## Answer-path rules

1. **No reasoning-heavy local model is on the answer path.**
2. **Thinking is off.** `MLX_THINKING=off` adds no-think request hints and strips `<think>` / reasoning preambles as a safety net.
3. **No local deep tier.** `DEEP_PROVIDER=off` disables automatic and manual local escalation. If a cloud fallback is ever enabled for the hardest cases, it must be explicit and outside the ordinary cite-the-code path.
4. **Citation validator stays on.** `VALIDATE_CITATIONS=true` flags any section number that is not present in the retrieved source chunks.

## Runtime controls

The **Research engine** control in the app makes model allocation explicit:

1. Open the active-model button in the header and choose **Granite**, **Gemma 4**, or **Ornith 35B**.
2. Press **Load** and then the confirmation button. The backend starts managed oMLX if needed, verifies the exact model is available, warms only that model, and makes it the active generator for new questions.
3. Press **Stop local server** and confirm to run `omlx stop`, unloading every local model. The desktop wrapper performs the same stop on quit by default; set `FCC_STOP_OMLX_ON_EXIT=0` only when another local workload owns oMLX.

Selecting a card alone never loads weights. The API exposes the same lifecycle as `GET /runtime`, `POST /runtime/start`, `POST /runtime/load`, and `POST /runtime/stop`.

- `GET /models` — current local model stack and allowed generators.
- `GET /model-check` — live readiness check for the oMLX endpoint.
- `python -m app.llm --model-check` — CLI equivalent.

## oMLX readiness / model-check

Run this from `backend/` after starting oMLX:

```bash
.venv/bin/python -m app.llm --model-check
```

A passing check confirms:

- `LOCAL_BASE_URL` is reachable.
- Both generator IDs appear in `/v1/models`.
- `BAAI/bge-m3` and the configured reranker appear in `/v1/models`.
- `/v1/embeddings` responds for `BAAI/bge-m3`.
- `/v1/rerank` responds for the configured reranker.
- The active generator answers a tiny prompt with thinking disabled.

If it fails, fix oMLX first — do not fall back to LM Studio, in-process MLX, or a local reasoning model.

## Port layout

Recommended local layout:

| Service | URL |
|---|---|
| oMLX model runtime | `http://localhost:8010/v1` |
| Fire Code CoPilot backend API | `http://localhost:8001` |
| Vite frontend | `http://localhost:5173` |

The app backend and oMLX should not bind the same port. `scripts/launch.sh` defaults the app API to `8001` and passes `VITE_API_BASE=http://localhost:8001` to the frontend.

## Ingestion note

Changing the embedding model changes vector dimensionality. After switching to `BAAI/bge-m3`, re-ingest the code books so Chroma contains BGE-M3 vectors:

```bash
cd backend
.venv/bin/python -m app.ingest --force
```

Keep `OCR_TABLE_ENABLED=false` unless a task specifically requires table extraction.