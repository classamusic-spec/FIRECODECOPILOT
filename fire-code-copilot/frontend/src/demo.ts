/**
 * demo.ts — canned, offline content for the showcase/demo mode.
 *
 * Activated by a `?demo` (or `?demo=clarify` / `?demo=empty`) query param, or by
 * building with VITE_DEMO=1. In demo mode lib/api short-circuits the network so the
 * full UI renders rich, representative data with no backend — used for screenshots
 * and for sharing a clickable preview. NONE of this is real legal text; the answer is
 * illustrative and the citations are synthetic.
 */
import type { AskResponse, AskStreamOpts, CollectionsResponse, CycleStatus, Health, ReviewItem, Source, StreamHandlers, VerifiedItem } from "./lib/api";

const params = new URLSearchParams(
  typeof window !== "undefined" ? window.location.search : "",
);
export const DEMO: boolean =
  params.has("demo") || import.meta.env.VITE_DEMO === "1";
/** "" (hero), "clarify", or "empty". */
export const DEMO_VARIANT: string = params.get("demo") ?? "";

export const demoHealth: Health = {
  ok: true,
  jurisdiction: "City of Hartford, Connecticut",
  generation_provider: "anthropic",
  model: "claude-sonnet-4-6",
};

export const demoCycle: CycleStatus = {
  active:
    "ACTIVE CYCLE: 2022 Connecticut State Codes (effective 2022-10-01)\n" +
    "  - Connecticut State Fire Safety Code (CSFSC) — CT edition 2022 (base: 2021 IFC)\n" +
    "  - Connecticut State Building Code (CSBC) — CT edition 2022 (base: 2021 IBC)",
  reminder:
    "2026 Connecticut State Codes expected in ~1 day. Verify with CT DAS, update your " +
    "code books + config/code_cycles.yaml, then re-run ingestion.",
};

const sources: Source[] = [
  {
    text:
      "903.2.8.4 Group R-2 existing buildings (Amd). In existing Group R-2 buildings, an " +
      "automatic sprinkler system shall be installed throughout where required by the State " +
      "Fire Marshal upon a change of occupancy or a substantial alteration as defined by the " +
      "Connecticut State Building Code.",
    metadata: {
      book: "CSFSC", edition: "2022", section: "903.2.8.4", page: 41,
      is_amendment: true, controlling: true, is_table: false,
    },
  },
  {
    text:
      "903.2.8 Group R. An automatic sprinkler system installed in accordance with Section " +
      "903.3 shall be provided throughout all buildings with a Group R fire area. For the " +
      "purposes of this section, fire areas are determined in accordance with the building code.",
    metadata: {
      book: "IFC (model)", edition: "2021", section: "903.2.8", page: 38,
      is_amendment: false, is_table: false,
    },
  },
  {
    text:
      "903.2.8.1 Group R-2. An automatic sprinkler system shall be installed throughout " +
      "buildings containing a Group R-2 occupancy where the building is more than three stories " +
      "above grade plane, has more than 16 dwelling units, or any Group R-2 fire area exceeds " +
      "12,000 square feet.",
    metadata: {
      book: "IFC (model)", edition: "2021", section: "903.2.8.1", page: 38,
      is_amendment: false, is_table: false,
    },
  },
  {
    text:
      "Q: sprinkler requirements for an existing Group R-2 on change of occupancy\n" +
      "VERIFIED ANSWER: In CT, an existing Group R-2 triggers sprinklers throughout on a change " +
      "of occupancy or substantial alteration under the CSFSC amendment to §903.2.8 — confirmed " +
      "with the State Fire Marshal's office, 2026-04.",
    metadata: {
      book: "VERIFIED", edition: "csfsc_2022", section: "903.2.8.4", page: "—",
      verified: true, is_amendment: false, is_table: false,
    },
  },
];

export const demoAnswer: AskResponse = {
  mode: "answer",
  answer:
    "## Direct answer\n" +
    "**Yes — most likely.** For an *existing* Group R-2 in Hartford, an automatic sprinkler " +
    "system is required throughout when the work is a **change of occupancy** or a **substantial " +
    "alteration**, under Connecticut's amendment to the IFC. New Group R-2 construction is " +
    "separately required to be sprinklered.\n\n" +
    "## Governing provisions\n" +
    "- **CSFSC 2022 §903.2.8.4 (CT amendment — controlling)** adds existing Group R-2 buildings: " +
    "sprinklers throughout *on change of occupancy or substantial alteration*.\n" +
    "- **IFC 2021 §903.2.8 / §903.2.8.1** require sprinklers in Group R / Group R-2 (the base " +
    "model text the amendment builds on).\n\n" +
    "## Conditions / assumptions\n" +
    "- If this is **not** a change of occupancy or substantial alteration, the retrofit trigger " +
    "may not apply — confirm the alteration level.\n" +
    "- New construction Group R-2 is required to be sprinklered regardless.\n\n" +
    "## Verify\n" +
    "Confirm the alteration level against the CSBC and the controlling §903.2.8.4 text before a " +
    "determination. The 2026 cycle may change this.",
  sources,
  citations_ok: true,
  unverified: [],
  needs_clarification: false,
  clarifying_questions: [],
  chips: {},
  escalated: true,
  confidence: 0.82,
  confidence_band: "high",
};

