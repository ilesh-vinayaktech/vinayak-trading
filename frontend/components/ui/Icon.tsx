import type { ReactNode } from "react";

// A small, consistent icon set for navigation and controls: 24px grid, 1.7px round strokes, currentColor.
const GLYPHS = {
  dashboard: <><rect x={3.5} y={3.5} width={7} height={8} rx={1.5} /><rect x={13.5} y={3.5} width={7} height={5} rx={1.5} /><rect x={13.5} y={11.5} width={7} height={9} rx={1.5} /><rect x={3.5} y={14.5} width={7} height={6} rx={1.5} /></>,
  chart: <path d="M4 19V5M4 19h16M8 15l3-4 3 2 4-6" />,
  benchmark: <path d="M4 20h16M7 20V11M12 20V6M17 20v-6" />,
  flask: <path d="M9 3h6M10 3v6L5 18a2 2 0 001.8 3h10.4A2 2 0 0019 18l-5-9V3M8 15h8" />,
  review: <><path d="M9 12l2 2 4-4" /><circle cx={12} cy={12} r={9} /></>,
  activity: <path d="M3 12h4l3-8 4 16 3-8h4" />,
  support: <><circle cx={12} cy={12} r={9} /><circle cx={12} cy={12} r={3.5} /><path d="M5.6 5.6l3.9 3.9M14.5 14.5l3.9 3.9M18.4 5.6l-3.9 3.9M9.5 14.5l-3.9 3.9" /></>,
  tasks: <><rect x={4} y={4} width={16} height={16} rx={2.5} /><path d="M8.5 12.5l2.5 2.5 4.5-5" /></>,
  plug: <path d="M9 3v5M15 3v5M6 8h12v3a6 6 0 01-12 0V8zM12 17v4" />,
  users: <><circle cx={9} cy={8} r={3.5} /><path d="M2.5 20c.5-3.5 3.2-5.5 6.5-5.5s6 2 6.5 5.5" /><path d="M16 4.7a3.5 3.5 0 010 6.6M18 14.8c2 .6 3.2 2.3 3.5 5.2" /></>,
  scroll: <><path d="M7 4h11a2 2 0 012 2v12a2 2 0 01-2 2H8a3 3 0 01-3-3V6" /><path d="M9 9h7M9 13h7M9 17h4" /></>,
  shield: <><path d="M12 3l8 3v5.5c0 4.5-3.2 8-8 9.5-4.8-1.5-8-5-8-9.5V6l8-3z" /><path d="M9 12l2 2 4-4" /></>,
  calendar: <><rect x={4} y={5} width={16} height={15} rx={2} /><path d="M4 10h16M9 3v4M15 3v4" /></>,
  menu: <path d="M4 7h16M4 12h16M4 17h16" />,
  close: <path d="M6 6l12 12M18 6L6 18" />,
  chevron: <path d="M7 10l5 5 5-5" />,
  eye: <><path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z" /><circle cx={12} cy={12} r={2.8} /></>,
  eyeOff: <><path d="M3 3l18 18M10.6 6a9.6 9.6 0 011.4-.1c6 0 9.5 6.1 9.5 6.1a16 16 0 01-3.2 3.9M6.5 7.6A15.7 15.7 0 002.5 12S6 18.5 12 18.5c1.5 0 2.8-.4 4-.9" /><path d="M9.9 9.9a3 3 0 004.2 4.2" /></>,
  check: <path d="M5 12.5l4.5 4.5L19 7.5" />,
  circle: <circle cx={12} cy={12} r={8} />,
  info: <><circle cx={12} cy={12} r={9} /><path d="M12 11v5M12 8h.01" /></>,
  alert: <><path d="M12 4l9 16H3L12 4z" strokeLinejoin="round" /><path d="M12 10v4.5M12 17.5h.01" /></>,
  logout: <path d="M10 4H6a2 2 0 00-2 2v12a2 2 0 002 2h4M15 8l4 4-4 4M19 12H9" />,
  user: <><circle cx={12} cy={8} r={4} /><path d="M4.5 20c.7-4 3.6-6 7.5-6s6.8 2 7.5 6" /></>,
} satisfies Record<string, ReactNode>;

export type IconName = keyof typeof GLYPHS;

export function Icon({ name, size = 18, className }: { name: IconName; size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false" className={className}>
      {GLYPHS[name]}
    </svg>
  );
}
