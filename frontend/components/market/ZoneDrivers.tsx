import { DRIVER_WORDS, effectText, pointsFromNeutral } from "@/lib/zoneDrivers";
import type { MarketZone } from "@/lib/schemas";

const TONE = { greed: "text-red-600", fear: "text-emerald-700", neutral: "text-ink-soft" } as const;
const FILL = { greed: "bg-red-500", fear: "bg-emerald-600", neutral: "bg-slate-400" } as const;

/** The signals behind the score in plain words: what each asks, what it says now, and how many points it adds to or takes from the overall score. */
export function ZoneDrivers({ drivers }: { drivers: MarketZone["drivers"] }) {
  if (drivers.length === 0) return null;
  const lean = (s: number) => effectText("", s).lean;
  const greedy = drivers.filter((d) => lean(d.score) === "greed").length;
  const fearful = drivers.filter((d) => lean(d.score) === "fear").length;
  const sorted = [...drivers].sort((a, b) => Math.abs(b.score - 50) - Math.abs(a.score - 50));
  return (
    <div>
      <h3 className="text-xs font-medium uppercase tracking-wide text-ink-soft">What is behind the score</h3>
      <p className="mb-3 mt-1 text-xs text-ink-soft">
        {greedy} of {drivers.length} signals lean greedy, {fearful} lean fearful, {drivers.length - greedy - fearful} are normal. The score is their average, so each bar below shows how many points it adds to the total (red, towards greed) or takes away (green, towards fear). Each is judged against its own last 45 days.
      </p>
      <ul className="space-y-3">
        {sorted.map((d) => {
          const e = effectText(d.key, d.score), pts = pointsFromNeutral(d.score, drivers.length), w = DRIVER_WORDS[d.key];
          const width = Math.min(50, (Math.abs(d.score - 50) / 50) * 50);
          return (
            <li key={d.key} className="text-xs">
              <div className="flex items-baseline justify-between gap-2">
                <span className="font-medium text-ink">{w?.title ?? d.name}</span>
                <span className={`tabular-nums ${TONE[e.lean]}`}>{e.strength} · {pts >= 0 ? "+" : "−"}{Math.abs(pts).toFixed(1)} points</span>
              </div>
              <div className={TONE[e.lean]}>{e.text}</div>
              <div className="relative mt-1 h-1.5 rounded-full bg-slate-100" role="img" aria-label={`${w?.title ?? d.name}: ${Math.round(d.score)} out of 100`}>
                <div className="absolute left-1/2 top-[-2px] h-[10px] w-px bg-slate-300" />
                <div className={`absolute h-1.5 rounded-full ${FILL[e.lean]}`} style={e.lean === "fear" ? { right: "50%", width: `${width}%` } : { left: "50%", width: `${width}%` }} />
              </div>
              <div className="mt-0.5 text-ink-faint">{d.reading ? `Now: ${d.reading}. ` : ""}{w?.what}</div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
