/**
 * demo.ts — canned, offline content for the showcase/demo mode.
 *
 * Activated by a `?demo` (or `?demo=clarify` / `?demo=empty`) query param, or by
 * building with VITE_DEMO=1. In demo mode lib/api short-circuits the network so the
 * full UI renders rich, representative data with no backend — used for screenshots
 * and for sharing a clickable preview. NONE of this is real legal text; the answer is
 * illustrative and the citations are synthetic.
 */
import type { AskResponse, CycleStatus, Health, Source } from "./lib/api";

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
};

/** The answer returned after the marshal resolves the clarifying questions. */
export const demoClarifyResolved: AskResponse = demoAnswer;

const delay = <T>(v: T, ms = 550): Promise<T> =>
  new Promise((r) => setTimeout(() => r(v), ms));

/** Network short-circuits used by lib/api when DEMO is on. */
export const demoApi = {
  ask: () => delay(DEMO_VARIANT === "clarify" ? demoClarify : demoAnswer),
  clarify: () => delay(demoClarifyResolved),
  health: () => delay(demoHealth, 120),
  cycle: () => delay(demoCycle, 120),
  feedback: () => delay({ id: 1, queued_for_review: false }),
  verify: () => delay({ id: "verified-demo", collection: "verified_answers", sections: ["903.2.8.4"] }),
};
