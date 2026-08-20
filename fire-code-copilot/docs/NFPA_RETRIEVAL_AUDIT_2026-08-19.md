# NFPA / Connecticut Core-Book Retrieval Audit

**Audit date:** August 19, 2026
**Application:** Fire Code CoPilot
**Active corpus:** `/Users/xavi/Desktop/2022 FIRE Codes`
**Active collection:** `csfsc_2022`

## Executive finding

NFPA 101 was present and indexed, but the application treated almost every NFPA 101 chunk as
`(preamble)`. The parser recognized ICC-style section numbers beginning with three or four digits
(e.g. `903.2.8`) but not common NFPA headings beginning with one or two digits (e.g. `7.1` or
`31.1.1.1`). Before repair, **1,371 of 1,377 NFPA 101 chunks** carried `(preamble)` metadata.

A second defect produced the user-visible message: citation validation looked for `NFPA 101` only
inside each retrieved chunk's body text. The chapter-split NFPA exports do not repeat the book title
in every chunk, although their `book` and `source` metadata identify NFPA 101 correctly. A correct
answer naming NFPA 101 was therefore annotated with:

> The following section reference(s) were not found in your loaded code books: NFPA 101

The book was not missing. The validator was ignoring authoritative source metadata.

## Root causes and repairs

1. **NFPA section headings were not parsed.** The chunker now accepts one- through four-digit NFPA
   section roots, number-only heading lines, significance asterisks, and Annex A headings while
   rejecting copyright years.
2. **Citation validation ignored book metadata.** Standard names are now verified from retrieved
   `book`/`source` metadata as well as body text. A different standard (for example NFPA 999) remains
   unverified.
3. **BM25 indexed body text only.** BM25 now indexes `book` and `source` labels alongside body text,
   so an explicit `NFPA 101` request ranks NFPA 101 even when the page body omits the title.
4. **Queries did not encode Connecticut's applicability branches.** Deterministic expansion now
   maps NFPA 101 to Part IV, NFPA 1 to the State Fire Prevention Code, IFC to Part III, pre-2006
   original permits to NFPA 101/Part IV, post-2005 original permits to the Part III/IFC framework,
   alterations/new work to Part III, and operational/hot-work questions to NFPA 1.
5. **Building context was prompt-only.** Original permit date and other supplied building facts now
   participate in retrieval for both normal and streaming requests.
6. **The clarification gate omitted Connecticut's cutoff date.** For an existing building without
   an original permit period, it can ask one decisive question: whether the original permit was
   issued before January 1, 2006.
7. **Cycle guidance was stale.** The active prompt now states that the 2022 Connecticut codes remain
   active and the proposed 2026 cycle is delayed pending state approval. It includes the Part III,
   Part IV, NFPA 1, mixed-alteration, and change-of-use rules supplied for this audit.
8. **NFPA 1 metadata had the wrong edition.** The 73 chapter records were labeled `NFPA 1 2022`
   because of their parent folder even though each source is the 2021 edition. The local
   `books.yaml` metadata now identifies them as NFPA 1, 2021 edition. The legacy folder name remains
   unchanged to avoid breaking source paths.
9. **Dense-only retrieval and body-only reranking could displace an explicitly named book.** Hybrid
   retrieval is now enabled, the reranker receives provenance labels, and the final source slate
   preserves the requested base code together with its controlling Connecticut amendment layer.
10. **Large BM25 initialization could exceed SQLite limits.** Chroma documents are now loaded in
    pages, and the cache notices external same-count Chroma updates through the store revision.
11. **Citation relationships were not preserved.** `NFPA 101 §31.1.1.1` now verifies the section
    against an NFPA 101 source, rather than independently finding the book in one chunk and the
    number in another. Annex A citations are parsed and validated as well.

## Core-book coverage

| Governing layer | Corpus status | Audit result |
|---|---:|---|
| 2021 IFC + 2022 CSFSC Part III | Present | Available for new work, alterations, additions, and changes of occupancy/use |
| 2021 NFPA 101 + 2022 CSFSC Part IV | Present | Rebuilt with NFPA-aware section metadata; explicit and pre-2006 retrieval verified |
| 2021 NFPA 1 + 2022 CSFPC | Present | Rebuilt with corrected 2021 edition metadata; hot-work retrieval verified |
| 2022 CSBC + 2021 IBC | Present | Available; the IBC PDF is a Code and Commentary publication, not a model-code-only copy |
| **2021 IEBC base code** | **Missing** | The Connecticut amendment material is present, but no standalone 2021 IEBC base book was found in the active folder or reversible archive |
| NFPA 13-2019 | Present twice | Near-duplicate copies overweight NFPA 13 retrieval and should be reconciled separately |
| NFPA 14-2019 | Present | Available |
| NFPA 20-2019 | Present | Available |
| NFPA 25-2020 | Present | Available |
| NFPA 72-2019 | Present | Available |
| NFPA 96-2021 | Present | Chapters 1–17 and Annex B indexed; explanatory Annex A is absent |

The missing 2021 IEBC is a real corpus gap. Connecticut's IEBC amendments do not substitute for the
copyrighted base model code. The app should not claim a complete IEBC answer until a lawfully
obtained 2021 IEBC source is added and indexed.

## Connecticut currentness

The official Connecticut DAS adoption-process page confirms that the proposed Building, Fire
Safety, and Fire Prevention code cycle did not take effect July 1, 2026 as anticipated and remains
subject to state approval. The application therefore keeps the 2022 cycle active and presents the
2026 cycle as delayed, not possibly already in effect.

Official status source:
<https://portal.ct.gov/das/office-of-state-building-inspector/building-and-fire-code-adoption-process>

## Final index reconciliation

The targeted rebuild exited successfully. The stable post-run collection contains **45,353 chunks**
from **317 adopted-code sources**. Ingestion state contains 319 sources because two tracked General
Statutes sources live in the separate statutes collection. The active manifest contains 320 PDFs;
the remaining active document is the known image-only `Plan Review Check list.pdf` scan.

| Indexed family | Chunks |
|---|---:|
| NFPA 101-2021 | 7,980 |
| NFPA 1-2021 | 10,756 |
| NFPA 96-2021 | 738 |
| IFC-2021 | 5,674 |
| IBC-2021 Code and Commentary | 7,369 |
| NFPA 13-2019 | 1,735 per indexed copy |
| NFPA 14-2019 | 162 |
| NFPA 20-2019 | 497 |
| NFPA 25-2020 | 496 |
| NFPA 72-2019 | 1,185 |

## Verification

- Explicit NFPA 101 existing-apartment retrieval ranked NFPA 101 Chapter 31 first.
- New-construction retrieval ranked the 2021 IFC base code first and retained Connecticut Fire
  Safety Code material.
- Hot-work retrieval ranked NFPA 1 Chapter 41 first.
- Explicit NFPA 13 and NFPA 96 queries ranked the requested standards first.
- Connecticut Part IV amendment queries ranked the Connecticut Fire Safety Code amendment layer.
- Backend: **163 passed, 1 skipped**.
- Frontend TypeScript typecheck and production build: passed.
- `git diff --check` and the added-line security scan: clean.
