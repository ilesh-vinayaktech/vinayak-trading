import type { ReactNode } from "react";
import type { ToolType } from "@/lib/drawings/model";

// One consistent icon set: 24px grid, 1.6px round strokes, currentColor. Hand-drawn for this console
// (no icon dependency), one glyph per tool so the rail reads like a professional charting terminal.

const D = (x: number, y: number) => <circle cx={x} cy={y} r={1.9} fill="currentColor" stroke="none" />;

const GLYPHS: Record<string, ReactNode> = {
  cursor: <><path d="M12 3v6M12 15v6M3 12h6M15 12h6" /><circle cx={12} cy={12} r={1} fill="currentColor" /></>,
  trend: <><path d="M6 18L18 6" />{D(5.5, 18.5)}{D(18.5, 5.5)}</>,
  ray: <><path d="M6 18L21 3" />{D(5.5, 18.5)}</>,
  extended: <><path d="M3 21L21 3" />{D(8.5, 15.5)}{D(15.5, 8.5)}</>,
  hline: <><path d="M3 12h18" />{D(12, 12)}</>,
  hray: <><path d="M6 12h15" />{D(5.5, 12)}</>,
  vline: <><path d="M12 3v18" />{D(12, 12)}</>,
  cross: <><path d="M3 12h18M12 3v18" />{D(12, 12)}</>,
  arrow: <><path d="M5 19L19 5M10 5h9v9" /></>,
  channel: <><path d="M3 14L16 3M8 21L21 10" /><path d="M5.5 17.5L18.5 6.5" strokeDasharray="2 3" /></>,
  pitchfork: <><path d="M4 20L20 4M9 20l11-11M4 15L15 4" />{D(4.5, 19.5)}</>,
  rect: <rect x={4} y={6} width={16} height={12} rx={1.5} />,
  ellipse: <ellipse cx={12} cy={12} rx={9} ry={6} />,
  triangle: <path d="M12 4L21 20H3Z" strokeLinejoin="round" />,
  brush: <path d="M4 19c3-9 5 1 8-6 2-5 4-1 8-8" />,
  fibret: <><path d="M3 5h18M3 10h18M3 15h18M3 20h18" /><path d="M6 20L18 5" strokeDasharray="2 2.5" /></>,
  fibext: <><path d="M3 4h18M3 9h18M3 14h18" /><path d="M4 20L10 10l5 5" />{D(4.5, 19.5)}{D(10, 10)}</>,
  measure: <><path d="M4 17L17 4l3 3L7 20z" strokeLinejoin="round" /><path d="M8 13l2 2M11 10l2 2M14 7l2 2" /></>,
  pricerange: <><path d="M12 5v14M8.5 8.5L12 5l3.5 3.5M8.5 15.5L12 19l3.5-3.5M5 4h14M5 20h14" /></>,
  daterange: <><path d="M5 12h14M8.5 8.5L5 12l3.5 3.5M15.5 8.5L19 12l-3.5 3.5M4 5v14M20 5v14" /></>,
  long: <><rect x={4} y={4} width={16} height={7} rx={1} /><rect x={4} y={11} width={16} height={9} rx={1} strokeDasharray="2 2" /><path d="M12 9V6M10.5 7.5L12 6l1.5 1.5" /></>,
  short: <><rect x={4} y={13} width={16} height={7} rx={1} /><rect x={4} y={4} width={16} height={9} rx={1} strokeDasharray="2 2" /><path d="M12 15v3M10.5 16.5L12 18l1.5-1.5" /></>,
  text: <path d="M6 6h12M12 6v13M9 19h6" />,
  magnet: <path d="M6 4v8a6 6 0 0012 0V4M6 8h4M14 8h4" strokeLinejoin="round" />,
  undo: <path d="M9 14L4 9l5-5M4 9h10a5.5 5.5 0 010 11h-3" />,
  redo: <path d="M15 14l5-5-5-5M20 9H10a5.5 5.5 0 000 11h3" />,
  camera: <><path d="M4 8h3l1.5-2.5h7L17 8h3v11H4z" strokeLinejoin="round" /><circle cx={12} cy={13} r={3.2} /></>,
  fullscreen: <path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" />,
  exit: <path d="M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5" />,
  list: <path d="M9 6h11M9 12h11M9 18h11M4.5 6h.01M4.5 12h.01M4.5 18h.01" />,
  eye: <><path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z" /><circle cx={12} cy={12} r={2.8} /></>,
  eyeoff: <><path d="M3 3l18 18M10.6 5.7A9 9 0 0112 5.5c6 0 9.5 6.5 9.5 6.5a16 16 0 01-3 3.7M6.4 7.4A16 16 0 002.5 12S6 18.5 12 18.5a9 9 0 003.4-.7" /></>,
  lock: <><rect x={5} y={11} width={14} height={9} rx={1.5} /><path d="M8 11V8a4 4 0 018 0v3" /></>,
  unlock: <><rect x={5} y={11} width={14} height={9} rx={1.5} /><path d="M8 11V8a4 4 0 017.5-2" /></>,
  trash: <path d="M5 7h14M10 7V4h4v3M7 7l1 13h8l1-13M10 11v5M14 11v5" strokeLinejoin="round" />,
  copy: <><rect x={8} y={8} width={12} height={12} rx={1.5} /><path d="M16 8V5.5A1.5 1.5 0 0014.5 4h-9A1.5 1.5 0 004 5.5v9A1.5 1.5 0 005.5 16H8" /></>,
  search: <><circle cx={10.5} cy={10.5} r={6.5} /><path d="M15.5 15.5L21 21" /></>,
  chevron: <path d="M6 9l6 6 6-6" />,
  candles: <><path d="M7 4v3M7 14v3M17 8v3M17 17v3" /><rect x={5} y={7} width={4} height={7} rx={0.5} /><rect x={15} y={11} width={4} height={6} rx={0.5} /></>,
  line: <path d="M3 17l5-6 4 3 6-8 3 4" strokeLinejoin="round" />,
  area: <><path d="M3 17l5-6 4 3 6-8 3 4v7H3z" strokeLinejoin="round" fill="currentColor" fillOpacity={0.15} /></>,
  info: <><circle cx={12} cy={12} r={9} /><path d="M12 11v5M12 8h.01" /></>,
};

export type IconName = keyof typeof GLYPHS | ToolType;

export function Icon({ name, size = 20, className }: { name: IconName; size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden="true" focusable="false">
      {GLYPHS[name] ?? null}
    </svg>
  );
}