export const demoClarify: AskResponse = {
  mode: "answer",
  answer: null,
  sources: [],
  citations_ok: true,
  unverified: [],
  needs_clarification: true,
  clarifying_questions: [
    "Is this new construction, or an existing building?",
    "If existing — is the work a change of occupancy or a substantial alteration?",
    "Is the building already sprinklered?",
  ],
  chips: {
    Status: ["New construction", "Existing", "Change of occupancy", "Alteration"],
    Occupancy: ["R-2", "R-1", "B", "A-2"],
    Sprinklered: ["Yes", "No", "Partial"],
  },
  escalated: false,
  confidence: null,
  confidence_band: null,
};

/** The answer returned after the marshal resolves the clarifying questions. */
export const demoClarifyResolved: AskResponse = demoAnswer;

/**
 * demoReview — flagged questions for the Review queue drawer. These are 👎 /
 * low-confidence turns the marshal pushed back on, with correction notes. As with
 * the rest of this file the text is illustrative, not authoritative legal content.
 */
export const demoReview: ReviewItem[] = [
  {
    id: 312,
    created_at: "2026-06-29T14:22:00Z",
    question:
      "Is a sprinkler system required for an existing Group R-2 in Hartford on a change of occupancy?",
    building_context: "Existing R-2 · 4 stories · 22 units · not sprinklered",
    answer:
      "The model IFC §903.2.8.1 requires sprinklers in Group R-2 only where the building is more " +
      "than three stories, has more than 16 dwelling units, or a fire area exceeds 12,000 sq ft, so " +
      "this building would already qualify under the base code.",
    rating: "down",
    note:
      "Missed the controlling CT amendment. CSFSC 2022 §903.2.8.4 adds existing Group R-2: " +
      "sprinklers throughout on a change of occupancy or substantial alteration — that's the " +
      "governing trigger here, not the base §903.2.8.1 thresholds.",
  },
  {
    id: 305,
    created_at: "2026-06-28T09:05:00Z",
    question:
      "What's the minimum egress width per occupant for a B occupancy without sprinklers?",
    building_context: "Business · 140 occupants · non-sprinklered · stairs",
    answer:
      "Use 0.2 inches per occupant for stairways and 0.15 inches per occupant for other egress " +
      "components.",
    rating: "down",
    note:
      "Those are the reduced (sprinklered) factors. For a non-sprinklered building use the " +
      "higher §1005.3 factors: 0.3 in/occupant for stairways, 0.2 in/occupant for other " +
      "components. Always confirm sprinkler status before picking the multiplier.",
  },
  {
    id: 298,
    created_at: "2026-06-27T16:48:00Z",
    question: "Does the CT amendment change fire-rated corridor requirements for R-2?",
    building_context: "",
    answer:
      "No — corridor fire-resistance ratings follow IBC Table 1020.1 unchanged in Connecticut.",
    rating: "down",
    note:
      "Cite the adopted CSBC edition of the table, not the generic IBC, and flag that the rating " +
      "depends on sprinklered vs. non-sprinklered. Re-verify against the 2022 CSBC corridor table.",
  },
  {
    id: 287,
    created_at: "2026-06-26T11:30:00Z",
    question: "Occupant load factor for a fitness area in a mixed-use building?",
    building_context: "Exercise room · ~1,800 sq ft · gross area",
    answer: "Use 15 net for the exercise room.",
    rating: "down",
    note:
      "Low confidence — the answer didn't cite the source table or distinguish exercise rooms " +
      "(50 gross) from exercise equipment areas. Pin to the adopted occupant-load table and show it.",
  },
];

const delay = <T>(v: T, ms = 550): Promise<T> =>
  new Promise((r) => setTimeout(() => r(v), ms));

const sleep = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms));

/**
 * Abortable sleep used by the demo stream: resolves after `ms`, OR immediately
 * (clearing the pending timer) the moment `signal` aborts — so a Stop click
 * doesn't have to wait out the last token's delay.
 */
const sleepUntil = (ms: number, signal?: AbortSignal): Promise<void> =>
  new Promise((resolve) => {
    const timer = setTimeout(done, ms);
    function done() {
      clearTimeout(timer);
      signal?.removeEventListener("abort", done);
      resolve();
    }
    signal?.addEventListener("abort", done, { once: true });
  });

