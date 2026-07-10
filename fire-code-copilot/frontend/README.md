# Frontend — Fire Code CoPilot

A clean, keyboard-first chat UI over the Fire Code CoPilot FastAPI backend.
React + Vite + TypeScript (strict) with Tailwind CSS v3. Calm, high-contrast,
citation-first design for a working code official — not a playful chatbot.

## Quick start

```bash
npm install            # install dependencies (does not commit node_modules)
npm run dev            # start the Vite dev server on http://localhost:5173
```

The dev UI expects the Fire Code CoPilot backend running on **http://localhost:8001**
so oMLX can own **http://localhost:8000/v1**:

```bash
# from the repo's backend/ directory, in a separate terminal
uvicorn app.main:app --reload --port 8000
```

> Note: the backend's answer generation needs a model (local or Anthropic) that
> may not be configured everywhere. The UI loads and the non-generative endpoints
> (`/health`, `/cycle-status`) work regardless; `/ask` requires a working backend.

## Configuration

The API base URL is read from `VITE_API_BASE` (see `.env.example`):

```bash
cp .env.example .env
# edit if your backend runs elsewhere
VITE_API_BASE=http://localhost:8001
```

The backend has permissive CORS, so the browser calls it directly. A `/api`
dev proxy is also configured in `vite.config.ts` as an optional convenience.

## Build

```bash
npm run build          # tsc -b (type-check) + vite build  ->  dist/
npm run preview        # serve the production build locally
npm run typecheck      # tsc --noEmit only
```

`dist/` is git-ignored; do not commit build output or `node_modules/`.

## Structure

```
src/
  lib/
    api.ts        Typed fetch wrappers + all contract types; throws on non-2xx.
    types.ts      UI-only view models for the chat log (turns).
  components/
    ChatMessage.tsx      One turn: user bubble, or assistant answer (markdown)
                         with an amber unverified-citations warning, a "deep
                         mode" tag, sources, and the feedback bar.
    SourceCitation.tsx   "BOOK ed · §section · p.page" badge; expand to read the
                         quoted source text. Highlights CT amendments
                         (controlling), verified answers, and tables.
    ClarifyingChips.tsx  When the backend needs more facts: quick-pick chips per
                         category + free text; assembles the answers string and
                         calls /clarify.
    FeedbackBar.tsx      👍 / 👎 (/feedback), "Correct this" note, and "Save as
                         verified answer" (/verify).
    CycleBanner.tsx      /cycle-status: dismissible "new edition due" reminder;
                         always exposes the active adopted editions.
    icons.tsx            Inline SVG icons (no icon dependency).
  App.tsx         Chat shell: header (+/health, CycleBanner), message log, and
                  the composer (Enter sends / Shift+Enter newline, provider
                  toggle, Deep checkbox, collapsible building context).
```

## API contract

All requests go through `src/lib/api.ts`, which mirrors the backend exactly:
`POST /ask`, `POST /clarify`, `POST /feedback`, `POST /verify`,
`GET /cycle-status`, `GET /health`. See that file for the request/response types.
