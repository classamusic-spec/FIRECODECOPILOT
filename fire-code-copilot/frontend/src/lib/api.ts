/**
 * api.ts — the single typed boundary between the UI and the FastAPI backend.
 *
 * Every type here mirrors the backend contract EXACTLY (see backend/app/models.py
 * and backend/app/agent.py::AgentResult). Do not invent endpoints or fields.
 *
 * Base URL comes from VITE_API_BASE (default http://localhost:8000). The backend
 * sets permissive CORS, so the browser calls it directly.
 */

// Resolve the API base once. import.meta.env values are strings (or undefined).
export const API_BASE: string =
  (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/+$/, "") ??
  "http://localhost:8000";

/* ------------------------------------------------------------------ Types -- */

/** Generation backend toggle. `null` lets the backend use its configured default. */
export type Provider = "local" | "anthropic" | null;

/** Two backend behaviours: compose an answer, or just return grounded sources. */
export type Mode = "answer" | "retrieve";

/** Up/down rating for the feedback loop. */
export type Rating = "up" | "down";

/** Metadata attached to each retrieved code chunk. All fields optional per contract. */
export interface SourceMetadata {
  book?: string;
  edition?: string;
  section?: string;
  page?: number | string;
  is_amendment?: boolean;
  is_table?: boolean;
  verified?: boolean;
  controlling?: boolean;
}

/** One retrieved source chunk: the quoted text plus its provenance metadata. */
export interface Source {
  text: string;
  metadata: SourceMetadata;
}

/** The unified response shape returned by /ask and /clarify (AgentResult). */
export interface AskResponse {
  mode: string;
  answer: string | null;
  sources: Source[];
  citations_ok: boolean;
  unverified: string[];
  needs_clarification: boolean;
  clarifying_questions: string[];
  /** map of category -> quick-pick chip labels, e.g. { Occupancy: ["R-2","B"] } */
  chips: Record<string, string[]>;
  escalated: boolean;
}

/** Request body for POST /ask. */
export interface AskRequest {
  question: string;
  mode?: Mode;
  building_context?: string;
  deep?: boolean;
  provider?: Provider;
}

/** Request body for POST /clarify. */
export interface ClarifyRequest {
  question: string;
  answers: string;
  building_context?: string;
  deep?: boolean;
  provider?: Provider;
}

/** Request body for POST /feedback. */
export interface FeedbackRequest {
  question: string;
  answer: string;
  rating: Rating;
  note?: string;
  building_context?: string;
  sources?: Source[];
}

/** Response from POST /feedback. */
export interface FeedbackResponse {
  id: number;
  queued_for_review: boolean;
}

/** Request body for POST /verify. */
export interface VerifyRequest {
  question: string;
  corrected_answer: string;
  governing_sections?: string[];
  edition?: string;
}

/** Response from POST /verify. */
export interface VerifyResponse {
  id: string;
  collection: string;
  sections: string[];
}

/** Response from GET /cycle-status. */
export interface CycleStatus {
  active: string;
  reminder: string | null;
}

/** Response from GET /health. */
export interface Health {
  ok: boolean;
  jurisdiction: string;
  generation_provider: string;
  model: string;
}

/* -------------------------------------------------------------- Internals -- */

/** Error carrying the HTTP status, so callers can branch on it if needed. */
export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/**
 * Centralized fetch. Throws ApiError (with the response body text) on any
 * non-2xx, so every call site can rely on a resolved promise meaning success.
 */
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...init,
    });
  } catch (e) {
    // Network-level failure (server down, CORS, DNS). Give an actionable message.
    const detail = e instanceof Error ? e.message : String(e);
    throw new ApiError(0, `Could not reach the backend at ${API_BASE}. ${detail}`);
  }

  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new ApiError(res.status, body || `${res.status} ${res.statusText}`);
  }
  // 204/empty bodies are not expected on these endpoints, but guard anyway.
  const text = await res.text();
  return (text ? JSON.parse(text) : null) as T;
}

function post<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, { method: "POST", body: JSON.stringify(body) });
}

/* ----------------------------------------------------------------- Calls -- */

/** Ask a code question. */
export function ask(body: AskRequest): Promise<AskResponse> {
  return post<AskResponse>("/ask", body);
}

/** Continue a thread after the marshal answers clarifying questions. */
export function clarify(body: ClarifyRequest): Promise<AskResponse> {
  return post<AskResponse>("/clarify", body);
}

/** Send 👍/👎 feedback (optionally with a correction note). */
export function sendFeedback(body: FeedbackRequest): Promise<FeedbackResponse> {
  return post<FeedbackResponse>("/feedback", body);
}

/** Promote a corrected answer into the Verified Answer Library. */
export function verifyAnswer(body: VerifyRequest): Promise<VerifyResponse> {
  return post<VerifyResponse>("/verify", body);
}

/** Current adopted cycle + any "new edition due" reminder. */
export function getCycleStatus(): Promise<CycleStatus> {
  return request<CycleStatus>("/cycle-status");
}

/** Backend health + jurisdiction/provider/model identity. */
export function getHealth(): Promise<Health> {
  return request<Health>("/health");
}
