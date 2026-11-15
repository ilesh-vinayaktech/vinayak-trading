import type { IntelFunnel, IntelProgress } from "@/lib/schemas";

type Stage = IntelFunnel["stages"][number];
type Job = IntelProgress["jobs"][number];

const share = (n: number, of: number) => (of > 0 ? Math.round((n / of) * 100) : 0);

/** The steps of the research pipeline, left to right. A step with a `job` shows the live state of that job; the others are done by hand for now. */
const STEPS: { label: string; job?: string }[] = [
  { label: "Validate features", job: "feature_validation" },
  { label: "Compute features", job: "feature_computation" },
  { label: "Discover alpha", job: "alpha_discovery" },
  { label: "Register strategies" },
  { label: "Run experiments" },
  { label: "Validate" },
  { label: "Paper trade" },
];

function latest(jobs: Job[], name: string): Job | undefined {
  return jobs.filter((j) => j.job === name).sort((a, b) => b.id - a.id)[0];
}

/** The cycle strip: which step is running right now (with its own progress), which last finished, which failed, and which are not automated yet. */
export function PipelineStrip({ jobs }: { jobs: Job[] }) {
  return (
    <ol className="grid gap-2 sm:grid-cols-4 lg:grid-cols-7" aria-label="Research pipeline steps">
      {STEPS.map((s, i) => {
        const j = s.job ? latest(jobs, s.job) : undefined;
        const state = !s.job ? "manual" : !j ? "idle" : j.status === "RUNNING" ? (j.stalled ? "stuck" : "running") : j.status === "DONE" ? "done" : "failed";
        const tone = {
          running: "border-blue-500 bg-blue-50 text-blue-900",
          stuck: "border-red-500 bg-red-50 text-red-900",
          failed: "border-red-400 bg-red-50 text-red-900",
          done: "border-emerald-400 bg-emerald-50 text-emerald-900",
          idle: "border-line bg-panel text-ink-soft",
          manual: "border-dashed border-line bg-panel text-ink-faint",
        }[state];
        const caption = {
          running: j ? `running · ${j.done} of ${j.total}` : "",
          stuck: "may be stuck",
          failed: "failed",
          done: "finished",
          idle: "not run yet",
          manual: "not automated yet",
        }[state];
        return (
          <li key={s.label} data-testid={`step-${i}`} data-state={state} className={`rounded-md border px-3 py-2 text-xs ${tone}`}>
            <div className="text-[10px] uppercase tracking-wide opacity-70">Step {i + 1}</div>
            <div className="font-semibold">{s.label}</div>
            <div className={state === "running" ? "animate-pulse" : ""}>{caption}</div>
          </li>
        );
      })}
    </ol>
  );
}

function StageCard({ s }: { s: Stage }) {
  if (!s.connected) {
    return (
      <div className="h-full rounded-xl border border-dashed border-line bg-panel/60 p-4 text-sm" data-testid={`stage-${s.key}`}>
        <h3 className="font-semibold text-ink-soft">{s.title}</h3>
        <p className="mt-1 text-xs font-medium uppercase tracking-wide text-ink-faint">Not linked yet</p>
        <p className="mt-2 text-xs text-ink-soft">{s.note}</p>
      </div>
    );
  }
  const dropped = s.entered - s.passed;
  return (
    <div className="h-full rounded-xl border border-line bg-panel p-4 text-sm shadow-card" data-testid={`stage-${s.key}`}>
      <h3 className="font-semibold">{s.title}</h3>
      {s.entered === 0 ? (
        <p className="mt-2 text-xs text-ink-soft">Nothing has reached this stage yet.</p>
      ) : (
        <>
          <p className="mt-1 text-2xl font-semibold tabular-nums">
            {s.entered} <span className="text-xs font-normal text-ink-soft">{s.unit} in</span>
          </p>
          <div className="mt-3 flex h-3 overflow-hidden rounded-full bg-slate-200" role="img" aria-label={`${s.passed} of ${s.entered} moved on, ${dropped} dropped`}>
            <div className="bg-emerald-500" style={{ width: `${share(s.passed, s.entered)}%` }} />
            <div className="bg-red-300" style={{ width: `${share(dropped, s.entered)}%` }} />
          </div>
          <p className="mt-2 flex justify-between text-xs">
            <span className="font-medium text-emerald-700">
              {s.passed} moved on ({share(s.passed, s.entered)}%)
            </span>
            <span className="font-medium text-red-700">
              {dropped} dropped ({share(dropped, s.entered)}%)
            </span>
          </p>
          {s.dropped.length > 0 ? (
            <ul className="mt-3 space-y-1.5 border-t border-line pt-3 text-xs">
              {s.dropped.map((d) => (
                <li key={d.reason}>
                  <div className="flex justify-between gap-3">
                    <span className="text-ink-soft">{d.reason}</span>
                    <span className="tabular-nums">{d.count}</span>
                  </div>
                  <div className="mt-0.5 h-1 rounded-full bg-slate-100">
                    <div className="h-1 rounded-full bg-red-300" style={{ width: `${share(d.count, s.entered)}%` }} />
                  </div>
                </li>
              ))}
            </ul>
          ) : null}
        </>
      )}
      <p className="mt-3 text-xs text-ink-faint">{s.note}</p>
    </div>
  );
}

/** The funnel: one card per stage, joined by arrows that say how many moved on to the next. */
export function Funnel({ stages }: { stages: Stage[] }) {
  return (
    <div className="grid items-stretch gap-3 lg:grid-cols-[repeat(6,1fr)]" aria-label="Research funnel">
      {stages.map((s, i) => (
        <div key={s.key} className="relative flex flex-col">
          <StageCard s={s} />
          {i < stages.length - 1 ? (
            <div className="py-1 text-center text-xs text-ink-faint lg:absolute lg:-right-3 lg:top-1/2 lg:z-10 lg:py-0" aria-hidden="true">
              <span className="lg:hidden">↓ {s.connected && s.entered > 0 ? `${s.passed} move on` : ""}</span>
              <span className="hidden rounded-full border border-line bg-panel px-1.5 py-0.5 lg:inline">→</span>
            </div>
          ) : null}
        </div>
      ))}
    </div>
  );
}
