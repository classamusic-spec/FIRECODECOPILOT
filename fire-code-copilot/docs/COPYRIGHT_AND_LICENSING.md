# Copyright & Licensing — Fire Code CoPilot

> Plain-language summary, not legal advice. Confirm specifics with your own attorney before
> monetizing, and check your municipal ethics rules as a public fire marshal.

## Why this matters

Fire/building codes are written by private nonprofits — the **International Code Council (ICC)**
and the **National Fire Protection Association (NFPA)** — and they hold copyright in the
model-code text and commentary. They fund themselves largely by selling that text. They are
**actively litigious** about reproduction (e.g., the multi-year *ICC v. UpCodes* case).

At the same time, courts have increasingly protected *free public access* to codes that have
been **incorporated into law**. In April 2026 the Third Circuit held that UpCodes' publication
of incorporated standards was likely fair use. **But the decisive factor was that UpCodes
did not charge for access to the code text.** The "market harm" factor turns against you the
moment you sell access to the copyrighted text and compete with the publishers' revenue.

The practical line:
- **Reading/searching codes you've licensed, privately = fine.**
- **Making the law freely readable to the public = increasingly protected (if free).**
- **Selling access to the copyrighted text = high risk, invites a well-funded lawsuit.**

## Personal use (this project) — you're on safe ground

For your own desktop tool, using books you bought, you are within normal personal use. To
stay clean, this project enforces:

1. **Code books never leave your machine.** Default processing is local; only your question
   and small retrieved snippets go to the Claude API. A fully-local embedding option exists.
2. **Nothing copyrighted enters git.** `.gitignore` excludes `code_books/`, `data/`,
   extracted text, and the vector store. After your first build, run `git status` and confirm.
3. **No publish/share feature.** The app is single-user. Don't add a way to export the
   corpus or expose code text to others.
4. **It's a research aid, not a rebroadcast.** It surfaces sections *to you* to verify.

Do this and the personal oracle carries essentially no copyright risk.

## If you later monetize — yes, use a SEPARATE repo

Keep the money product in its own repository, and architect it so **the copyrighted text is
never in your product at all.** Recommended approach, lowest-risk first:

### Option A — Sell the workflow, "bring your own license" (recommended)
Your product is the **intelligence + workflow layer**: clarifying-question logic, inspection
checklists, violation tracking, report generation, the Hartford/CT amendment map, saved
matters, etc. Users authenticate to **their own** licensed code access (ICC Digital Codes
Premium / NFPA LiNK) and the text stays on the publisher's side. You never store or ship the
code text. You sell time saved and workflow, not the code.
- **Pro:** sidesteps the core copyright problem.
- **Con:** the publishers now have their own AI tools (ICC "AI Navigator", NFPA "CASI"), so
  compete on workflow/UX/Hartford-specific value, not on "we have the code."

### Option B — Build around non-copyrighted material
Things that aren't the publishers' protected text: the **Connecticut amendments** themselves
(state-authored, much weaker copyright claim — but still verify), statutory references,
checklists, your own original explanations, training material, and tooling. Point *into* the
code rather than reproducing it.

### Option C — License it properly
ICC and NFPA do license to third parties. Legitimate but expensive, and you'd compete with
their own products. Worth a conversation only if A/B prove out commercially.

### What NOT to do
- Don't ship the model-code text (or a database of it) inside a paid product.
- Don't let your monetized repo ingest copyrighted PDFs you then redistribute or expose.
- Don't market it as an official or binding interpretation source.

## Two more flags as a sitting public fire marshal
- **Municipal ethics / conflict of interest.** Building a paid business adjacent to your AHJ
  role can trigger your city's ethics rules. Check before selling anything.
- **Liability.** If others rely on AI code interpretations sold under your name, that's
  exposure. Keep "verify against the official adopted code; not a binding interpretation"
  front and center, and talk to counsel about an LLC + disclaimers + insurance.

## Repo separation checklist
- [ ] Monetized work lives in a **new repo** (e.g., `fire-code-workflow`), not this one.
- [ ] That repo contains **zero** copyrighted code text or PDFs.
- [ ] "Bring your own license" for the actual code text (Option A).
- [ ] Disclaimers + "not a binding interpretation" throughout.
- [ ] Entity + insurance + municipal-ethics check before first dollar.
