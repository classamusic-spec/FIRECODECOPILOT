# Running Fire Code CoPilot Fully Local (Mac Studio, 512GB)

Your hardware (M3 Ultra, 512GB unified memory) can run a frontier-class open model *and*
the full retrieval stack locally — nothing but your own machine. This doc is the local
configuration. The architecture from `ARCHITECTURE.md` is unchanged; we just swap the
generation + embedding providers to local endpoints and ADD a reranker + a citation validator
(the two things that actually kill hallucinations).

## TL;DR recommended local stack (June 2026)

| Component | Pick | Why |
|---|---|---|
| **Generation LLM** | **GLM-5.2** (MLX, 512GB-tuned ~3.5bpw build) | Strongest open-weight model right now; 1M context fits your whole code corpus; MIT license; an MLX build is tuned specifically for a 512GB M3 Ultra |
| **Serving runtime** | **LM Studio** (GUI + OpenAI-compatible server) or **`mlx_lm.server`** (barebones) | MLX is the fastest path on Apple Silicon; both expose `/v1/chat/completions` |
| **Format** | **MLX**, not GGUF | MLX is faster on Apple Silicon for these big MoEs; the 512GB sweet-spot builds are MLX |
| **Embeddings** | **Qwen3-Embedding** (or **BGE-M3**) | Strong, multilingual, MLX-friendly, fully local |
| **Reranker (critical)** | **Qwen3-Reranker-4B** or **bge-reranker-v2-m3** | Cross-encoder rerank = 15–40% precision gain; the single biggest anti-hallucination lever |
| **Citation validator** | custom (this project) | Programmatically rejects any cited section not present in the retrieved text |
| **Vector store** | Chroma (unchanged) | Local, file-based |

### Why GLM-5.2 over the others you mentioned
- **GLM-5.2** — ~744–753B MoE, ~40B active, 1M-token context, MIT license. Independently
  ranked the top open-weight model (Artificial Analysis Intelligence Index ~51). A specific
  MLX build (`avlp12/GLM-5.2-Alis-MLX-Dynamic-3.5bpw` and the `pipenetwork/glm-52-mlx`
  collection) targets the "golden spot" for 512GB: best quality that still runs a **full 1M
  context** comfortably. This is the pick.
- **MiniMax M3** — capable (Intelligence Index ~44), 1M context, open weights, but GLM-5.2
  outranks it. Fine as a fallback.
- **Qwen 3.6** — the *open* sizes are small (27B dense, 35B-A3B MoE). Fast and excellent at
  instruction-following, but lower raw capability than GLM-5.2. **Best used as a fast
  "triage/draft" model**, and Qwen also gives you the embedding + reranker models above.
  (Note: Qwen 3.7-Max is API-only / proprietary — not a local option.)

> Privacy note: GLM/Qwen/MiniMax are Chinese models, but **self-hosting the open weights means
> nothing leaves your machine** — the "subject to Chinese law" concern only applies to their
> *cloud APIs*, not local weights. For keeping copyrighted code books local, self-hosted
> weights are ideal.

## The honest tradeoff (read this)

Even GLM-5.2 — the best open model — sits a notch below Claude Opus 4.8 on the hardest
reasoning, and quantization can introduce subtle errors. For *citation-critical* fire-code
work, you have two good options:

1. **Fully local** (max privacy): GLM-5.2 + reranker + the citation validator below. Very
   viable. The validator is what makes it trustworthy.
2. **Hybrid** (max reliability): local model for everyday/fast/private queries, with an
   optional one-click escalation to the Claude API for hard or ambiguous questions. The
   project already supports a `DEEP_MODEL` — point it at Claude and gate it behind a button.

Either way: **the reranker + citation validator matter more than the model choice.**

## Wiring it into the backend

The backend already abstracts providers. Extend the same pattern to generation.

### 1. Serve the model (pick one)
**LM Studio:** load the GLM-5.2 MLX build, start the local server (defaults to
`http://localhost:1234/v1`), OpenAI-compatible.

**mlx_lm.server:**
```bash
pip install mlx-lm           # plus the patched fork if the build's README requires it
mlx_lm.server --model pipenetwork/GLM-5.2-MLX-<your-build> \
  --kv-bits 8 --quantized-kv-start 4096 --port 1234
```

### 2. Point the app at it (`.env`)
```
GENERATION_PROVIDER=local           # "local" | "anthropic"
LOCAL_BASE_URL=http://localhost:1234/v1
LOCAL_MODEL=glm-5.2
# Optional hybrid escalation to Claude for hard questions:
DEEP_PROVIDER=anthropic
DEEP_MODEL=claude-opus-4-8
```

