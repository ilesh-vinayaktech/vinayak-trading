"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { PageHeader } from "@/components/layout/PageHeader";
import { Badge } from "@/components/status/Badge";
import { ErrorBox, Loading } from "@/components/status/LoadState";
import { Alert } from "@/components/ui/Alert";
import { EmptyState } from "@/components/ui/DataTable";
import { Field } from "@/components/ui/Field";
import { Panel } from "@/components/ui/Layout";
import { buttonClass, inputFull, inputClass } from "@/components/ui/styles";
import { api } from "@/lib/api/client";
import { fmtDateTime } from "@/lib/formatting";
import type { ReviewItem } from "@/lib/schemas";

const REVIEWER_KEY = "reviewer:v1";
const FILTERS = ["open", "decided", "all"] as const;
type Filter = (typeof FILTERS)[number];
const field = inputFull;

function isDecided(i: ReviewItem): boolean {
  return i.latest !== null && i.latest.decision !== "NEEDS_MORE_EVIDENCE";
}

export default function ReviewsPage() {
  const q = useQuery({ queryKey: ["reviews"], queryFn: api.reviews });
  const [filter, setFilter] = useState<Filter>("open");
  const [kind, setKind] = useState("all");
  const items = q.data?.items ?? [];
  const kinds = [...new Set(items.map((i) => i.kind))];
  const shown = items.filter(
    (i) =>
      (filter === "all" || (filter === "decided") === isDecided(i)) &&
      (kind === "all" || i.kind === kind),
  );

  return (
    <div className="space-y-4">
      <PageHeader
        title="Reviews"
        subtitle="Decisions only a person can make. Each is recorded with who, when and the evidence; nothing here changes identity or membership data by itself."
      />
      {q.isLoading ? <Loading what="review items" /> : null}
      {q.error ? <ErrorBox error={q.error} what="review items" /> : null}
      {q.data ? (
        <>
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <span data-testid="progress">
              {q.data.decided} of {q.data.total} decided
            </span>
            <div className="flex gap-1" role="group" aria-label="Filter">
              {FILTERS.map((f) => (
                <button
                  key={f}
                  type="button"
                  aria-pressed={filter === f}
                  onClick={() => setFilter(f)}
                  className={buttonClass(
                    filter === f ? "primary" : "secondary",
                    true,
                  )}
                >
                  {f}
                </button>
              ))}
            </div>
            <select
              aria-label="Kind"
              value={kind}
              onChange={(e) => setKind(e.target.value)}
              className={inputClass}
            >
              <option value="all">all kinds</option>
              {kinds.map((k) => (
                <option key={k} value={k}>
                  {k.replaceAll("_", " ").toLowerCase()}
                </option>
              ))}
            </select>
          </div>
          {!q.data.writes_enabled ? (
            <Alert tone="warn">
              Saving is switched off on this server. Start the API with
              ALGO_REVIEW_WRITES=1 to record decisions.
            </Alert>
          ) : null}
          {shown.length === 0 ? (
            <Panel>
              <EmptyState icon="tasks" title="Nothing in this view">
                Try another filter.
              </EmptyState>
            </Panel>
          ) : null}
          {shown.map((i) => (
            <ItemCard key={i.id} item={i} writable={q.data.writes_enabled} />
          ))}
        </>
      ) : null}
    </div>
  );
}

