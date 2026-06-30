/**
 * types.ts — UI-only view models (distinct from the wire types in api.ts).
 *
 * A "turn" is one item in the chat log. User turns hold the typed question;
 * assistant turns hold the backend's AskResponse (or a loading/error state, or
 * a pending clarification the marshal still needs to resolve).
 */
import type { AskResponse } from "./api";

/** A question the marshal typed. */
export interface UserTurn {
  id: string;
  role: "user";
  text: string;
  /** building context that was attached to this question, if any */
  buildingContext: string;
}

/** The assistant's side of one exchange. */
export interface AssistantTurn {
  id: string;
  role: "assistant";
  /** lifecycle: thinking -> done | error (clarifying is a sub-state of done) */
  status: "loading" | "done" | "error";
  /** populated once the request resolves */
  response?: AskResponse;
  /** error message if status === "error" */
  error?: string;
  /** the question this answer belongs to (for feedback/verify payloads) */
  question: string;
  /** building context used for this exchange (for feedback payloads) */
  buildingContext: string;
  /** true while a /clarify follow-up for this turn is in flight */
  clarifying?: boolean;
}

export type Turn = UserTurn | AssistantTurn;
