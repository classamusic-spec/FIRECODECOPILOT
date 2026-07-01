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
import type { ConfidenceBand } from "../lib/api";
import SourceCitation from "./SourceCitation";
import FeedbackBar from "./FeedbackBar";
import ClarifyingChips from "./ClarifyingChips";
import AmendmentDiff from "./AmendmentDiff";
import { WarningIcon, SparkIcon } from "./icons";

interface Props {
  turn: Turn;
  /** Called when the marshal answers a clarification for THIS turn. */
  onClarify: (turnId: string, answers: string) => void;
}

/**
 * ConfidenceChip — a small reranker-confidence signal shown near the "Deep mode"
 * tag. Renders nothing when the band is null (no reranker → no signal to show).
 */
function ConfidenceChip({ band }: { band: ConfidenceBand }) {
  if (!band) return null;
  const styles: Record<"low" | "medium" | "high", { chip: string; dot: string; label: string }> = {
    high: {
      chip: "border-verified-500/30 bg-verified-500/15 text-verified-700",
      dot: "bg-verified-500",
      label: "High",
    },
    medium: {
      chip: "border-white/10 bg-white/10 text-steel-300",
      dot: "bg-steel-400",
      label: "Medium",
    },
    low: {
      chip: "border-coral-500/40 bg-coral-500/10 text-coral-200",
      dot: "bg-coral-400",
      label: "Low",
    },
  };
  const s = styles[band];
  return (
    <span className={"inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider " + s.chip}>
      <span className={"h-1.5 w-1.5 rounded-full " + s.dot} />
      Confidence: {s.label}
    </span>
  );
}

/** Three-dot pulse used while an answer is generating. */
function LoadingDots() {
  return (
    <div className="flex items-center gap-1.5 text-coral-400" role="status" aria-label="Generating answer">
      <span className="h-2 w-2 animate-blink rounded-full bg-current [animation-delay:0ms]" />
      <span className="h-2 w-2 animate-blink rounded-full bg-current [animation-delay:200ms]" />
      <span className="h-2 w-2 animate-blink rounded-full bg-current [animation-delay:400ms]" />
      <span className="ml-1 text-xs text-steel-400">Researching your code books…</span>
    </div>
  );
}

export default function ChatMessage({ turn, onClarify }: Props) {
  /* ----------------------------------------------------------- user turn -- */
  if (turn.role === "user") {
    return (
      <div className="flex justify-end animate-rise">
        <div className="max-w-prose whitespace-pre-wrap rounded-2xl rounded-br-md bg-coral-500 px-4 py-2.5 text-[15px] leading-relaxed text-white shadow-glow-sm">
          {turn.text}
        </div>
      </div>
    );
  }

  /* ------------------------------------------------------ assistant turn -- */
  const { status, response, error } = turn;

  return (
    <div className="animate-rise">
      <div className="glass max-w-prose px-4 py-3.5">
        {/* Loading (request open, no tokens yet) */}
        {status === "loading" && <LoadingDots />}

        {/* Streaming: render accumulated tokens live, with a blinking caret.
            Until the first token lands we still show the LoadingDots. */}
        {status === "streaming" &&
          (turn.streamText ? (
            <div className="answer-prose">
              <ReactMarkdown>{turn.streamText}</ReactMarkdown>
              <span
                className="ml-0.5 inline-block h-4 w-[2px] -translate-y-px animate-blink bg-coral-400 align-middle"
                aria-hidden="true"
              />
            </div>
          ) : (
            <LoadingDots />
          ))}

        {/* Error */}
        {status === "error" && (
          <div className="flex items-start gap-2 text-sm text-critical-700">
            <WarningIcon className="mt-0.5 h-4 w-4 shrink-0" />
            <div>
              <p className="font-semibold text-critical-600">Something went wrong.</p>
              <p className="mt-0.5 text-steel-300">{error}</p>
            </div>
          </div>
        )}

        {/* Resolved response */}
        {status === "done" && response && (
          <>
            {response.needs_clarification ? (
              <ClarifyingChips
                questions={response.clarifying_questions}
                chips={response.chips}
                busy={turn.clarifying}
                onContinue={(answers) => onClarify(turn.id, answers)}
              />
            ) : (
              <>
                {(response.escalated || response.confidence_band) && (
                  <div className="mb-2.5 flex flex-wrap items-center gap-1.5">
                    {response.escalated && (
                      <span className="inline-flex items-center gap-1 rounded-full border border-coral-500/30 bg-coral-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-coral-300">
                        <SparkIcon className="h-3 w-3" /> Deep mode
                      </span>
                    )}
                    <ConfidenceChip band={response.confidence_band} />
                  </div>
                )}

                {/* Prominent coral warning when citations could not be verified. */}
                {!response.citations_ok && (
                  <div role="alert" className="mb-3 rounded-xl border border-coral-500/40 bg-coral-500/10 px-3 py-2.5 text-sm">
                    <div className="flex items-center gap-2 font-semibold text-coral-200">
                      <WarningIcon className="h-4 w-4" />
                      Unverified citations — confirm before relying on this
                    </div>
                    {response.unverified.length > 0 && (
                      <ul className="mt-1.5 list-disc space-y-0.5 pl-8 text-coral-200/90">
                        {response.unverified.map((u, i) => (
                          <li key={i} className="font-mono text-xs">{u}</li>
                        ))}
                      </ul>
                    )}
                  </div>
                )}

                {response.answer ? (
                  <div className="answer-prose">
                    <ReactMarkdown>{response.answer}</ReactMarkdown>
                  </div>
                ) : (
                  <p className="text-sm italic text-steel-400">No answer was returned for this question.</p>
                )}

                {/* Model-vs-CT amendment diff — surfaced above the flat Sources
                    list; returns null (renders nothing) when there are no pairs. */}
                <AmendmentDiff sources={response.sources} />

                {response.sources.length > 0 && (
                  <div className="mt-4">
                    <p className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-steel-500">
                      Sources
                      <span className="rounded-full bg-white/10 px-1.5 py-0.5 text-[10px] text-steel-300">{response.sources.length}</span>
                    </p>
                    <div className="space-y-1.5">
                      {response.sources.map((s, i) => (
                        <SourceCitation key={i} source={s} index={i + 1} />
                      ))}
                    </div>
                  </div>
                )}

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