### 3. Generation call (OpenAI-compatible)
Use the `openai` Python client pointed at the local base URL — every local runtime above
speaks this dialect:
```python
from openai import OpenAI
client = OpenAI(base_url=settings.local_base_url, api_key="not-needed")
resp = client.chat.completions.create(
    model=settings.local_model,
    messages=[{"role": "system", "content": system_prompt},
              {"role": "user", "content": user_block}],
    temperature=0.1,          # low temp for code work
)
```
Keep `agent.py` provider-agnostic: an `anthropic` path and a `local` (OpenAI-compatible) path
behind one interface, selected by `GENERATION_PROVIDER`.

## Three ways to run an open-source model

`GENERATION_PROVIDER` now accepts four values: `local`, `llamacpp`, `mlx`, `anthropic`.
The `llamacpp` and `mlx` providers load a model file **directly in-process** (no server). Their
deps are optional and live in `backend/requirements-local-llm.txt` (NOT in the core install).

Check your configuration any time — this never needs the heavy deps and never runs inference:
```bash
cd backend && python -m app.llm --check
```

### (a) Via a server — `local` (LM Studio / Ollama / llama.cpp server) — *recommended, easiest*
Run any OpenAI-compatible server and point the app at it. Nothing extra to install (the core
`openai` client is already a dependency).
```bash
# pick ONE server:
#   LM Studio   -> load a model, click "Start Server" (defaults to :1234)
#   Ollama      -> `ollama serve` then `ollama run <model>`  (base url http://localhost:11434/v1)
#   llama.cpp   -> `llama-server -m model.gguf --port 1234`
```
```
GENERATION_PROVIDER=local
LOCAL_BASE_URL=http://localhost:1234/v1
LOCAL_MODEL=glm-5.2
```

### (b) A downloaded GGUF — `llamacpp` (cross-platform, CPU or GPU)
Loads a `.gguf` file directly with `llama-cpp-python` — no server process.

1. **Get a GGUF.** Download a quantized `.gguf` from Hugging Face (search the
   *"…-GGUF"* repos, e.g. `bartowski/...` or `Qwen/...-GGUF`). A `Q4_K_M` quant is a good
   size/quality balance. Save it somewhere like `backend/models/`.
2. **Install the runtime** (needs a C/C++ compiler; add GPU flags for acceleration):
   ```bash
   pip install llama-cpp-python                                              # CPU only
   CMAKE_ARGS="-DLLAMA_METAL=on"  pip install llama-cpp-python               # Apple Silicon (Metal)
   CMAKE_ARGS="-DLLAMA_CUBLAS=on" pip install llama-cpp-python               # NVIDIA (CUDA)
   ```
3. **Point the app at the file** (`.env`):
   ```
   GENERATION_PROVIDER=llamacpp
   GGUF_MODEL_PATH=./models/qwen2.5-7b-instruct-q4_k_m.gguf   # relative paths anchor to project root
   GGUF_N_CTX=8192                                            # context window
   GGUF_N_GPU_LAYERS=-1                                       # -1 = offload all to GPU; 0 = CPU only
   ```
The model loads once (cached for the process). `python -m app.llm --check` confirms the dep is
importable and the file exists.

### (c) MLX — `mlx` (Apple Silicon only, fastest on Mac)
Loads an MLX model directly with `mlx_lm` — no server.

1. **Install** (Apple Silicon only): `pip install mlx-lm`
2. **Pick a model** from the `mlx-community` org on Hugging Face (the id is downloaded on first
   use), or use a local path.
3. **Configure** (`.env`):
   ```
   GENERATION_PROVIDER=mlx
   MLX_MODEL=mlx-community/Qwen2.5-7B-Instruct-4bit   # HF repo id OR a local path
   ```
The model loads once and uses the tokenizer's chat template when available.

## The anti-hallucination pipeline (do all four)

1. **Two-stage retrieval.** Embed query → retrieve top ~20 (recall) → **cross-encoder
   rerank** → keep top **5–7** (precision). Add a `reranker.py` step between `retriever.py`
   and `agent.py`.
2. **Cap context to 5–7 chunks.** More chunks = "lost in the middle" = missed/garbled
   citations. Quality of chunks beats quantity.
3. **Hard grounding prompt.** Already in `AGENT_SYSTEM_PROMPT.md`: only cite sections present
   in the provided context; if it's not there, say so. Keep `temperature` low (≈0.1).
4. **Citation validator (the safety net).** After the model drafts an answer, programmatically
   check that **every cited section number actually appears in the retrieved chunks.** If a
   citation isn't found, strip/flag it and either re-retrieve or tell the marshal "couldn't
   verify this one." For fire code, this single check is worth more than any model upgrade —
   it makes fabricated citations structurally impossible to slip through.

## Suggested `requirements.txt` additions (local mode)
```
openai                 # talk to local OpenAI-compatible server
mlx-lm                 # if serving via mlx_lm.server
FlagEmbedding          # bge-reranker-v2-m3
# or use the Qwen3-Embedding / Qwen3-Reranker via sentence-transformers / MLX
```
