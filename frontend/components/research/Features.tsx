import { StatusPill } from "@/components/ui/Layout";
import type { IntelFeatures, IntelProgress } from "@/lib/schemas";

type Feature = IntelFeatures["features"][number];
type Job = IntelProgress["jobs"][number];

const CHECKS: {
  key: keyof NonNullable<Feature["validation"]>["checks"];
  label: string;
}[] = [
  { key: "coverage", label: "Enough values" },
  { key: "reproducible", label: "Same on a second read" },
  { key: "stored_match", label: "Stored months agree" },
  { key: "no_lookahead", label: "No look-ahead" },
];
const day = (iso: string) => iso.replace("T", " ").slice(0, 16);

/** The feature being validated right now, read from the running validation job's phase ("checking ret_20d"). */
export function checkingNow(
  jobs: Job[],
): { name: string; message: string } | null {
  const run = jobs.find(
    (j) => j.job === "feature_validation" && j.status === "RUNNING",
  );
  const m = run?.phase.match(/^checking (\S+)$/);
  return run && m?.[1] ? { name: m[1], message: run.message } : null;
}

function Row({
  f,
  now,
}: {
  f: Feature;
  now: { name: string; message: string } | null;
}) {
  const checking = now?.name === f.name;
  const v = f.validation;
  const tone = checking
    ? "info"
    : f.status === "USABLE"
      ? "good"
      : f.status === "BLOCKED" || (v && !v.passed)
        ? "bad"
        : "neutral";
  const word = checking
    ? "Checking now"
    : f.status === "USABLE"
      ? "Usable"
      : f.status === "BLOCKED"
        ? "Blocked"
        : f.status === "NOT_REGISTERED"
          ? "Not stored yet"
          : v
            ? v.passed
              ? "Passed, not set usable"
              : "Failed"
            : "Not validated yet";
  return (
    <li
      className={`space-y-2 px-5 py-4 text-sm ${checking ? "bg-blue-50/60" : ""}`}
      data-testid={`feature-${f.name}`}
      data-state={
        checking
          ? "checking"
          : v
            ? v.passed
              ? "passed"
              : "failed"
            : "unchecked"
      }
    >
      <div className="flex flex-wrap items-center gap-3">
        <span className="font-mono text-sm font-semibold">{f.name}</span>
        <span
          className="rounded border border-line px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-ink-faint"
          data-testid="family"
        >
          {f.family}
        </span>
        <StatusPill tone={tone}>{word}</StatusPill>
        <span className="text-xs text-ink-faint">
          needs {f.warmup} days of history ·{" "}
          {f.validations === 0
            ? "never validated"
            : `validated ${f.validations} time${f.validations === 1 ? "" : "s"}`}
        </span>
        {v ? (
          <span className="ml-auto text-xs text-ink-faint">
            last checked {day(v.at ?? "")}
          </span>
        ) : null}
      </div>
      <p className="text-ink-soft">
        <span className="text-ink-faint">Measures: </span>
        {f.measures}{" "}
        <span className="text-ink-faint">
          ({f.unit}, from {f.inputs.join(", ")})
        </span>
      </p>
      {checking && now ? (
        <p className="text-xs text-blue-800">
          Being checked now: {now.message || "starting"}
        </p>
      ) : null}
      {v ? (
        <>
          <ul
            className="flex flex-wrap gap-2 text-xs"
            aria-label={`${f.name} checks`}
          >
            {CHECKS.map((c) => (
              <li
                key={c.key}
                title={v.checks[c.key].detail}
                className={`rounded-full border px-2 py-0.5 ${v.checks[c.key].ok ? "border-emerald-300 bg-emerald-50 text-emerald-800" : "border-red-300 bg-red-50 text-red-800"}`}
              >
                {v.checks[c.key].ok ? "✓" : "✗"} {c.label}
              </li>
            ))}
          </ul>
          {v.reasons.length > 0 ? (
            <ul className="list-disc space-y-0.5 pl-5 text-xs text-red-800">
              {v.reasons.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          ) : (
            <p className="text-xs text-ink-faint">
              {v.checks.coverage.detail}.
            </p>
          )}
        </>
      ) : null}
      {f.status_reason && f.status !== "NOT_REGISTERED" ? (
        <p className="text-xs text-ink-faint">Status note: {f.status_reason}</p>
      ) : null}
    </li>
  );
}

/** Every feature defined in code, what it measures, and the latest validation: which of the four checks passed, why a failure failed, and which feature is being checked now. */
export function FeatureList({
  features,
  jobs,
}: {
  features: Feature[];
  jobs: Job[];
}) {
  const now = checkingNow(jobs);
  return (
    <ul className="divide-y divide-line" aria-label="Features">
      {features.map((f) => (
        <Row key={`${f.name}@${f.version}`} f={f} now={now} />
      ))}
    </ul>
  );
}
