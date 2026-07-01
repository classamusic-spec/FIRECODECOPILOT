/**
 * Drawer — the shared right-anchored slide-over shell (navy-cockpit language).
 *
 * Handles the backdrop, Esc-to-close, focus-on-open, and the frosted-glass panel
 * chrome. Callers provide a header (icon + title + optional trailing controls) and
 * the scrollable body. Reused by the Review/Verified drawer and the History drawer.
 */
import { useEffect, useRef, type ReactNode } from "react";
import { CloseIcon } from "./icons";

interface Props {
  open: boolean;
  onClose: () => void;
  /** accessible label for the dialog */
  label: string;
  /** header content (rendered left of the close button) */
  header: ReactNode;
  /** scrollable body content */
  children: ReactNode;
}

export default function Drawer({ open, onClose, label, header, children }: Props) {
  const closeRef = useRef<HTMLButtonElement>(null);

  // Esc closes; focus the close button when the drawer opens.
  useEffect(() => {
    if (!open) return;
    closeRef.current?.focus();
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-40">
      {/* Backdrop — click anywhere outside the panel to dismiss. */}
      <button
        type="button"
        aria-label={`Close ${label}`}
        onClick={onClose}
        className="absolute inset-0 h-full w-full cursor-default bg-navy-950/70 backdrop-blur-sm"
      />

      {/* Panel — anchored right, full height, frosted glass. */}
      <div
        role="dialog"
        aria-label={label}
        aria-modal="true"
        className="glass absolute right-0 top-0 flex h-full w-full max-w-[460px] flex-col rounded-none border-y-0 border-r-0 animate-rise"
      >
        <div className="flex items-center gap-2.5 border-b border-white/10 px-4 py-3.5">
          {header}
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="ml-auto grid h-8 w-8 shrink-0 place-items-center rounded-lg text-steel-400 transition-colors hover:bg-white/[0.06] hover:text-steel-100"
          >
            <CloseIcon className="h-4 w-4" />
          </button>
        </div>

        <div className="scroll-thin flex-1 overflow-y-auto px-4 py-4">{children}</div>
      </div>
    </div>
  );
}
