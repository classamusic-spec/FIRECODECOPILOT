/**
 * api.ts — the single typed boundary between the UI and the FastAPI backend.
 *
 * Every type here mirrors the backend contract EXACTLY (see backend/app/models.py
 * and backend/app/agent.py::AgentResult). Do not invent endpoints or fields.
 *
 * Base URL comes from VITE_API_BASE (default http://localhost:8000). The backend
 * sets permissive CORS, so the browser calls it directly.
 */
import { DEMO, demoApi } from "../demo";

// Resolve the API base once. import.meta.env values are strings (or undefined).
export const API_BASE: string =
  (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/+$/, "") ??
  "http://localhost:8000";

/* ------------------------------------------------------------------ Types -- */

/** Generation backend toggle. `null` lets the backend use its configured default. */
export type Provider = "local" | "openai" | "anthropic" | null;

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

/** Reranker confidence bucket. `null` when there is no reranker signal. */
export type ConfidenceBand = "low" | "medium" | "high" | null;

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
  /** reranker confidence score, or null when there is no reranker signal */
  confidence: number | null;
  /** bucketed confidence, or null when there is no reranker signal */
  confidence_band: ConfidenceBand;
}

/** Request body for POST /ask. */
export interface AskRequest {
  question: string;
  mode?: Mode;
  building_context?: string;
  deep?: boolean;
  provider?: Provider;
  /** Which code-edition collection to search; omit/empty = the backend's active edition. */
  collection?: string;
}

/** One selectable code-edition collection (a stored cycle) from GET /collections. */
export interface Collection {
  /** collection name / id (what you pass back as AskRequest.collection) */
  name: string;
  /** number of code books ingested, or null when unknown */
  books: number | null;
  /** number of retrievable chunks in the collection */
  chunks: number;
  /** the CT edition years this collection covers, e.g. ["2021","2022"] */
  editions: string[];
  /** true for the currently adopted collection */
  active: boolean;
}

/** Response from GET /collections: the active collection name + the full list. */
export interface CollectionsResponse {
  active: string;
  collections: Collection[];
}

