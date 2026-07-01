# Fire Code CoPilot — Improvement Roadmap

> Audience: the product owner (technical). Every recommendation below is grounded in what the
> code does *today* (file + function cited). Nothing here weakens the two hard guardrails —
> copyright containment and citation honesty. Those are reiterated in §5.
>
> Scope note: the **local-model swap (GGUF/MLX)** is being added separately and is intentionally
> light here. **Hermes/MCP** exists (`backend/app/mcp_server.py`) but is explicitly out of scope
> per the owner — mentioned, not expanded.

---

## 0. Recently shipped ✅

Since this roadmap was written, the following have been implemented (tests in `backend/tests/`):

- **N1 — hierarchy-aware amendment merge** (`sections.relates`, `retriever._merge_amendments`): equal/ancestor/descendant matching, not exact-string.
- **N2 — quote-level citation validation** (`citations.py`): whole-token section match (kills the `903.2`⊂`903.2.8` false positive) + verbatim-quote grounding.
- **N3 — per-edition collections** (`ingest.py`, `retriever`, `/collections`): one Chroma collection per cycle via `books.yaml` `collection:`.
- **N4 — deterministic query expansion** (`query.py`): occupancy codes + code acronyms, appended before embedding.
- **N6 — pypdf fallback + OCR-needed flag** (`ingest._read_pdf`): scanned/image-only pages are detected and flagged (never OCR'd silently).
- **X1 — eval/regression harness** (`app/eval.py`, `eval/golden.yaml`): retrieval + amendment + citation-safety golden set (`python -m app.eval`), plus an **LLM-judge** tier (`--judge`).
- **X2 — hybrid BM25 + dense retrieval** (`lexical.py`, `retriever._fuse`): reciprocal-rank fusion so exact tokens (section numbers, "NFPA 13") can't be missed.
- **X3 — streaming responses** (`llm.chat_stream`, `agent.ask_stream`, `/ask/stream`, UI): token-by-token with post-stream citation validation.
- **X7 — review-queue UI** (`ReviewQueue.tsx`): consumes `/review-queue`.
- **Local-model swap** (GGUF/MLX) and the premium UI redesign also landed.

Still open below: OCR pre-pass (X4), structured tables (X5), threads/persistence (X6), verified-answer edit/dedupe (X8), model-vs-CT diff (X9), confidence surfacing (X10), export (L3), and the packaging items.

---

## 1. Executive summary (highest-leverage moves)

- **Per-edition collections are documented but not built.** `ingest.ingest()` writes every PDF
  into a single `settings.active_collection`; `retriever.retrieve_scored()` queries one
  collection. ARCHITECTURE §3.6 and the README both promise one-collection-per-edition for
  legacy queries — today legacy editions would *pollute* current-cycle answers. This is the
  biggest gap between docs and code. **(Now)**
- **Amendment merge is brittle: exact section-string equality.** `retriever._merge_amendments`
  matches base↔amendment only when `section` strings are byte-identical (`{"section":{"$in":…}}`).
  Real CT amendments cite ranges, sub-sections, and reformatted numbers — many overrides will
  silently not merge. This directly threatens the "CT version governs" rule. **(Now)**
- **Citation validation is presence-only, not quote-level.** `citations.validate` confirms a
  cited *section number* appears in the retrieved chunks; it does not check that the **quoted
  text** the model attributes to that section actually matches. A correct section number with a
  fabricated requirement passes today. **(Now)**
- **No query rewriting / expansion** despite ARCHITECTURE §4.1 and BUILD_PLAN Phase 2 calling
  for it. Occupancy abbreviations ("R-2", "Group A"), code acronyms, and synonyms are passed
  raw to the bi-encoder. Cheapest large win for recall. **(Now/Next)**
- **No streaming.** `llm.chat()` returns a full string; the UI shows a 3-dot spinner
  (`ChatMessage.LoadingDots`). On a local GLM-class model, time-to-first-token matters a lot for
  perceived speed. **(Next)**
- **No hybrid (BM25 + dense) retrieval.** Pure Chroma dense search. Code questions are full of
  exact tokens (section numbers, "Table 509", "NFPA 13") where lexical match beats embeddings.
  **(Next)**
- **No regression/eval harness.** PROJECT_SPEC sets a "~20 known questions, zero fabricated
  citations" acceptance bar; there is no golden set or runner. Every retrieval/prompt/model
  change is currently unguarded. **(Next)**
- **No conversation persistence and `/clarify` has no memory.** Chat history lives only in React
  state (`App.tsx` `turns`); `/clarify` re-runs retrieval from scratch and folds answers into a
  flat `building_context` string (`main.clarify`). User stories #4 (saved matters) and the v1.1
  "threads/history" item are unmet. **(Next/Later)**

---

## 2. Current-state assessment (per layer)

### Ingestion — `ingest.py`
**Does well:** hash-based skip of unchanged files (`_file_hash` + `ingest_state.json`); batched
embed+upsert (B=64) keeps memory flat; an excellent `--inspect` dry-run that reports section
counts, tables, amendment tags, and flags likely extraction problems; optional `books.yaml`
manifest for per-file `book`/`edition`/`is_amendment_doc`, with a filename heuristic fallback
(`_meta_for`).

**Concrete limitations:**
- **Text-only extraction.** `_read_pdf` calls `page.get_text("text")` — no OCR. A scanned or
  image-only code book yields empty/garbage chunks with no warning beyond `--inspect`'s preamble
  flag. PyMuPDF + `pypdf` are in `requirements.txt`, but `pypdf` is never actually used as a
  fallback.
- **Single collection, ignores edition.** Despite metadata carrying `edition`, everything lands
  in `settings.active_collection`. The per-edition-collection design is unimplemented.
- **No multi-column / reading-order handling.** `get_text("text")` linearizes a 2-column legal
  page top-to-bottom, interleaving columns. No `sort=True`, no block/column detection.
- **No incremental re-ingest by section** — a one-character edit to a PDF re-chunks and
  re-embeds the *whole* file (hash changes → full reprocess).
- **ID scheme can collide / churn.** IDs are `f"{book}|{page}|{i}"` where `i` is the per-file
  chunk index; re-chunking shifts `i`, leaving orphaned vectors from the prior run (upsert keys
  change, old keys aren't deleted).
- **No progress reporting** to the API caller — `/ingest` blocks until done and returns a summary
  with no streaming/progress.

### Chunking — `chunking.py`
**Does well:** genuinely thoughtful, well-tested section-aware splitter. Strips recurring
headers/footers and bare page numbers (`_strip_boilerplate`), uses **case-sensitivity** to avoid
inline cross-refs faking headings, keeps tables together with a look-ahead heuristic
(`_is_prose`), folds heading-only blocks forward as context (`flush`), tags amendment markers
(`AMENDMENT_MARKER`), and sub-splits only over-long sections (`_split_long`). Tests in
`test_chunking.py` lock the failure modes.

**Concrete limitations:**
- **Word-count chunking, not token-aware.** `TARGET_WORDS=450` "≈600 tokens" is a guess;
  `tiktoken` is a dependency but unused. Over/under-shoots the model's effective window.
- **Tables stored as flattened text.** A table is one text blob; rows/columns are not preserved
  structurally, so "what's the value in row X, column Y" questions degrade. No HTML/markdown
  table reconstruction (PyMuPDF `find_tables()` is available and unused).
- **Boilerplate stripping is frequency-based and can over-strip.** A short line repeated on ≥40%
  of pages is dropped — a legitimately repeated short heading or a recurring note could be lost.
- **Amendment detection is regex-on-text.** `AMENDMENT_MARKER` keys on "(Amd)/(Add)/(Del)" and
  phrases. Books that format amendments differently (margin bars, italics, "**" change marks)
  won't be tagged.
- **No figure/diagram handling** — images are simply absent from the text stream.

### Embeddings — `embeddings.py`
**Does well:** clean provider abstraction (`voyage` | `local`), lazy model load, MPS/CPU
auto-select, normalized embeddings.

**Concrete limitations:**
- **First-run download + load is heavy and silent.** BGE-M3 is multi-GB; first `embed()` call
  blocks while downloading/loading with no warm-up or progress. Same pattern hits the reranker.
- **No embedding cache.** Re-embedding identical text across runs/queries is not memoized
  (ARCHITECTURE §8 says "cache embeddings" — not done).
- **Voyage path ignores `input_type` for local.** `_embed_local` drops the `input_type`
  argument; BGE-M3 benefits from query/passage instruction prefixes that aren't applied.
- **No batching control for queries** (fine today; matters if multi-query expansion lands).

### Retrieval — `retriever.py` + `reranker.py`
**Does well:** two-stage retrieve→rerank is implemented and is the right anti-hallucination
lever; cross-encoder rerank (`reranker.rerank`) keeps top-K; Verified Answer Library is queried
and labeled (`_verified_matches`); amendment merge prepends controlling text; sources rendered
with provenance labels (`render_sources`); `retrieve_scored` exposes scores for deep-mode.

**Concrete limitations:**
- **No query rewriting/expansion.** ARCHITECTURE §4.1 ("expand abbreviations, add occupancy/
  section hints") is not implemented anywhere.
- **Dense-only.** No BM25/lexical channel; exact section-number and standard-name lookups rely
  entirely on embedding similarity.
- **Amendment merge = exact string match** (`_merge_amendments`, `{"section":{"$in":…}}`). No
  normalization, no range expansion, no parent/child section logic. A CT amendment to "903.2"
  won't merge onto a retrieved "903.2.8" and vice-versa.
- **Single collection only.** `retrieve_scored` reads `settings.active_collection`; cross-edition
  / legacy-building queries are impossible without manual `.env` swaps.
- **Amendment lookup scoped to the one collection** — if amendments ever live in a separate
  edition collection, the merge silently returns nothing (the bare `except: return chunks`).
- **Reranker fixed at top-K with no score floor passed downstream to the UI** — the score is used
  only for deep-mode escalation, never surfaced as a confidence signal.

### Agent / generation — `agent.py`, `llm.py`
**Does well:** clean two-mode design (answer/retrieve); deep-mode auto-escalation gated on
reranker score (`deep_escalate_below`); robust clarification parsing incl. fenced JSON
(`_parse_clarification`); citation validation wired in; system prompt assembled from the canonical
`AGENT_SYSTEM_PROMPT.md` with cycle-block injection.

**Concrete limitations:**
- **`llm.chat` only handles `local` and `anthropic`.** `settings` declares `llamacpp` and `mlx`
  providers (and `gguf_*` config), but `llm.chat` raises `ValueError` for them. (This is the
  separately-tracked local-model-swap work — flagged, not expanded here.)
- **No streaming** (full-string return; `max_tokens=2048` hard cap on the anthropic path).
- **Deep-mode escalation only re-runs generation, not retrieval.** BUILD_PLAN/PROMPT call for a
  "second retrieval pass with query rewriting" on hard questions; `ask()` reuses the same chunks
  and just swaps the model.
- **No multi-turn memory.** `ask()` is stateless; `/clarify` concatenates strings, so prior
  answers/threads don't inform the next turn.
- **Clarification is single-round in practice** — the model can ask once; there's no structured
  loop that remembers what was already asked vs. answered.

### Citations — `citations.py`
**Does well:** the single most important safety net; extracts citations with a broad regex,
normalizes shapes (`§903.2.8` == `Section 903.2.8` == `903.2.8`), verifies against section
metadata *or* literal text, and **surfaces** unverified citations rather than hiding them
(`annotate`).

**Concrete limitations:**
- **Presence-only grounding.** Verifies the *number* exists in context, not that the *claim/quote*
  matches the source. A real section number paired with a wrong requirement passes.
- **Substring false-positives.** `n in text_blob` can match "903.2" inside "903.2.8" or inside a
  cross-reference list, marking a citation "verified" when the actual governing section wasn't
  retrieved.
- **No NFPA-vs-section disambiguation in validation** beyond the regex; "NFPA 13" presence
  anywhere validates any "NFPA 13" claim.

### Cycles — `cycles.py`
**Does well:** loads finalized or `.example` YAML; builds the prompt block; computes a warn-window
reminder with graceful date parsing.

**Concrete limitations:**
- **Reminder is read-only and date-naive.** `recheck_interval_days` is in the YAML but unused;
  there's no "snooze/acknowledged" state, so the banner just persists.
- **No machine link between `code_cycles.yaml` editions and Chroma collections** — moving
  pending→active is a manual, error-prone, multi-file edit (`README` documents the 4-step dance).

### Learning loop — `feedback.py`
**Does well:** SQLite capture with sources + review-queue flagging; Verified Answer Library
promotion embeds the *question* (so similar questions match) and stores Q+answer; `/review-queue`
endpoint exists.

**Concrete limitations:**
- **No review-queue UI.** `/review-queue` is unconsumed by the frontend; gap detection (Level 3)
  has no surface.
- **Verified answers can't be edited, deduped, or deleted.** `promote_verified` upserts on
  `hash((question, corrected_answer))` — a slightly reworded correction creates a *new* entry;
  stale/wrong verified answers can't be removed and will keep surfacing labeled `[VERIFIED]`.
- **`governing_sections` is dropped by the UI.** `FeedbackBar.saveVerified` sends no
  `governing_sections` (comment even says so), so verified entries lose their section linkage.
- **No analytics.** No "which topics get 👎 most," no low-similarity logging into the queue
  (the `low_confidence` flag exists in schema but nothing in the ask-path sets it).

### Frontend — `frontend/src/`
**Does well:** clean, accessible chat shell; provider/deep toggles; collapsible building-context;
clarifying-chips flow wired to `/clarify`; expandable source citations with amendment/verified/
table badges; feedback + verify path; cycle banner; sensible API boundary (`lib/api.ts`) mirroring
the backend contract.

**Concrete limitations:**
- **No history persistence** (refresh loses the conversation).
- **No streaming render**, no markdown copy/export, no keyboard command palette.
- **No review-queue / matters / saved-address views.**
- **`escalated` shows "Deep mode" but score/confidence is never shown** to the marshal.

### Tests — `backend/tests/`
**Does well:** offline, fast, no network; covers chunking failure modes, citation extraction,
the agent's three behaviors (good/clarify/refuse), API wiring, and a *real-embedding* integration
test for amendment precedence + verified-answer surfacing (`test_retrieval_integration.py`).

**Concrete limitations:**
- **No golden Q→A regression set** (PROJECT_SPEC wants ~20).
- **No property tests** for chunking invariants (e.g., "no chunk loses its section number,"
  "tables never split").
- **No CI** configured.
- **Amendment merge is only tested for the exact-string-match happy path** — the brittleness
  above is unverified.

---

## 3. Prioritized roadmap

Effort: **S** ≤1 day · **M** a few days · **L** 1–2+ weeks.

### NOW — correctness & safety of what already exists

| # | Problem | Solution | Effort | Files |
|---|---|---|---|---|
| N1 | Amendment merge misses anything but exact section-string equality → "CT governs" silently fails | Normalize section numbers (strip trailing dots, case); expand parent↔child (amend "903.2" covers "903.2.x"); add a fallback text-match. Add tests for range/sub-section/parent merges | M | `retriever._merge_amendments`, `chunking._heading`, `test_retrieval_integration.py` |
| N2 | Citation validation is presence-only; a right section # + wrong requirement passes | Add **quote-level grounding**: when the answer quotes/paraphrases a requirement, verify a high token-overlap span exists in the cited chunk; tighten substring match to word-boundary/section-prefix-aware compare to kill "903.2" ⊂ "903.2.8" false positives | M | `citations.validate`, `citations._normalize`, `test_citations.py` |
| N3 | Per-edition collections promised, not built; legacy editions pollute current answers | Make `ingest` write to a collection derived from `edition` (or manifest); have `retrieve` default to active edition with an optional `edition`/`collection` param already present in the signature; merge amendments within edition | M | `ingest.ingest`, `retriever.retrieve_scored`, `settings`, `main.ask` |
| N4 | Query passed raw to bi-encoder; abbreviations/acronyms hurt recall | Add a **deterministic** query-expansion pass (occupancy abbrev table R-2→"Group R-2 residential", IFC/IBC/NFPA expansions, "sprinkler"→"automatic sprinkler system"). Keep it rule-based first (no LLM) so it's testable and offline | S/M | new `retriever` helper or `query.py`, `retrieve_scored` |
| N5 | First-run model downloads block silently; cold start looks like a hang | Add a `/warm` route + CLI warm-up that pre-loads embedder + reranker; surface load state in `/health`; print a one-time "downloading model…" notice | S | `embeddings`, `reranker`, `main.health`, `cli` |
| N6 | `pypdf` listed as fallback but never used; scanned books fail silently | Wire a real fallback: if PyMuPDF yields near-empty text for a page, try `pypdf`; if still empty, flag the book as "needs OCR" in the ingest summary | S | `ingest._read_pdf`, `ingest.ingest` summary |

### NEXT — quality, UX, and guardrails for change

| # | Problem | Solution | Effort | Files |
|---|---|---|---|---|
| X1 | No regression/eval harness; every change is unguarded vs. the ~20-question bar | Add `eval/` golden set (`question, expected_sections, must_refuse?`) + a runner that asserts zero fabricated citations and correct governing sections; runnable offline against a seeded test index | M | new `backend/eval/`, reuse `test_retrieval_integration` fixtures |
| X2 | No hybrid search; exact tokens (section #s, "Table 509", "NFPA 13") rely on embeddings | Add BM25 (e.g. `rank_bm25` over chunk text) as a second channel; reciprocal-rank-fuse with dense before rerank | M | `retriever`, `requirements.txt` |
| X3 | No streaming; local model TTFT feels slow | Stream tokens: SSE/`StreamingResponse` from `/ask`; `llm` yields deltas; UI renders progressively. **Validate citations after stream completes** (don't stream past the validator) | M | `llm.chat`→`stream`, `agent.ask`, `main.ask`, `App.tsx`, `ChatMessage`, `lib/api` |
| X4 | OCR for scanned/image code books | Optional `ocrmypdf`/`tesseract` pre-pass during ingest, triggered when a page has images and little text; cache OCR output beside the index | M | `ingest`, `requirements.txt`, `docs/INSTALL_MAC.md` |
| X5 | Tables flattened; figure/table questions degrade | Use PyMuPDF `find_tables()` to emit markdown/HTML tables as their own chunks (tagged `is_table`); keep current flatten as fallback | M | `chunking`, `ingest` |
| X6 | No conversation threads/history; `/clarify` is memoryless | Persist threads to SQLite (`threads`, `messages`); thread the clarification state so the agent remembers what was asked/answered; load history on the next turn | M/L | new `threads.py`, `feedback` DB, `agent`, `main`, `App.tsx` |
| X7 | Review queue has no UI; gaps invisible | Build a `/review` view consuming `/review-queue`; set `low_confidence=True` in the ask-path when top rerank score < floor so low-confidence answers auto-enter the queue | M | `agent.ask`→feedback hook, `main`, new `ReviewQueue.tsx` |
| X8 | Verified answers can't be edited/deduped/deleted; `governing_sections` lost | Stable IDs by normalized question; add `/verify` edit+delete; pass `governing_sections` from the UI; near-dup detection on promote | S/M | `feedback.promote_verified`, `main`, `FeedbackBar` |
| X9 | "Show your work" diff of model-code vs CT amendment requested but absent | When both base and controlling-amendment chunks are retrieved for a section, render a side-by-side diff in the source panel | M | `retriever` (pair them), `SourceCitation`/new `AmendmentDiff.tsx` |
| X10 | No confidence surfacing | Pass top rerank score through `AgentResult`; show a calibrated low/med/high chip; tie into the unverified-citation banner | S | `agent`, `models`/`api`, `ChatMessage` |
| X11 | Cross-edition handling absent | Add an edition selector in the UI; query active + (optional) prior edition; label cross-edition results and warn on mismatch (prompt already instructs "don't blend editions") | M | `retriever`, `main`, `App.tsx` |
| X12 | Deep-mode doesn't re-retrieve | On escalation, run a query-rewrite + second retrieval pass before the stronger model (as PROMPT specifies) | S/M | `agent.ask` |

### LATER — packaging, scale, and the compounding loop

| # | Problem | Solution | Effort | Files |
|---|---|---|---|---|
| L1 | Three-process startup (model server + uvicorn + vite) is a lot for one marshal | One-command launcher script (and/or a `Makefile`/`justfile`) that warms models, starts API + frontend, opens the browser; health/setup wizard that checks books, `.env`, model server reachability | M | new `scripts/launch.*`, `cli` |
| L2 | Not a desktop app | Wrap in **Tauri** (smaller than Electron, fits the local-first/private ethos) so the marshal gets an installable app with the backend embedded | L | new `desktop/` |
| L3 | Export answer + citations for the file | "Export to PDF/notes" of answer + quoted sources + edition/date stamp | S/M | new `export.py` or client-side, `ChatMessage` |
| L4 | Saved "matters" by address/inspection | Group threads under a matter (address, permit #); persist + list | M | `threads.py`, new UI |
| L5 | Books manifest editor + per-edition collection management UI | UI to edit `books.yaml`, see collections, trigger per-edition (re)ingest with progress | M | `main` (manifest CRUD + progress), new UI |
| L6 | Parent-document / sentence-window retrieval for better precision-with-context | Index small windows but return the parent section to the model; reduces "lost in the middle" while keeping citation granularity | M | `chunking`, `retriever` |
| L7 | Citation-span highlighting in the answer | Link each in-answer citation to the exact retrieved chunk/offset; click to scroll-and-highlight the source | M | `agent` (span map), `ChatMessage`, `SourceCitation` |
| L8 | Embedding cache / batching / smaller-model option | Content-hash embedding cache on disk; expose a smaller embedder/reranker profile for lower-RAM machines; document GPU/Metal vs CPU tradeoffs | S/M | `embeddings`, `reranker`, `docs/LOCAL_MODELS.md` |
| L9 | Property tests + CI | Hypothesis property tests for chunking invariants; GitHub Actions running the offline suite + eval set | S/M | `tests/`, `.github/workflows/` |

### Hermes / MCP (out of scope — noted only)
`backend/app/mcp_server.py` exposes `fire_code_lookup` / `fire_code_cycle_status` and is wired
into the same agent path, so retrieval/eval/citation improvements above flow to it for free. No
dedicated work planned per the owner's direction.

---

## 4. Quick wins (<1 day each, high impact)

1. **Fix the substring false-positive in citation validation** — make `n in text_blob` and the
   section-metadata compare word-boundary/prefix-aware so "903.2" doesn't validate against
   "903.2.8". (`citations.validate`) — *safety win.*
2. **Deterministic query expansion table** (occupancy abbreviations + IFC/IBC/NFPA + a few
   synonyms) applied before embedding. Pure-function, easy to test. (N4)
3. **Model warm-up route + CLI command** so first query isn't a silent multi-GB hang. (N5)
4. **Wire the `pypdf` fallback and an OCR-needed flag** so scanned books don't fail silently. (N6)
5. **Pass `governing_sections` from `FeedbackBar.saveVerified`** so verified answers keep their
   section linkage. (one-line-ish UI fix)
6. **Set `low_confidence=True` in the ask-path** when the top rerank score is below the deep
   floor, so weak answers auto-populate the existing review queue. (`agent.ask` → feedback)
7. **Apply BGE query/passage instruction prefixes** in `_embed_local` (honor `input_type`) — a
   free retrieval-quality bump on the default local embedder.
8. **Surface the rerank confidence** already computed in `retrieve_scored` into the response and
   UI banner.

---

## 5. Risks & non-goals (guardrails any new feature MUST preserve)

These are **hard constraints** from `CLAUDE.md` and `PROJECT_SPEC.md`. Every item above is
designed to respect them; call out any future feature that would cross a line.

- **Copyright containment.** Code books, extracted text, embeddings, the Chroma store, and OCR
  output are copyrighted and **must never be committed**. New ingest/OCR/cache features must
  write only under gitignored `data/` (and any OCR cache must be gitignored too). Do **not** add
  any "share / publish / export the codes" capability — exporting *one answer + the snippet it
  cites* is fine (§L3); exporting the corpus is redistribution. Containment is checked by
  `scripts/check_containment.sh`; keep it green.
- **Citation honesty.** Never fabricate a section number or quote. The citation validator
  (`citations.py`) is the safety net — **strengthen it, never relax it** (quote-level grounding
  in N2 is the next step, not optional bypasses). Streaming (X3) must still run validation before
  an answer is treated as final. If retrieval returns nothing relevant, the agent says so
  ("couldn't find this in your loaded code books"), as the prompt already mandates.
- **CT amendment governs.** The Connecticut adopted/amended text always overrides base model
  text. The amendment-merge fixes (N1) and the model-vs-CT diff (X9) must make this *more*
  reliable; never present base-model text as controlling when a CT amendment exists.
- **Edition correctness.** Answers are pinned to the active adopted edition. Per-edition
  collections (N3) and cross-edition UI (X11) must not "blend editions" — label and warn on
  mismatch.
- **Local-first / private.** No telemetry, no cloud DB. The only data that may leave the machine
  is the question + small retrieved snippets (+ optional embedding calls). New analytics (review
  queue, gap stats) stay in local SQLite. Any model escalation to Claude remains off by default
  and opt-in (`DEEP_PROVIDER`).
- **Decision support, not authority.** The marshal is the AHJ. Keep the "verify before relying"
  framing; never present output as a binding determination.

**Non-goals (unchanged):** public code library, plan-check/drawing analysis, model fine-tuning on
code text. Improvement comes from better retrieval + curated memory, not new weights.
