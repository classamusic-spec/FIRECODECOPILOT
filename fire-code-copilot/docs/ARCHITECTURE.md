# Architecture — Fire Code CoPilot

## 1. High-level picture

```
┌──────────────────────────────────────────────────────────────────────┐
│  YOUR MACHINE (everything local except small API calls)                │
│                                                                        │
│  code_books/*.pdf ──► Ingestion ──► Chunks ──► Embeddings ──► Chroma   │
│   (copyrighted,         (parse,      (section-   (Voyage law /  (vector │
│    gitignored)          chunk)        aware)      local BGE)     store) │
│                                                          │             │
│   React chat UI ◄──► FastAPI ◄──► Retriever ◄────────────┘             │
│        ▲                │              │                               │
│        │                │              ▼                               │
│        │                │        Retrieved excerpts + active editions  │
│        │                │              │                               │
│        │                ▼              ▼                               │
│        │          Agent (Claude API: Sonnet default / Opus for hard)   │
│        │                │                                              │
│        └──── answer + citations + follow-ups ◄──────┘                  │
│                         │                                              │
│        👍/👎 + corrections ──► SQLite feedback  ──► Verified Answers    │
│                                                     (own Chroma coll.) │
└──────────────────────────────────────────────────────────────────────┘
        Only data leaving the machine: your question, small retrieved
        snippets sent to Claude, and (optional) embedding calls.
```

## 2. Recommended file tree

```
fire-code-copilot/
├── CLAUDE.md
├── README.md
├── .gitignore
├── .env.example  ->  .env
├── code_books/                      # PDFs (gitignored)
├── data/                            # chroma/, feedback.sqlite (gitignored)
├── config/
│   └── code_cycles.yaml
├── backend/
│   ├── requirements.txt
│   └── app/
│       ├── main.py                  # FastAPI app + routes
│       ├── settings.py              # loads .env (pydantic-settings)
│       ├── ingest.py                # PDF -> chunks -> embeddings -> Chroma
│       ├── chunking.py              # section-aware splitter
│       ├── embeddings.py            # provider abstraction (voyage | local)
│       ├── retriever.py             # query -> top-k chunks (+ amendment merge)
│       ├── agent.py                 # builds prompt, calls Claude, formats answer
│       ├── prompt.py                # assembles system prompt from template + config
│       ├── cycles.py                # reads code_cycles.yaml, computes reminders
│       ├── feedback.py              # SQLite + Verified Answer Library writes
│       └── models.py                # pydantic request/response schemas
└── frontend/
    ├── package.json
    └── src/
        ├── App.tsx                  # chat shell
        ├── components/
        │   ├── ChatMessage.tsx      # renders answer + citations (expandable source)
        │   ├── SourceCitation.tsx   # section badge + quoted source text
        │   ├── FeedbackBar.tsx      # 👍/👎 + "correct this" capture
        │   ├── ClarifyingChips.tsx  # quick-pick chips for occupancy/type/etc.
        │   └── CycleBanner.tsx      # "new code cycle due" warning
        └── lib/api.ts               # talks to FastAPI
```

## 3. Ingestion & chunking (the part that makes or breaks accuracy)

Codes are highly structured (numbered sections, tables, cross-refs). Naive fixed-size
chunking destroys that and produces wrong citations. Strategy:

1. **Extract with PyMuPDF**, preserving page numbers and as much layout as possible.
2. **Detect section boundaries** with a regex pass for code numbering
   (e.g., `^\d{3,4}(\.\d+)*\b`, `^NFPA \d+`, `Table \d`, chapter/section headers).
   Chunk on section boundaries, not arbitrary character counts.
3. **Carry metadata on every chunk:** `book_key`, `title`, `ct_edition`, `section`,
   `page`, `is_amendment` (Connecticut amendment vs. base model text), `is_table`.
4. **Target ~600 tokens/chunk with ~80 overlap**, but never split mid-section if a section
   is small; merge tiny sections with their parent heading for context.