function ItemCard({ item, writable }: { item: ReviewItem; writable: boolean }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [reviewer, setReviewer] = useState("");
  const [decision, setDecision] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [evidence, setEvidence] = useState("");
  const [note, setNote] = useState("");
  const [showHistory, setShowHistory] = useState(false);
  useEffect(() => {
    try {
      setReviewer(window.localStorage.getItem(REVIEWER_KEY) ?? "");
    } catch {
      /* no storage: the name is simply typed each time */
    }
  }, []);
  const opt = item.options.find((o) => o.value === decision);
  const history = useQuery({
    queryKey: ["review-history", item.id],
    queryFn: () => api.reviewHistory(item.id),
    enabled: showHistory,
  });
  const save = useMutation({
    mutationFn: () =>
      api.decideReview(item.id, {
        decision,
        reviewer,
        effective_date: opt?.needs_date ? from || undefined : undefined,
        effective_to: opt?.has_end ? to || undefined : undefined,
        evidence_ref: evidence,
        note,
      }),
    onSuccess: () => {
      try {
        window.localStorage.setItem(REVIEWER_KEY, reviewer);
      } catch {
        /* ignore */
      }
      setDecision("");
      setFrom("");
      setTo("");
      setEvidence("");
      setNote("");
      void qc.invalidateQueries({ queryKey: ["reviews"] });
      void qc.invalidateQueries({ queryKey: ["review-history", item.id] });
    },
  });
  const ready =
    writable &&
    reviewer.trim() !== "" &&
    opt !== undefined &&
    (!opt.needs_date || from !== "") &&
    (opt.needs_evidence === false || evidence.trim() !== "");
  const l = item.latest;

  return (
    <section
      className="rounded-xl border border-line bg-panel p-5 shadow-card"
      aria-label={item.title}
    >
      <button
        type="button"
        className="flex w-full items-start justify-between gap-3 text-left"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        <span>
          <span className="block text-sm font-semibold">{item.title}</span>
          <span className="block text-xs text-ink-soft">{item.question}</span>
        </span>
        <span className="flex shrink-0 items-center gap-2">
          <Badge tone="neutral">
            {item.category.replaceAll("_", " ").toLowerCase()}
          </Badge>
          {l ? (
            <Badge tone={isDecided(item) ? "good" : "warn"}>
              {item.options
                .find((o) => o.value === l.decision)
                ?.label.split(":")[0] ?? l.decision}
            </Badge>
          ) : (
            <Badge tone="warn">open</Badge>
          )}
        </span>
      </button>
      {open ? (
        <div className="mt-3 space-y-3">
          <dl className="grid gap-x-4 gap-y-1 text-xs md:grid-cols-[10rem_1fr]">
            {Object.entries(item.context).map(([k, v]) => (
              <div key={k} className="contents">
                <dt className="text-ink-soft">{k}</dt>
                <dd className="break-words">{v}</dd>
              </div>
            ))}
            {item.leads.length ? (
              <>
                <dt className="text-ink-soft">Read these releases</dt>
                <dd className="break-words font-mono">
                  {item.leads.join(", ")}{" "}
                  (data/lake/raw/niftyindices/&lt;id&gt;)
                </dd>
              </>
            ) : null}
          </dl>
          {l ? (
            <p className="rounded bg-slate-50 p-2 text-xs">
              Latest: <b>{l.decision}</b>
              {l.effective_date ? ` from ${l.effective_date}` : ""}
              {l.effective_to ? ` to ${l.effective_to}` : ""} by {l.reviewer},{" "}
              {fmtDateTime(l.decided_at)}. Evidence: {l.evidence_ref || "none"}.{" "}
              {l.note}
            </p>
          ) : null}
          <div className="grid gap-3 md:grid-cols-2">
            <div>
              <Field id={`${item.id}-decision`} label={"Decision"}>
                <select
                  id={`${item.id}-decision`}
                  className={field}
                  value={decision}
                  onChange={(e) => setDecision(e.target.value)}
                  disabled={!writable}
                >
                  <option value="">Choose…</option>
                  {item.options.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
            <div>
              <Field id={`${item.id}-name`} label={"Your name"}>
                <input
                  id={`${item.id}-name`}
                  className={field}
                  value={reviewer}
                  onChange={(e) => setReviewer(e.target.value)}
                  disabled={!writable}
                />
              </Field>
            </div>
            {opt?.needs_date ? (
              <div>
                <Field
                  id={`${item.id}-date`}
                  label={opt.date_label ?? "Effective date"}
                >
                  <input
                    id={`${item.id}-date`}
                    type="date"
                    className={field}
                    value={from}
                    onChange={(e) => setFrom(e.target.value)}
                  />
                </Field>
              </div>
            ) : null}
            {opt?.has_end ? (
              <div>
                <Field
                  id={`${item.id}-until`}
                  label={"Until (exclusive, optional)"}
                >
                  <input
                    id={`${item.id}-until`}
                    type="date"
                    className={field}
                    value={to}
                    min={from}
                    onChange={(e) => setTo(e.target.value)}
                  />
                </Field>
              </div>
            ) : null}
            <div className="md:col-span-2">
              <Field
                id={`${item.id}-evidence`}
                label={`Evidence: document id, URL and page${opt?.needs_evidence === false ? " (optional)" : ""}`}
              >
                <input
                  id={`${item.id}-evidence`}
                  className={field}
                  value={evidence}
                  onChange={(e) => setEvidence(e.target.value)}
                  placeholder="e.g. pr_ind_prs17072023, p.3 or https://…"
                  disabled={!writable}
                />
              </Field>
            </div>
            <div className="md:col-span-2">
              <Field id={`${item.id}-note`} label={"Description / reasoning"}>
                <textarea
                  id={`${item.id}-note`}
                  className={field}
                  rows={3}
                  maxLength={4000}
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  disabled={!writable}
                />
              </Field>
            </div>
          </div>
          {save.error ? (
            <Alert tone="error">
              {String(
                save.error instanceof Error ? save.error.message : save.error,
              )}
            </Alert>
          ) : null}
          <div className="flex items-center gap-3">
            <button
              type="button"
              disabled={!ready || save.isPending}
              onClick={() => save.mutate()}
              className={buttonClass("primary")}
            >
              {save.isPending ? "Saving…" : "Save decision"}
            </button>
            <button
              type="button"
              className="text-xs underline"
              onClick={() => setShowHistory(!showHistory)}
            >
              {showHistory ? "Hide history" : "History"}
            </button>
          </div>
          {showHistory ? (
            <ul className="space-y-1 text-xs">
              {(history.data ?? []).map((h) => (
                <li key={h.decision_id}>
                  {fmtDateTime(h.decided_at)} · {h.reviewer} ·{" "}
                  <b>{h.decision}</b>
                  {h.effective_date ? ` from ${h.effective_date}` : ""} ·{" "}
                  {h.evidence_ref || "no evidence"} · {h.note}
                </li>
              ))}
              {history.data?.length === 0 ? <li>No decisions yet.</li> : null}
            </ul>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
