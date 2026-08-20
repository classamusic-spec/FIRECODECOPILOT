import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

interface Props {
  src: string;
  alt: string;
  onClose: () => void;
}

const MIN_ZOOM = 75;
const MAX_ZOOM = 250;
const ZOOM_STEP = 25;

/** Full-viewport, keyboard-accessible viewer for reading the original typeset code page. */
export default function PageLightbox({ src, alt, onClose }: Props) {
  const [zoom, setZoom] = useState(100);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeRef.current?.focus();

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
      if ((event.metaKey || event.ctrlKey) && (event.key === "+" || event.key === "=")) {
        event.preventDefault();
        setZoom((value) => Math.min(MAX_ZOOM, value + ZOOM_STEP));
      }
      if ((event.metaKey || event.ctrlKey) && event.key === "-") {
        event.preventDefault();
        setZoom((value) => Math.max(MIN_ZOOM, value - ZOOM_STEP));
      }
    }

    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
    };
  }, [onClose]);

  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`Enlarged ${alt}`}
      className="fixed inset-0 z-[100] flex flex-col bg-navy-950/95 backdrop-blur-xl"
    >
      <header className="flex min-h-16 shrink-0 items-center gap-3 border-b border-white/10 bg-navy-950/90 px-4 py-3 sm:px-6">
        <div className="min-w-0 flex-1">
          <div className="font-mono text-[10px] uppercase tracking-[0.22em] text-coral-300">Original code page</div>
          <div className="truncate text-sm font-semibold text-steel-100">{alt}</div>
        </div>

        <div className="flex shrink-0 items-center gap-1 rounded-xl border border-white/10 bg-white/[0.04] p-1">
          <button
            type="button"
            onClick={() => setZoom((value) => Math.max(MIN_ZOOM, value - ZOOM_STEP))}
            disabled={zoom === MIN_ZOOM}
            aria-label="Zoom out"
            className="grid h-10 w-10 place-items-center rounded-lg text-xl text-steel-200 transition hover:bg-white/10 hover:text-white disabled:cursor-not-allowed disabled:opacity-35"
          >
            −
          </button>
          <button
            type="button"
            onClick={() => setZoom(100)}
            aria-label="Reset zoom"
            className="min-w-16 rounded-lg px-2 py-2 font-mono text-xs font-semibold text-steel-200 transition hover:bg-white/10 hover:text-white"
          >
            {zoom}%
          </button>
          <button
            type="button"
            onClick={() => setZoom((value) => Math.min(MAX_ZOOM, value + ZOOM_STEP))}
            disabled={zoom === MAX_ZOOM}
            aria-label="Zoom in"
            className="grid h-10 w-10 place-items-center rounded-lg text-xl text-steel-200 transition hover:bg-white/10 hover:text-white disabled:cursor-not-allowed disabled:opacity-35"
          >
            +
          </button>
        </div>

        <a
          href={src}
          target="_blank"
          rel="noreferrer"
          className="hidden h-11 items-center rounded-xl border border-white/10 bg-white/[0.04] px-3 text-xs font-semibold text-steel-200 transition hover:border-coral-400/40 hover:text-white sm:inline-flex"
        >
          Open original
        </a>
        <button
          ref={closeRef}
          type="button"
          onClick={onClose}
          aria-label="Close enlarged page"
          className="grid h-11 w-11 place-items-center rounded-xl border border-white/10 bg-white/[0.04] text-2xl text-steel-300 transition hover:border-coral-400/40 hover:bg-white/[0.08] hover:text-white"
        >
          ×
        </button>
      </header>

      <div className="scroll-thin min-h-0 flex-1 overflow-auto bg-[radial-gradient(circle_at_top,rgba(255,92,66,0.08),transparent_32rem)] p-3 sm:p-6">
        <div className="mx-auto flex min-h-full min-w-max items-start justify-center">
          <img
            src={src}
            alt={alt}
            draggable={false}
            style={{ width: `${zoom}%` }}
            className="h-auto max-w-none rounded-md bg-white shadow-2xl ring-1 ring-black/30 transition-[width] duration-150"
          />
        </div>
      </div>

      <footer className="shrink-0 border-t border-white/10 bg-navy-950/90 px-4 py-2 text-center font-mono text-[10px] uppercase tracking-[0.16em] text-steel-500">
        Scroll to move around · Esc closes · ⌘/Ctrl + or − zooms
      </footer>
    </div>,
    document.body,
  );
}
