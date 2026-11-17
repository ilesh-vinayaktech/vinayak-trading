"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { PageHeader } from "@/components/layout/PageHeader";
import { ErrorBox, Loading } from "@/components/status/LoadState";
import { Alert } from "@/components/ui/Alert";
import { Field } from "@/components/ui/Field";
import { Panel, StatusPill } from "@/components/ui/Layout";
import { buttonClass, inputFull } from "@/components/ui/styles";
import { useToast } from "@/components/ui/Toast";
import { ConfirmButton } from "@/components/users/ConfirmButton";
import { ApiError, api } from "@/lib/api/client";
import type { Regulatory, RegulatoryItem } from "@/lib/schemas";

const TONE = { ok: "good", stale: "warn", missing: "bad" } as const;
const WORD = { ok: "recorded", stale: "needs a re-check", missing: "not recorded" } as const;
const message = (e: unknown) => (e instanceof ApiError ? e.message : "Could not save. Try again.");
const FILL = "<fill in>";
const pretty = (v: unknown) => (v === null || v === undefined ? "" : JSON.stringify(v, null, 2));

/** The value is whatever the person read in the circular, typed as JSON; the page only checks that it parses and is not empty. */
function parse(text: string): { value: unknown } | { error: string } {
  if (text.trim() === "") return { error: "Write what the rule says." };
  try {
    const v: unknown = JSON.parse(text);
    if (v === null || v === "") return { error: "Write what the rule says." };
    return text.includes(FILL) ? { error: `Replace every ${FILL} with what the rule says.` } : { value: v };
  } catch {
    return { error: 'Not valid JSON. Example: {"orders_per_second": 10}, or a quoted sentence such as "Market orders need protection".' };
  }
}

function RecordForm({ item, today }: { item: RegulatoryItem; today: string }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [text, setText] = useState(pretty(item.value));
  const [source, setSource] = useState(item.source ?? "");
  const [effective, setEffective] = useState(item.effective_from ?? "");
  const parsed = parse(text);
  const problem = "error" in parsed ? parsed.error : null;
  const save = useMutation({
    mutationFn: () => api.recordRegulatory({ topic: item.topic, value: (parsed as { value: unknown }).value, source, effective_from: effective }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["regulatory"] });
      toast.success(`${item.label} recorded`);
    },
  });
  const ready = problem === null && source.trim() !== "" && effective !== "" && effective <= today;
  return (
    <div className="space-y-3">
      <Field id={`value-${item.topic}`} label="What the rule says (JSON)" error={text === "" ? null : problem} hint={
          <>
            Free-form: use any keys you like, with the figures or wording as the circular gives them. A suggested layout:{" "}
            <button type="button" className="underline" onClick={() => setText(pretty(item.example))}>
              use this layout
            </button>
            <pre className="mt-1 overflow-x-auto rounded border border-line bg-white p-2 font-mono text-xs">{pretty(item.example)}</pre>
          </>
        }>
        <textarea id={`value-${item.topic}`} className={`${inputFull} h-28 font-mono text-xs`} value={text} onChange={(e) => setText(e.target.value)} spellCheck={false} />
      </Field>
      <Field id={`source-${item.topic}`} label="Where you read it" hint="Circular number and date, or a link.">
        <input id={`source-${item.topic}`} className={inputFull} value={source} onChange={(e) => setSource(e.target.value)} maxLength={500} />
      </Field>
      <Field id={`effective-${item.topic}`} label="In force since" error={effective > today ? "That date has not come yet." : null}>
        <input id={`effective-${item.topic}`} type="date" className={inputFull} value={effective} max={today} onChange={(e) => setEffective(e.target.value)} />
      </Field>
      <button type="button" className={buttonClass("primary")} disabled={!ready || save.isPending} onClick={() => save.mutate()}>
        Record rule
      </button>
      {save.error ? <Alert tone="error">{message(save.error)}</Alert> : null}
    </div>
  );
}

