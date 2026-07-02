# Monetization Plan — the Harness as a Product

> Companion to `COPYRIGHT_AND_LICENSING.md` (read that first — it defines the legal lines this
> plan lives inside). Plain-language planning notes, not legal or financial advice.

## What is actually for sale

**Never the code text.** ICC/NFPA fund themselves selling it and litigate; the case law that
protects free public access flips against anyone who *charges* for the text (market-harm factor).

What we built — and what is sellable — is the **harness around the text**:

- section-aware ingestion + token-aware chunking of the *customer's own licensed* books
- **amendment-precedence layering** (the controlling state text always wins, shown side-by-side)
- **citation honesty**: whole-token section grounding + verbatim-quote validation, click-to-verify
  down to the highlighted line and the real typeset page
- the **Verified Answer Library** — a compounding, office-owned institutional memory
- matters (per-address/permit organization), review queue, confidence surfacing
- local-first privacy: the corpus, the index, and inspection data never leave the machine

Business model: **bring-your-own-license.** The product ships empty; each customer ingests the
books *they* bought. The copyright containment this repo enforces per-user is exactly the
multi-tenant architecture the model requires.

## Who buys it

1. **Fire marshal offices / building departments (AHJs)** — the core segment. Local-first is a
   selling point: departments often cannot send inspection data to cloud AI tools.
2. **Third-party inspectors and code consultants** — individual seats, credit-card sales.
3. **Fire-protection engineers and architects** — plan-review acceleration.

## The moat (what ICC AI Navigator / NFPA CASI / UpCodes don't have)

- **Jurisdictional layering**: the state-amendment precedence map (start: Connecticut). State-
  authored amendments carry a much weaker copyright claim than model-code text (verify with
  counsel). Expansion is **state-by-state amendment maps**, never more code text.
- **The compounding library**: a year of a marshal's verified answers is switching-cost gold.
- **Verification-first UX** and a defensible "decision support, never a determination" posture.
- The harness generalizes: "citation-honest RAG over a licensed corpus with an authority-
  precedence layer" fits any regulated vertical where a local authority amends a national
  standard. Fire code is the proof; the harness is the asset.

## Pricing

Anchors the buyers already accept: ICC Digital Codes Premium ≈ $400–700/yr, NFPA LiNK ≈
$250–500/yr, UpCodes ≈ $470–700/yr — *just to read the text*. Value math: saving 2–3 hrs/week of
professional time ($50–100/hr) is $5k–15k/yr of value per seat; capture ~10%.

| Tier | Price | Notes |
|---|---|---|
| Individual | $39–49/mo ($400–500/yr annual) | solo inspectors, consultants, FPEs |
| Office (5 seats) | $1,500–2,500/yr | marshal offices, small departments |
| Department / enterprise | $5,000–10,000/yr quoted | onboarding + training + priority support |
| Perpetual alternative | $399–599 one-time + $99–149/yr updates | municipal buyers often prefer perpetual + maintenance over SaaS |
| Setup & training service | $500–1,500 one-time | also how we learn municipal procurement |

Rules of thumb:
- **Do not price below ~$30/mo** — in professional verticals, cheap signals toy; buyers evaluate
  on trust, and marginal cost is ~zero (local inference, BYO license), so pricing is value capture.
- **Annual is the headline** (offices budget annually); monthly is the low-commitment door.
- **Founding pricing** for the first 10–20 customers (40–50% off, locked) in exchange for
  feedback + referenceability — in this community, references are the entire sales channel.

## Prerequisites before the first dollar (gating items)

1. **Municipal ethics check (FIRST — costs nothing).** A sitting Hartford fire marshal selling a
   product adjacent to the AHJ role can trigger conflict-of-interest rules.
2. **Separate repo** for the product, containing **zero** copyrighted text or PDFs.
3. **Entity + insurance + disclaimers** ("not a binding interpretation; verify against the
   official adopted code" everywhere), per counsel.
4. Verify the CT-amendment copyright position with counsel before marketing it as content.

## Sequencing

1. Prove the tool on the owner's real books; tighten from real usage.
2. Ethics check → LLC → separate product repo (harness code only).
3. 3–5 pilot offices at founding pricing, sold with the setup service; iterate on procurement.
4. Only then: pricing page, self-serve individual tier, and the second state's amendment map.
