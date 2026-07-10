# CLAUDE.md — Fire Code CoPilot

> This file is read automatically by Claude Code. It is the source of truth for how to
> build this project. Read it fully, then read `docs/BUILD_PLAN.md` and work phase by phase.
> Do not skip the rules in this file. When in doubt, ask before assuming.

## What we are building

A **local-first, personal AI research assistant** for a certified Fire Marshal in the
**City of Hartford, Connecticut**. The user has purchased fire/building code books as PDFs
in a local folder. The app lets them ask plain-language questions ("when is a sprinkler
system required for an existing Group R-2?") and get an answer that:

1. Retrieves the relevant sections from *their* code books (RAG),
2. Respects Connecticut's amended/adopted versions over raw model-code text,
3. Cites the exact section and shows the retrieved source text for verification,
4. Asks clarifying follow-up questions when the answer depends on building specifics,
5. Improves over time from the marshal's feedback,
6. Knows the current adopted code cycle and flags when a new one is due.

This is a **decision-support tool, not an authority**. The human marshal is the AHJ
(Authority Having Jurisdiction). The app never issues binding determinations.

## Non-negotiable rules

These are hard constraints. Violating them defeats the purpose of the project.

### 1. Copyright containment (most important)
- The user's code book PDFs are **copyrighted** (ICC, NFPA, etc.). They are licensed for
  personal use only.
- **Never commit** code books, extracted text, embeddings, the vector store, or any file
  that reproduces substantial code text. `.gitignore` already excludes these — keep it that way.
- All code text stays **on the user's machine**. Default to local processing. The only data
  that may leave the machine is (a) the user's *question*, (b) small *retrieved snippets*
  sent to the Claude API to compose an answer, and (c) optional embedding calls — and even
  those can be switched to a fully local model via `EMBEDDING_PROVIDER=local`.
- If asked to add a "share" or "publish codes" feature, **stop and flag it** — that crosses
  from personal use into redistribution.

### 2. Citation honesty (safety-critical)
- The agent must **never fabricate a section number or quote**. Fire code errors have
  real-world safety and liability consequences.
- Every substantive claim must map to a retrieved chunk. If retrieval returns nothing
  relevant, the agent says so plainly ("I couldn't find this in your loaded code books")
  rather than guessing.
- Always surface the **source text and section citation** the answer is built on so the
  marshal can verify in one glance.

### 3. Edition / cycle correctness
- Answers are pinned to the **currently adopted Connecticut edition** (see
  `config/code_cycles.yaml`). The active editions are injected into the agent's system prompt.
- When a question touches a code that is mid-transition (a new cycle pending), the agent
  flags it.

### 4. Local-first & private by default
- No telemetry. No cloud database. Vector store (Chroma) and feedback DB (SQLite) live in
  `data/` on disk.
- Secrets only in `.env` (gitignored). Never hardcode keys.

## Tech stack (decided — don't re-litigate unless something blocks the build)

| Layer | Choice | Why |
|---|---|---|
| Backend | **Python + FastAPI** | Best PDF/RAG ecosystem; simple local server |
| Vector store | **ChromaDB** (file-based, local) | No server to run; lives in `data/` |
| PDF parsing | **PyMuPDF (fitz)** + pypdf fallback | Keeps layout/section structure |
| Embeddings | **Voyage `voyage-law-2`** (default) OR **local BGE-M3** | Legal-domain tuned; local option for full privacy |
| Generation | **Claude API** — `claude-sonnet-4-6` default, `claude-opus-4-8` for hard queries | Strong reasoning + citation discipline |
| Frontend | **React + Vite + Tailwind** | Clean, fast chat UI |
| Feedback/learning | **SQLite** + a "Verified Answers" Chroma collection | Compounding, retrievable confirmed knowledge |

Model strings, ports, and provider toggles come from `.env` (see `.env.example`). Read the
current model names from env — do not hardcode them in source.

## Where everything is specified

- `docs/PROJECT_SPEC.md` — goals, user stories, functional requirements, the learning loop.
- `docs/ARCHITECTURE.md` — components, data flow, chunking strategy, the amendment-layering
  approach, the code-cycle mechanism.
- `docs/AGENT_SYSTEM_PROMPT.md` — the fire-marshal agent prompt (use verbatim as the base).
- `docs/LOCAL_MODELS.md` — the oMLX single-endpoint local runtime: two switchable generators,
  BGE-M3 embeddings, reranker, OCR, thinking-off answers, and the citation validator.
- `docs/BUILD_PLAN.md` — the phased, ordered build steps. **Execute in order.**
- `docs/COPYRIGHT_AND_LICENSING.md` — the legal guardrails + the future monetization split.
- `config/code_cycles.example.yaml` — adopted editions + effective dates (user finalizes).

## How to proceed

1. Confirm the folder structure and create the recommended tree (see `docs/ARCHITECTURE.md`).
2. Build **Phase 1 (ingestion)** first and prove it works on one real code book before moving on.
3. After each phase, run it and show the user the result. Do not batch all phases blindly.
4. Keep functions small and well-commented; the user is technical but not a full-time dev.
5. Never weaken the copyright or citation rules to "simplify." Ask the user instead.