5. **Tag Connecticut amendments.** CT amendment docs mark changes as (Amd)/(Add)/(Del).
   Detect these and set `is_amendment=true` + capture the affected section number so the
   retriever can merge/override base text. This directly serves the "CT version governs" rule.
6. Store one Chroma collection per **edition** (so legacy editions stay queryable for
   existing-building questions without polluting current-cycle answers).

## 4. Retrieval (with amendment merge)

1. Optionally **rewrite the query** (expand abbreviations, add occupancy/section hints).
2. Embed query (`input_type="query"`), search the **active edition** collection for top-k.
3. **Amendment merge:** for any retrieved section that has a matching CT amendment chunk,
   pull the amendment in and mark it as controlling.
4. Also search the **Verified Answer Library** collection; if a high-similarity verified
   answer exists, include it (labeled) — this is how the system "remembers" confirmed rulings.
5. Pass the merged, de-duplicated, source-labeled excerpts to the agent.

## 5. The learning loop (honest about what it is)

This system "gets better over time" through **retrieval improvement + curated memory**, not
model fine-tuning. That's deliberate: you never want a possibly-wrong interpretation baked
into model weights, and re-training is unnecessary for this use case.

**Level 1 — Feedback capture.** Every answer has 👍/👎 and an optional "correct this" box.
Stored in SQLite with the question, retrieved sources, answer, and the marshal's note.

**Level 2 — Verified Answer Library (the compounding part).** When the marshal confirms or
corrects an answer, save `{question, corrected_answer, governing_sections}` as a *verified
interpretation*. Embed it into its own Chroma collection. Future similar questions retrieve
it (labeled `[VERIFIED]`), so confirmed knowledge accumulates and the assistant gets sharper
on the questions you actually ask.

**Level 3 — Gap detection.** Log queries with low retrieval similarity or a 👎 to a review
queue. Periodically the marshal reviews: was the right section missing from the books? Was
chunking bad for that area? Add a verified answer or re-ingest.

**Level 4 — Regression guard (optional, later).** Keep a small eval set of known Q→A pairs.
Re-run it after each code-cycle update or prompt change to catch regressions.

**Explicitly NOT doing:** fine-tuning the model on code text (impractical, copyright-risky,
and worse than RAG for citation accuracy).

## 6. Code-cycle awareness

- `cycles.py` loads `config/code_cycles.yaml` and:
  - builds the `ACTIVE_CODE_CYCLE_BLOCK` injected into the agent prompt,
  - computes whether a reminder should fire (today vs. `expected_effective_date`,
    `warn_days_before_expected`, `recheck_interval_days`),
  - exposes a `/cycle-status` endpoint the UI's `CycleBanner` reads.
- When a new cycle lands: drop new books in `code_books/`, update the YAML (move
  `pending_cycle` → `active_cycle`), re-run `python -m app.ingest`. Old edition stays indexed
  for legacy questions.

## 7. API surface (FastAPI)

| Method | Route | Purpose |
|---|---|---|
| POST | `/ask` | `{question, context?}` → answer + citations + follow-ups + needs_clarification |
| POST | `/clarify` | continue a thread after the marshal answers clarifying questions |
| POST | `/feedback` | 👍/👎 + optional correction → SQLite |
| POST | `/verify` | promote a corrected answer into the Verified Answer Library |
| POST | `/ingest` | (re)index `code_books/` (or run via CLI) |
| GET | `/cycle-status` | reminder banner data |
| GET | `/health` | sanity check |

## 8. Privacy & cost posture

- **Default:** Voyage embeddings (small per-token cost) + Claude generation. Question + small
  snippets leave the machine; full books never do.
- **Max privacy:** set `EMBEDDING_PROVIDER=local` (BGE-M3 via sentence-transformers/Ollama).
  Then only the question + snippets reach Claude. For *fully* offline, swap the generation
  call for a local model later — but expect lower citation accuracy.
- Cache embeddings; only re-embed changed/new books.
