# Install & Run on Mac Studio (fully local, no Hermes)

This is the complete standalone setup: your local model does the answering, retrieval runs on
your machine, and it reads the code books from a folder on your Desktop. Nothing leaves the Mac.

## How it works (the whole loop in plain English)

```
   Your code books (Desktop folder, PDFs)
            │   one-time:  python -m app.ingest
            ▼
   Section-aware chunks ─ local embeddings ─▶ Chroma index (in ./data, on disk)
            ▲
            │  every question:
   You type a question (CLI or API)
            │
            ▼
   embed question (local) ─▶ Chroma search (top 20) ─▶ reranker (keep top 6)
            │
            ▼
   build a prompt with ONLY those 6 source passages
            │
            ▼
   your LOCAL model (GLM-5.2 / Qwen / MiniMax via LM Studio) drafts the answer
            │
            ▼
   citation validator checks every cited § is really in the sources
            │
            ▼
   answer + book/section/page citations  ──▶ you
```

Three independent pieces run on your Mac: (1) a **model server** (LM Studio) serving your LLM,
(2) this **app** (retrieval + reranker + validator), (3) your **code books** folder. The app
talks to the model over a local URL and reads the books from the folder you point it at.

## Step 1 — Prerequisites
- **Python 3.11+**: `python3 --version` (install via [python.org] or `brew install python` if needed).
- **A local model server.** Easiest is **LM Studio** (GUI). Download it, then in the Discover
  tab grab an **MLX** build of your model:
  - `GLM-5.2` (the 512GB-tuned MLX build — best quality), or
  - `Qwen3.6` (smaller/faster), or `MiniMax-M3`.
  - Load the model, open the **Developer / Local Server** tab, **Start Server**. It serves an
    OpenAI-compatible API at `http://localhost:1234/v1`. Note the model's id (e.g. `glm-5.2`).
  - (Alternative, no GUI: `pip install mlx-lm` then `mlx_lm.server --model <repo> --port 1234`.)

## Step 2 — Get the project + install deps
```bash
cd ~/Desktop                      # or wherever you keep projects
# put the Fire-Code-CoPilot folder here (your repo / the starter kit)
cd Fire-Code-CoPilot/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Step 3 — Point it at your model and your code books
```bash
cd ..                             # project root
cp .env.example .env
```
Open `.env` and set:
```
GENERATION_PROVIDER=local
LOCAL_BASE_URL=http://localhost:1234/v1   # LM Studio default (Ollama is :11434)
LOCAL_MODEL=glm-5.2                        # the model id shown in your server

EMBEDDING_PROVIDER=local                   # embeddings stay on your machine
LOCAL_EMBEDDING_MODEL=BAAI/bge-m3

USE_RERANKER=true
RERANKER_MODEL=BAAI/bge-reranker-v2-m3
VALIDATE_CITATIONS=true

# 👉 Point this at your code books folder on the Desktop:
CODE_BOOKS_DIR=/Users/YOURNAME/Desktop/CodeBooks
```
Replace `YOURNAME` and the folder name with your actual path. The books stay there; the app
only reads them.

### Optional but recommended: label your books
Create `CodeBooks/books.yaml` so editions and Connecticut amendments are tagged correctly:
```yaml
"2022_CSFSC.pdf":        { book: "CSFSC", edition: "2022", is_amendment_doc: false }
"CT_Amendments_IFC.pdf": { book: "CSFSC", edition: "2022", is_amendment_doc: true }
"NFPA_13_2022.pdf":      { book: "NFPA 13", edition: "2022", is_amendment_doc: false }
```
Without it, the app infers book/edition from filenames and guesses amendment docs by name.

## Step 4 — Build the index (one time, and whenever books change)
```bash
cd backend && source .venv/bin/activate
python -m app.ingest
```
You'll see each book indexed with a chunk count. The first run also downloads the small local
embedding + reranker models (a few hundred MB, one time). The index is written to `./data`.

## Step 5 — Ask questions
**Easiest — terminal chat (no server, no frontend):**
```bash
python -m app.cli
```
```
› sprinkler requirement for an existing 3-story apartment building
```
It will ask for any decisive missing facts (occupancy, sprinklered, etc.), then return a cited
answer. Type `cycle` to see the adopted editions, `quit` to exit.

**Or run the API** (for a frontend or scripts later):
```bash
uvicorn app.main:app --reload --port 8000
curl -s localhost:8000/ask -H 'Content-Type: application/json' \
  -d '{"question":"egress width for 300 occupants, sprinklered","building_context":"Group A-2, new"}'
```

## Swapping models (GLM ↔ Qwen ↔ MiniMax)
1. In LM Studio, load the other model and Start Server.
2. Set `LOCAL_MODEL` in `.env` to its id (or, if the server runs one model, the app can
   auto-use it).
3. Restart the CLI/API. No re-ingest needed — embeddings are independent of the chat model.

## Daily use
- Model server (LM Studio) running → `python -m app.cli` → ask away.
- New code cycle / new books? Drop PDFs in the folder, update `books.yaml`, re-run
  `python -m app.ingest`.

## Troubleshooting
- **"Connection refused" / errors on ask** → the model server isn't running, or `LOCAL_BASE_URL`
  is wrong. Confirm LM Studio's server is started and the port matches.
- **"collection does not exist"** → run `python -m app.ingest` first.
- **Slow first answer** → the local embedding/reranker models load on first use; subsequent
  questions are fast. Big-context prompts to a large model also take time to "prefill."
- **Citations show ⚠️ unverified** → working as intended: the model cited a section not in the
  retrieved text. Re-ask more specifically, or confirm the book is ingested.
- **Wrong edition in answers** → check `ACTIVE_COLLECTION` and your `books.yaml` editions.
```