/** Request body for POST /clarify. */
export interface ClarifyRequest {
  question: string;
  answers: string;
  building_context?: string;
  deep?: boolean;
  provider?: Provider;
  /** Same semantics as AskRequest.collection — the clarify follow-up must search the SAME
   *  edition the original question did, or the final answer silently switches code cycles. */
  collection?: string;
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

/** One flagged (👎 / low-confidence) question awaiting the marshal's review. */
export interface ReviewItem {
  id: number;
  created_at: string;
  question: string;
  building_context: string;
  answer: string;
  rating: string;
  note: string;
}

/** Response from GET /review-queue. */
export interface ReviewQueue {
  items: ReviewItem[];
}

/** One entry in the Verified Answer Library (GET /verified). */
export interface VerifiedItem {
  id: string;
  question: string;
  answer: string;
  sections: string[];
  edition: string;
  verified_at: string;
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
// In demo/showcase mode (?demo or VITE_DEMO=1) every call resolves to canned
// content so the full UI renders with no backend (see demo.ts).

/** Ask a code question. */
export function ask(body: AskRequest): Promise<AskResponse> {
  if (DEMO) return demoApi.ask();
  return post<AskResponse>("/ask", body);
}

/* ------------------------------------------------------------- Streaming -- */

/**
 * Callbacks driven by POST /ask/stream (Server-Sent Events). The stream emits
 * zero-or-more `token`s, then exactly one of (`clarify` | `meta`), then `done`;
 * an `error` may arrive instead at any point. Each callback maps 1:1 to an event
 * `type` on the wire — see the backend SSE contract.
 */
export interface StreamHandlers {
  /** a `token` event: append `text` to the live answer */
  onToken: (text: string) => void;
  /** a `clarify` event: this turn is a clarification, not an answer (discard tokens) */
  onClarify: (q: string[], chips: Record<string, string[]>, escalated: boolean) => void;
  /** a `meta` event: finalize — full answer = accumulated tokens + answer_suffix */
  onMeta: (m: {
    sources: Source[];
    citations_ok: boolean;
    unverified: string[];
    answer_suffix: string;
    escalated: boolean;
    confidence: number | null;
    confidence_band: ConfidenceBand;
  }) => void;
  /** an `error` event, or a network/HTTP failure */
  onError: (message: string) => void;
  /** the in-flight request was aborted via opts.signal (NOT routed to onError) */
  onAbort?: () => void;
}

/** Per-call options for {@link askStream}. */
export interface AskStreamOpts {
  /** when this aborts, the fetch/reader is cancelled and onAbort fires */
  signal?: AbortSignal;
}

/**
 * Stream an answer token-by-token from POST /ask/stream. Reads the SSE body,
 * splits on the blank-line event delimiter, parses each `data: {json}` line and
 * dispatches by `type`. Resolves when the stream ends (or after onError).
 *
 * In demo mode the network is short-circuited and the stream is simulated from
 * canned content (see demo.ts::demoApi.stream).
 */
export async function askStream(
  body: AskRequest,
  h: StreamHandlers,
  opts?: AskStreamOpts,
): Promise<void> {
  if (DEMO) return demoApi.stream(h, opts);

  let res: Response;
  try {
    res = await fetch(`${API_BASE}/ask/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: opts?.signal,
    });
  } catch (e) {
    // A user-initiated abort surfaces as an AbortError — treat it as a clean stop,
    // not an error the UI should shout about.
    if (e instanceof DOMException && e.name === "AbortError") {
      h.onAbort?.();
      return;
    }
    const detail = e instanceof Error ? e.message : String(e);
    h.onError(`Could not reach the backend at ${API_BASE}. ${detail}`);
    return;
  }

  if (!res.ok || !res.body) {
    const text = await res.text().catch(() => "");
    h.onError(text || `${res.status} ${res.statusText}`);
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  // Whether a terminal event (clarify | meta | error) arrived. If the connection closes
  // without one (backend restarted, proxy cut the stream), the caller's turn would be stuck
  // in "streaming" forever — we surface that as an error instead.
  let terminal = false;

  // Route one parsed SSE payload to the matching handler.
  const dispatch = (payload: unknown) => {
    if (!payload || typeof payload !== "object") return;
    const ev = payload as { type?: string; [k: string]: unknown };
    if (ev.type === "clarify" || ev.type === "meta" || ev.type === "error") terminal = true;
    switch (ev.type) {
      case "token":
        h.onToken(String(ev.text ?? ""));
        break;
      case "clarify":
        h.onClarify(
          (ev.clarifying_questions as string[]) ?? [],
          (ev.chips as Record<string, string[]>) ?? {},
          Boolean(ev.escalated),
        );
        break;
      case "meta":
        h.onMeta({
          sources: (ev.sources as Source[]) ?? [],
          citations_ok: Boolean(ev.citations_ok),
          unverified: (ev.unverified as string[]) ?? [],
          answer_suffix: String(ev.answer_suffix ?? ""),
          escalated: Boolean(ev.escalated),
          confidence: typeof ev.confidence === "number" ? ev.confidence : null,
          confidence_band: (ev.confidence_band as ConfidenceBand) ?? null,
        });
        break;
      case "error":
        h.onError(String(ev.message ?? "Stream error."));
        break;
      // "done" and any unknown types are ignored.
    }
  };

  // Pull one `data: {json}` event out of a `\n\n`-delimited chunk.
  const handleChunk = (chunk: string) => {
    for (const line of chunk.split("\n")) {
      if (!line.startsWith("data:")) continue;
      const json = line.slice(5).trim();
      if (!json) continue;
      try {
        dispatch(JSON.parse(json));
      } catch {
        /* ignore malformed lines rather than aborting the stream */
      }
    }
  };

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      // Events are separated by a blank line; process all complete ones.
      let sep: number;
      while ((sep = buffer.indexOf("\n\n")) !== -1) {
        const chunk = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);
        handleChunk(chunk);
      }
    }
    // Flush any trailing event that wasn't terminated by a blank line.
    if (buffer.trim()) handleChunk(buffer);
    if (!terminal) {
      h.onError("The connection closed before the answer finished. The backend may have restarted — try again.");
    }
  } catch (e) {
    // An abort cancels the reader and throws — finalize quietly via onAbort.
    if (e instanceof DOMException && e.name === "AbortError") {
      h.onAbort?.();
      return;
    }
    const detail = e instanceof Error ? e.message : String(e);
    h.onError(`The answer stream was interrupted. ${detail}`);
  }
}

/** Continue a thread after the marshal answers clarifying questions. */
export function clarify(body: ClarifyRequest): Promise<AskResponse> {
  if (DEMO) return demoApi.clarify();
  return post<AskResponse>("/clarify", body);
}

/** Send 👍/👎 feedback (optionally with a correction note). */
export function sendFeedback(body: FeedbackRequest): Promise<FeedbackResponse> {
  if (DEMO) return demoApi.feedback();
  return post<FeedbackResponse>("/feedback", body);
}

/** Promote a corrected answer into the Verified Answer Library. */
export function verifyAnswer(body: VerifyRequest): Promise<VerifyResponse> {
  if (DEMO) return demoApi.verify();
  return post<VerifyResponse>("/verify", body);
}

/** Current adopted cycle + any "new edition due" reminder. */
export function getCycleStatus(): Promise<CycleStatus> {
  if (DEMO) return demoApi.cycle();
  return request<CycleStatus>("/cycle-status");
}

/** Backend health + jurisdiction/provider/model identity. */
export function getHealth(): Promise<Health> {
  if (DEMO) return demoApi.health();
  return request<Health>("/health");
}

/** The marshal's review queue: 👎/low-confidence questions flagged for follow-up. */
export function getReviewQueue(): Promise<ReviewQueue> {
  if (DEMO) return demoApi.review();
  return request<ReviewQueue>("/review-queue");
}

/** List the stored code-edition collections + which one is active (GET /collections). */
export function getCollections(): Promise<CollectionsResponse> {
  if (DEMO) return demoApi.collections();
  return request<CollectionsResponse>("/collections");
}

/** The Verified Answer Library: marshal-confirmed answers (GET /verified). */
export function getVerified(): Promise<{ items: VerifiedItem[] }> {
  if (DEMO) return demoApi.verified();
  return request<{ items: VerifiedItem[] }>("/verified");
}

/** Remove a verified answer by id (DELETE /verified/{id}). */
export function deleteVerified(id: string): Promise<{ deleted: boolean; id: string }> {
  if (DEMO) return demoApi.deleteVerified(id);
  return request<{ deleted: boolean; id: string }>(`/verified/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}