function Verify({ item }: { item: RegulatoryItem }) {
  const qc = useQueryClient();
  const toast = useToast();
  const run = useMutation({
    mutationFn: () => api.verifyRegulatory(item.topic),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["regulatory"] });
      toast.success(`${item.label} checked again`);
    },
  });
  return (
    <>
      <ConfirmButton question="Have you read the current circular, and the rule is unchanged?" confirmLabel="Yes, unchanged" onConfirm={() => run.mutate()} disabled={run.isPending}>
        Re-check: nothing changed
      </ConfirmButton>
      {run.error ? <Alert tone="error">{message(run.error)}</Alert> : null}
    </>
  );
}

function Rule({ item, d }: { item: RegulatoryItem; d: Regulatory }) {
  const recorded = item.status !== "missing";
  return (
    <Panel title={item.label} actions={<StatusPill tone={TONE[item.status]}>{WORD[item.status]}</StatusPill>}>
      <div className="space-y-3 p-4">
        <p className="text-sm text-ink-soft">{item.help}</p>
        {recorded ? (
          <>
            <pre className="overflow-x-auto rounded-lg border border-line bg-white p-3 font-mono text-xs">{pretty(item.value)}</pre>
            <dl className="grid gap-2 text-sm sm:grid-cols-2">
              <div>
                <dt className="text-ink-soft">Source</dt>
                <dd>{item.source}</dd>
              </div>
              <div>
                <dt className="text-ink-soft">In force since</dt>
                <dd>{item.effective_from}</dd>
              </div>
              <div>
                <dt className="text-ink-soft">Last checked</dt>
                <dd>
                  {item.last_verified} by {item.verified_by} ({item.days_since} days ago)
                </dd>
              </div>
              <div>
                <dt className="text-ink-soft">{item.status === "stale" ? "Check was due" : "Check due by"}</dt>
                <dd>{item.expires_on}</dd>
              </div>
            </dl>
          </>
        ) : null}
        {d.can_edit ? (
          <div className="flex flex-wrap items-start gap-3">
            {recorded ? <Verify item={item} /> : null}
            <details className="w-full">
              <summary className="cursor-pointer text-sm font-medium">{recorded ? "The rule changed: record the new one" : "Record this rule"}</summary>
              <div className="mt-3">
                <RecordForm item={item} today={d.today} />
              </div>
            </details>
          </div>
        ) : null}
      </div>
    </Panel>
  );
}

export default function RegulatoryPage() {
  const q = useQuery({ queryKey: ["regulatory"], queryFn: api.regulatory });
  const d = q.data;
  return (
    <div className="space-y-4">
      <PageHeader title="Regulatory rules" subtitle="The exchange and broker rules live trading depends on. Nothing is fetched or guessed: you read the circular and record it here. Live trading stays blocked while any rule is missing or was last checked more than a month ago. Paper trading is not affected." />
      {q.isLoading ? <Loading what="the regulatory rules" /> : null}
      {q.error ? <ErrorBox error={q.error} what="the regulatory rules" /> : null}
      {d ? (
        <>
          {d.blocks_live ? (
            <Alert tone="warn" title="Live trading is blocked">
              <ul className="list-disc pl-5">
                {d.problems.map((p) => (
                  <li key={p}>{p.replace("regulatory: ", "")}</li>
                ))}
              </ul>
            </Alert>
          ) : (
            <Alert tone="success" title="Every rule is recorded and recent">
              Re-check each one within {d.max_age_days} days. Checked for {d.exchange} {d.segment} on {d.today}.
            </Alert>
          )}
          {d.can_edit ? null : <Alert tone="info">You can look at these rules. Recording or re-checking one needs an operator.</Alert>}
          {d.items.map((i) => (
            <Rule key={i.topic} item={i} d={d} />
          ))}
        </>
      ) : null}
    </div>
  );
}
