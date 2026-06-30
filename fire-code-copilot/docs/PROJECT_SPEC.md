# Project Spec — Fire Code CoPilot

## Goal

Cut the time a Hartford fire marshal spends hunting through code books. Ask a question in
plain language; get an accurate, citation-backed answer drawn from the marshal's own books,
respecting Connecticut's adopted/amended editions — with the marshal always able to verify.

## Non-goals (important)

- Not a binding code interpretation or legal authority. The marshal is the AHJ.
- Not a public code library. It does not publish, share, or redistribute code text.
- Not a plan-check / drawing-analysis tool (that's a possible future product — see the
  monetization doc — but out of scope for the personal oracle).
- Not a fine-tuned model. Improvement comes from RAG + curated memory.

## Primary user

One certified fire marshal, City of Hartford, CT, using it on their own desktop with their
own licensed code books.

## User stories

1. *As a marshal, I ask "sprinkler requirements for an existing 3-story R-2" and get the
   governing CT-adopted sections with the exact text, so I don't open three books.*
2. *As a marshal, when my question is missing key facts (occupancy, sprinklered?), the
   assistant asks me the few things that actually change the answer before committing.*
3. *As a marshal, I can expand any answer to see the quoted source section and page, so I
   trust it and can cite it.*
4. *As a marshal, when the assistant is wrong, I correct it once and it remembers — similar
   future questions get the corrected answer.*
5. *As a marshal, I get a heads-up when a new CT code cycle is coming so I can update my books.*
6. *As a marshal, I'm confident my copyrighted books never leave my machine or get committed.*

## Functional requirements

### Must have (v1)
- [ ] Ingest a folder of PDF code books with section-aware chunking + metadata.
- [ ] Plain-language Q&A with retrieval over the marshal's books.
- [ ] Connecticut amendment precedence (adopted/amended text governs base model text).
- [ ] Inline citations: book, edition, section, page + expandable quoted source text.
- [ ] Clarifying-question flow for conditional answers (occupancy, new/existing, type,
      height/area, sprinklered, etc.), with quick-pick chips in the UI.
- [ ] "Not found" honesty — never fabricate a citation.
- [ ] Feedback capture (👍/👎 + correction) to SQLite.
- [ ] Verified Answer Library that feeds back into retrieval.
- [ ] Code-cycle config + reminder banner.
- [ ] Clean, fast chat UI.

### Should have (v1.1)
- [ ] Deep-mode escalation (Opus + query rewrite + second retrieval pass) for hard questions.
- [ ] Conversation threads / history.
- [ ] Per-edition collections so legacy editions stay queryable.
- [ ] Export an answer (with citations) to PDF/notes for the file.

### Could have (later)
- [ ] Local-only generation mode (fully offline).
- [ ] Side-by-side edition diff ("what changed from 2022 → 2026 for this section?").
- [ ] Saved "matters" (group Q&A by inspection/address).

## Quality bar / acceptance tests

- **Citation accuracy:** on a set of ~20 known questions, every cited section number must
  actually exist in the books and say what the answer claims. Zero fabricated citations.
- **Amendment precedence:** for ≥5 sections CT amends, the answer reflects the CT version,
  not the base model text.
- **Refusal:** for a question whose answer isn't in the loaded books, the assistant says so
  instead of inventing one.
- **Clarification:** for an underspecified conditional question, the assistant asks for the
  decisive facts before answering.
- **Containment:** `git status` after a full build + ingest shows no PDFs, no `data/`, no
  extracted text staged or committed.

## The learning loop (summary)

Feedback → Verified Answer Library (retrievable confirmed answers) → gap review → optional
regression eval. See `ARCHITECTURE.md §5`. This is curated memory + better retrieval, not
model retraining — chosen for safety, simplicity, and citation integrity.
