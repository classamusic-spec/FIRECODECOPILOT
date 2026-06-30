/**
 * icons.tsx — a tiny set of inline SVG icons.
 *
 * We avoid an icon dependency: these are hand-picked, currentColor-driven
 * glyphs sized for the UI. Each takes a className so callers control size/color.
 */
import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement>;

const base = (p: IconProps) => ({
  width: 16,
  height: 16,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
  ...p,
});

export const ChevronIcon = (p: IconProps) => (
  // Points right by default; rotate via className (e.g. "rotate-90") when open.
  <svg {...base(p)}>
    <polyline points="9 18 15 12 9 6" />
  </svg>
);

export const InfoIcon = (p: IconProps) => (
  <svg {...base(p)}>
    <circle cx="12" cy="12" r="10" />
    <line x1="12" y1="16" x2="12" y2="12" />
    <line x1="12" y1="8" x2="12.01" y2="8" />
  </svg>
);

export const WarningIcon = (p: IconProps) => (
  <svg {...base(p)}>
    <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
    <line x1="12" y1="9" x2="12" y2="13" />
    <line x1="12" y1="17" x2="12.01" y2="17" />
  </svg>
);

export const SendIcon = (p: IconProps) => (
  <svg {...base(p)}>
    <line x1="22" y1="2" x2="11" y2="13" />
    <polygon points="22 2 15 22 11 13 2 9 22 2" />
  </svg>
);

export const ThumbUpIcon = (p: IconProps) => (
  <svg {...base(p)}>
    <path d="M7 10v12" />
    <path d="M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2a3.13 3.13 0 0 1 3 3.88z" />
  </svg>
);

export const ThumbDownIcon = (p: IconProps) => (
  <svg {...base(p)}>
    <path d="M17 14V2" />
    <path d="M9 18.12 10 14H4.17a2 2 0 0 1-1.92-2.56l2.33-8A2 2 0 0 1 6.5 2H20a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-2.76a2 2 0 0 0-1.79 1.11L12 22a3.13 3.13 0 0 1-3-3.88z" />
  </svg>
);

export const CloseIcon = (p: IconProps) => (
  <svg {...base(p)}>
    <line x1="18" y1="6" x2="6" y2="18" />
    <line x1="6" y1="6" x2="18" y2="18" />
  </svg>
);

export const CheckIcon = (p: IconProps) => (
  <svg {...base(p)}>
    <polyline points="20 6 9 17 4 12" />
  </svg>
);

export const SparkIcon = (p: IconProps) => (
  // A four-point "deep mode" spark.
  <svg {...base(p)}>
    <path d="M12 3v4M12 17v4M3 12h4M17 12h4" />
    <path d="M12 8a4 4 0 0 0 0 8 4 4 0 0 0 0-8z" />
  </svg>
);

export const ShieldIcon = (p: IconProps) => (
  <svg {...base(p)}>
    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
  </svg>
);

/**
 * BrandMark — a flame inside a shield, the app's identity. Uses fill (not the
 * stroke base) so it reads as a solid coral glyph. Pass a className for size.
 */
export const BrandMark = (p: IconProps) => (
  <svg viewBox="0 0 24 24" fill="none" aria-hidden width={24} height={24} {...p}>
    {/* shield outline */}
    <path
      d="M12 2.2 4.5 5v6.4c0 5 3.4 8 7.5 10.4 4.1-2.4 7.5-5.4 7.5-10.4V5L12 2.2z"
      fill="currentColor"
      fillOpacity="0.16"
      stroke="currentColor"
      strokeWidth="1.3"
      strokeLinejoin="round"
    />
    {/* flame */}
    <path
      d="M12 7c.7 1.5 2.6 2.3 2.6 4.6A2.7 2.7 0 0 1 12 14.3a2.7 2.7 0 0 1-2.6-2.7c0-.9.4-1.5.8-2 .2.5.5.8.9 1 .1-1 .4-2.1.9-3.6z"
      fill="currentColor"
    />
  </svg>
);
