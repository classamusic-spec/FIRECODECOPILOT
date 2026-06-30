# Build Plan — Fire Code CoPilot

Execute in order. **Finish and verify each phase before starting the next.** After each
phase, run it and show the user the result. Don't build everything blind.

---

## Phase 0 — Scaffolding (30 min)
- [ ] Create the file tree from `ARCHITECTURE.md §2`.
- [ ] `backend/app/settings.py` loads `.env` via pydantic-settings (model names, keys, dirs,
      retrieval params). Never hardcode model strings — read from env.
- [ ] Confirm `.gitignore` excludes `code_books/`, `data/`, `*.pdf`, `.env`. **Verify with
      `git status` that nothing copyrighted is trackable.**
- [ ] Stub `/health` endpoint; confirm the server runs.

**Checkpoint:** `uvicorn app.main:app --reload` serves `/health`.

---

## Phase 1 — Ingestion (the foundation; get this right)
- [ ] `embeddings.py`: provider abstraction with `embed(texts, input_type)` supporting
      `voyage` and `local`. Read provider/model from settings.
- [ ] `chunking.py`: section-aware splitter per `ARCHITECTURE.md §3` (regex section detection,
      metadata, table handling, CT amendment tagging).
- [ ] `ingest.py`: walk `code_books/`, extract (PyMuPDF), chunk, embed, write to Chroma with
      one collection per edition. Skip unchanged files (hash cache).
- [ ] CLI: `python -m app.ingest`.
- [ ] **Test on ONE real code book first.** Print: # chunks, sample chunk + metadata,
      confirm section numbers and pages look right. Fix chunking before ingesting everything.

**Checkpoint:** the user's books are indexed; a quick similarity search returns sensible,
correctly-cited chunks.

---

## Phase 2 — Retrieval + amendment merge
- [ ] `retriever.py`: query rewrite (optional) → embed query → top-k from active edition →
      amendment merge (pull controlling CT amendment for any matched base section) →
      also query Verified Answer Library → de-dupe, source-label, return.
- [ ] Unit-check: a query about a CT-amended section returns the amendment marked controlling.

**Checkpoint:** given a question, retriever returns clean, labeled, correctly-prioritized
excerpts.

---

## Phase 3 — The agent
- [ ] `prompt.py`: assemble the system prompt from `AGENT_SYSTEM_PROMPT.md` + the active-cycle
      block from `cycles.py`.
- [ ] `agent.py`: build messages (system + retrieved excerpts + question), call Claude
      (`ANSWER_MODEL`), parse into structured answer (direct answer, governing provisions,
      conditions, cross-refs, verify, follow-ups, `needs_clarification`).
- [ ] Implement the clarifying-question path: if the model returns `needs_clarification`,
      return the questions (+ suggested chips) instead of a final answer.
- [ ] Deep-mode hook: escalate to `DEEP_MODEL` on low retrieval confidence or a "hard" flag.
- [ ] **Test the three behaviors:** (a) good cited answer, (b) asks clarifying Qs when
      underspecified, (c) refuses to fabricate when the answer isn't in the books.

**Checkpoint:** end-to-end Q&A works from the terminal / API client.

---

## Phase 4 — Frontend (clean chat UI)
- [ ] React + Vite + Tailwind. Read `frontend-design` skill principles for a non-templated,
      intentional look. Calm, professional, high-contrast, fast.
- [ ] `ChatMessage` + `SourceCitation` (section badge → click to expand quoted source text).
- [ ] `ClarifyingChips` for quick occupancy/type/sprinklered picks.
- [ ] `FeedbackBar` (👍/👎 + "correct this").
- [ ] `CycleBanner` reading `/cycle-status`.
- [ ] Loading/streaming states; keyboard-first; mobile-friendly enough for field use.

**Checkpoint:** the user can ask, see cited answers, expand sources, answer clarifying chips,
and rate answers.

---

## Phase 5 — Learning loop
- [ ] `feedback.py`: `/feedback` writes to SQLite; `/verify` promotes a corrected answer into
      the Verified Answer Library (embed + store).
- [ ] Wire the library into retrieval (Phase 2) so verified answers surface on similar Qs.
- [ ] Simple "review queue" view of 👎 / low-confidence questions.

**Checkpoint:** correct an answer once → ask a similar question → the corrected/verified
answer is retrieved and reflected.

---

## Phase 6 — Code-cycle awareness + polish
- [ ] `cycles.py` reminder logic + `/cycle-status`; banner appears within the warn window.
- [ ] Document the "new cycle arrived" update procedure in the README.
- [ ] Run the acceptance tests in `PROJECT_SPEC.md` (citation accuracy, amendment precedence,
      refusal, clarification, containment).

**Checkpoint:** all acceptance tests pass; `git status` confirms no copyrighted material tracked.

---

## Definition of done (v1)
- All Phase 0–6 checkpoints pass.
- Zero fabricated citations on the test set.
- No copyrighted material in git, ever.
- The marshal can get a cited answer faster than opening the books.