/**
 * Simulate the real /ask/stream event order offline so the demo answer animates
 * in token-by-token. Clarify variant emits a single onClarify; otherwise it dribbles
 * the canned answer out as word chunks, then finalizes with onMeta.
 */
async function demoStream(h: StreamHandlers, opts?: AskStreamOpts): Promise<void> {
  // Treat an already-fired (or mid-stream) abort signal as a clean stop, mirroring
  // the real askStream: bail before the next scheduled chunk and call onAbort.
  const aborted = () => Boolean(opts?.signal?.aborted);
  if (aborted()) { h.onAbort?.(); return; }

  if (DEMO_VARIANT === "clarify") {
    await sleep(450);
    if (aborted()) { h.onAbort?.(); return; }
    h.onClarify(demoClarify.clarifying_questions, demoClarify.chips, false);
    return;
  }

  await sleep(250);
  // Split on whitespace but KEEP the trailing space on each chunk so reassembly
  // (concatenation) reproduces the original answer exactly.
  const chunks = (demoAnswer.answer ?? "").match(/\S+\s*/g) ?? [];
  for (const chunk of chunks) {
    // Check before each scheduled chunk; stop emitting tokens once aborted.
    if (aborted()) { h.onAbort?.(); return; }
    h.onToken(chunk);
    // ~25–40ms per chunk, but short-circuit (and clear the timer) on abort.
    await sleepUntil(25 + Math.random() * 15, opts?.signal);
  }
  if (aborted()) { h.onAbort?.(); return; }
  h.onMeta({
    sources: demoAnswer.sources,
    citations_ok: true,
    unverified: [],
    answer_suffix: "",
    escalated: demoAnswer.escalated,
    confidence: demoAnswer.confidence,
    confidence_band: demoAnswer.confidence_band,
  });
}

/**
 * demoVerified — believable entries for the Verified Answer Library tab. As with
 * the rest of this file, the text is illustrative, not authoritative legal content.
 */
export const demoVerified: VerifiedItem[] = [
  {
    id: "ver_903_r2",
    question:
      "Is a sprinkler system required for an existing Group R-2 in Hartford on a change of occupancy?",
    answer:
      "Yes. Under the CSFSC 2022 amendment §903.2.8.4, an existing Group R-2 requires an automatic " +
      "sprinkler system throughout on a change of occupancy or substantial alteration — confirmed with " +
      "the State Fire Marshal's office.",
    sections: ["903.2.8.4", "903.2.8"],
    edition: "csfsc_2022",
    verified_at: "2026-06-24T13:10:00Z",
  },
  {
    id: "ver_1005_egress",
    question: "Egress width factors for a non-sprinklered B occupancy?",
    answer:
      "Non-sprinklered: use §1005.3 factors — 0.3 in/occupant for stairways and 0.2 in/occupant for " +
      "other egress components. The reduced 0.2/0.15 factors apply only to sprinklered buildings.",
    sections: ["1005.3"],
    edition: "csbc_2022",
    verified_at: "2026-06-18T09:42:00Z",
  },
  {
    id: "ver_corridor_r2",
    question: "Corridor fire-resistance rating for a sprinklered R-2 in CT?",
    answer:
      "Cite the adopted 2022 CSBC corridor table (not the generic IBC). For a sprinklered Group R-2 the " +
      "required corridor rating is reduced — verify the sprinklered column of the adopted table.",
    sections: ["1020.1"],
    edition: "csbc_2022",
    verified_at: "2026-06-11T15:05:00Z",
  },
];

/**
 * demoCollections — two stored code-edition cycles for the edition selector: the
 * active 2022 cycle and a legacy 2018 cycle (for existing-building questions). As
 * with the rest of this file, the numbers are illustrative, not authoritative.
 */
export const demoCollections: CollectionsResponse = {
  active: "csfsc_2022",
  collections: [
    { name: "csfsc_2022", books: 2, chunks: 812, editions: ["2021", "2022"], active: true },
    { name: "csfsc_2018", books: 2, chunks: 760, editions: ["2015", "2018"], active: false },
  ],
};

/** Network short-circuits used by lib/api when DEMO is on. */
export const demoApi = {
  ask: () => delay(DEMO_VARIANT === "clarify" ? demoClarify : demoAnswer),
  collections: () => delay(demoCollections, 120),
  stream: (h: StreamHandlers, opts?: AskStreamOpts) => demoStream(h, opts),
  clarify: () => delay(demoClarifyResolved),
  health: () => delay(demoHealth, 120),
  cycle: () => delay(demoCycle, 120),
  feedback: () => delay({ id: 1, queued_for_review: false }),
  verify: () => delay({ id: "verified-demo", collection: "verified_answers", sections: ["903.2.8.4"] }),
  review: () => delay({ items: demoReview }),
  verified: () => delay({ items: demoVerified }),
  deleteVerified: (id: string) => delay({ deleted: true, id }),
};
