/**
 * ChatMessage — renders one turn in the chat log.
 *
 * User turns: a right-aligned bubble with the typed question.
 *
 * Assistant turns:
 *   - loading           -> a calm "thinking" indicator (see LoadingDots).
 *   - error             -> a critical (deep-red) notice with the message.
 *   - needs_clarification -> ClarifyingChips (App wires onContinue -> /clarify).
 *   - done (answer)     -> markdown answer; a prominent AMBER warning listing
 *                          `unverified` when !citations_ok; a small "deep mode"
 *                          tag when escalated; each source via SourceCitation;
 *                          and FeedbackBar at the bottom.
 */
import ReactMarkdown from "react-markdown";
import type { Turn } from "../lib/types";
import SourceCitation from "./SourceCitation";
import FeedbackBar from "./FeedbackBar";
import ClarifyingChips from "./ClarifyingChips";
import { WarningIcon } from "./icons";

interface Props {
  turn: Turn;
  /** Called when the marshal answers a clarification for THIS turn. */
  onClarify: (turnId: string, answers: string) => void;
}

/** Three-dot pulse used while an answer is generating. */
function LoadingDots() {
  return (
    <div
      className="flex items-center gap-1.5 text-ink-faint"
      role="status"
      aria-label="Generating answer"
    >
      <span className="h-2 w-2 animate-blink rounded-full bg-current [animation-delay:0ms]" />
      <span className="h-2 w-2 animate-blink rounded-full bg-current [animation-delay:200ms]" />
      <span className="h-2 w-2 animate-blink rounded-full bg-current [animation-delay:400ms]" />
      <span className="ml-1 text-xs">Researching your code books…</span>
    </div>
  );
}

export default function ChatMessage({ turn, onClarify }: Props) {
  /* ----------------------------------------------------------- user turn -- */
  if (turn.role === "user") {
    return (
      <div className="flex justify-end animate-rise">
        <div className="max-w-prose whitespace-pre-wrap rounded-2xl rounded-br-sm bg-slate-900 px-4 py-2.5 text-[15px] leading-relaxed text-white">
          {turn.text}
        </div>
      </div>
    );
  }

  /* ------------------------------------------------------ assistant turn -- */
  const { status, response, error } = turn;

  return (
    <div className="animate-rise">
      <div className="max-w-prose rounded-2xl rounded-bl-sm border border-slate-200 bg-white px-4 py-3 shadow-sm">
        {/* Loading */}
        {status === "loading" && <LoadingDots />}

        {/* Error */}
        {status === "error" && (
          <div className="flex items-start gap-2 text-sm text-critical-700">
            <WarningIcon className="mt-0.5 h-4 w-4 shrink-0" />
            <div>
              <p className="font-semibold">Something went wrong.</p>
              <p className="mt-0.5 text-critical-600">{error}</p>
            </div>
          </div>
        )}

        {/* Resolved response */}
        {status === "done" && response && (
          <>
            {/* Clarification path: render chips instead of an answer. */}
            {response.needs_clarification ? (
              <ClarifyingChips
                questions={response.clarifying_questions}
                chips={response.chips}
                busy={turn.clarifying}
                onContinue={(answers) => onClarify(turn.id, answers)}
              />
            ) : (
              <>
                {/* "Deep mode" tag when the backend escalated to the stronger model. */}
                {response.escalated && (
                  <div className="mb-2">
                    <span className="inline-flex items-center rounded bg-slate-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-ink-muted">
                      Deep mode
                    </span>
                  </div>
                )}

                {/* Prominent amber warning when citations could not be verified. */}
                {!response.citations_ok && (
                  <div
                    role="alert"
                    className="mb-3 rounded-md border border-safety-200 bg-safety-50 px-3 py-2.5 text-sm"
                  >
                    <div className="flex items-center gap-2 font-semibold text-safety-700">
                      <WarningIcon className="h-4 w-4" />
                      Unverified citations — confirm before relying on this
                    </div>
                    {response.unverified.length > 0 && (
                      <ul className="mt-1.5 list-disc space-y-0.5 pl-8 text-safety-900">
                        {response.unverified.map((u, i) => (
                          <li key={i} className="font-mono text-xs">
                            {u}
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                )}

                {/* The answer body, rendered as markdown. */}
                {response.answer ? (
                  <div className="answer-prose">
                    <ReactMarkdown>{response.answer}</ReactMarkdown>
                  </div>
                ) : (
                  <p className="text-sm italic text-ink-muted">
                    No answer was returned for this question.
                  </p>
                )}

                {/* Source citations. */}
                {response.sources.length > 0 && (
                  <div className="mt-4">
                    <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-ink-faint">
                      Sources ({response.sources.length})
                    </p>
                    <div className="space-y-1.5">
                      {response.sources.map((s, i) => (
                        <SourceCitation key={i} source={s} index={i + 1} />
                      ))}
                    </div>
                  </div>
                )}

                {/* Feedback loop — only meaningful once there's an answer. */}
                {response.answer && (
                  <FeedbackBar
                    question={turn.question}
                    answer={response.answer}
                    sources={response.sources}
                    buildingContext={turn.buildingContext}
                  />
                )}
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}
