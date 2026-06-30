# Fire Code CoPilot 🔥📖

A **personal AI research assistant** for fire code work in the **City of Hartford, CT**.
Ask it questions in plain language instead of digging through code books.

> ⚠️ **Personal-use tool.** Your code books are copyrighted. This app keeps them on your
> machine and never publishes or redistributes them. It is a research aid — **you** remain
> the Authority Having Jurisdiction. Always verify against the official adopted code before
> making a determination. See `docs/COPYRIGHT_AND_LICENSING.md`.

## What it does

- 📚 Indexes the code books in your local `code_books/` folder (ICC I-Codes, NFPA, and the
  Connecticut amendments).
- 💬 Answers questions like *"Sprinkler requirements for an existing 3-story Group R-2?"*
- 🧭 Asks the right follow-up questions (occupancy, new vs. existing, construction type,
  height/area, sprinkler status) before committing to an answer.
- 🔖 Cites the exact section and shows you the source text so you can verify instantly.
- 🇨🇹 Prioritizes Connecticut's **adopted/amended** versions over raw model-code text.
- 📈 Learns from your 👍/👎 and corrections — confirmed answers improve future ones.
- 🗓️ Tracks the adopted code cycle and warns you when a new one (e.g., the 2026 CT codes)
  is due so you can update your books.

## Quickstart

```bash
# 1. Put your code book PDFs here (this folder is gitignored — never committed):
#    code_books/
#    (Optional: describe each book in code_books/books.yaml — see books.yaml.example.)

# 2. Backend
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp ../.env.example ../.env        # then adjust providers/keys (works fully local by default)

# 2a. Look before you index — dry-run chunking on your real books and eyeball it:
python -m app.ingest --inspect    # # chunks, sections, tables, amendment tags, no writes
python -m app.ingest              # then index for real (Phase 1)
uvicorn app.main:app --reload     # start the API

# 3. Frontend
cd ../frontend
npm install
cp .env.example .env              # VITE_API_BASE (defaults to http://localhost:8000)
npm run dev                       # open the chat UI
```

**No books yet? Smoke-test the whole pipeline** with synthetic, structurally-realistic
fire-code PDFs (original text — not copyrighted):

```bash
python scripts/make_sample_pdf.py   # writes SAMPLE_*.pdf into code_books/ (gitignored)
cd backend && python -m app.ingest --inspect && python -m app.ingest
python -m pytest                    # 21 offline tests: chunking, citations, agent, retrieval, cycles
```

> **Tuning to your books:** `--inspect` is how you confirm section detection matches your PDFs.
> If it flags *"many (preamble) chunks → section regex may not match this book's numbering,"*
> adjust `SECTION_HEADING` / `SECTION_KEYWORD` in `backend/app/chunking.py` to your code's
> numbering, then re-inspect. The defaults are tuned to ICC I-Code / NFPA conventions.

## When a new code cycle arrives

1. Drop the new edition's PDFs (and the Connecticut amendment document) into `code_books/`.
2. In `config/code_cycles.yaml`, move `pending_cycle` → `active_cycle` and set the new
   `pending_cycle` (verify dates with CT DAS). Point `ACTIVE_COLLECTION` in `.env` at the new
   edition (one Chroma collection per edition keeps legacy editions queryable).
3. Re-run `python -m app.ingest`. The old edition stays indexed for existing-building questions.
4. Confirm with `bash scripts/check_containment.sh` that nothing copyrighted got staged.

## Project layout

```
fire-code-copilot/
├── CLAUDE.md                 # Build instructions for Claude Code (read first)
├── README.md                 # You are here
├── .gitignore                # Keeps copyrighted material OUT of git
├── .env.example              # Copy to .env and fill in
├── code_books/               # YOUR PDFs go here (gitignored, never committed)
├── data/                     # Vector store + feedback DB (gitignored)
├── config/
│   └── code_cycles.yaml      # Adopted CT editions + effective dates
├── backend/                  # FastAPI + RAG
├── frontend/                 # React + Vite chat UI
└── docs/                     # Full spec — see below
```

## The docs

| File | What's in it |
|---|---|
| `docs/BUILD_PLAN.md` | The ordered, phased build steps |
| `docs/ARCHITECTURE.md` | How it all fits together |
| `docs/PROJECT_SPEC.md` | Requirements + the learning loop |
| `docs/AGENT_SYSTEM_PROMPT.md` | The fire-marshal agent's brain |
| `docs/COPYRIGHT_AND_LICENSING.md` | Legal guardrails + monetization path |
