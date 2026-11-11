"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { PageHeader } from "@/components/layout/PageHeader";
import { Alert } from "@/components/ui/Alert";
import { DataTable, EmptyState, Skeleton, type Column } from "@/components/ui/DataTable";
import { Dialog } from "@/components/ui/Dialog";
import { Field } from "@/components/ui/Field";
import { Panel, StatusPill } from "@/components/ui/Layout";
import { buttonClass, inputFull } from "@/components/ui/styles";
import { useToast } from "@/components/ui/Toast";
import { ConfirmButton } from "@/components/users/ConfirmButton";
import { ApiError, api } from "@/lib/api/client";
import { useAuth } from "@/lib/auth";
import type { MarketCalendar } from "@/lib/schemas";

type Row = MarketCalendar["exceptions"][number];
const fmtDay = (iso: string) => new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
const message = (e: unknown) => (e instanceof ApiError ? e.message : "Could not save. Try again.");

function AddDialog({ open, onClose, day: presetDay }: { open: boolean; onClose: () => void; day: string }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [day, setDay] = useState(presetDay);
  const [start, setStart] = useState("09:15");
  const [end, setEnd] = useState("15:30");
  const [note, setNote] = useState("");
  const [shownFor, setShownFor] = useState(presetDay);
  if (presetDay !== shownFor) {
    // the dialog was opened for another day (from "Add hours"): start from that day
    setShownFor(presetDay);
    setDay(presetDay);
  }
  const add = useMutation({
    mutationFn: () => api.addMarketSession({ day, start, end, note }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["market"] });
      toast.success(`Session added for ${fmtDay(day)}.`);
      onClose();
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    add.mutate();
  };
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Add a special session"
      description="Times are Indian Standard Time. On this date the live feed follows these hours instead of the regular session."
      footer={
        <>
          <button type="button" onClick={onClose} className={buttonClass("secondary")}>Cancel</button>
          <button type="submit" form="session-form" disabled={add.isPending} className={buttonClass("primary")}>Add session</button>
        </>
      }
    >
      <form id="session-form" onSubmit={submit} className="space-y-4">
        {add.isError ? <Alert tone="error">{message(add.error)}</Alert> : null}
        <Field id="ses-day" label="Date">
          <input id="ses-day" type="date" required value={day} onChange={(e) => setDay(e.target.value)} className={inputFull} />
        </Field>
        <div className="grid grid-cols-2 gap-4">
          <Field id="ses-start" label="Starts">
            <input id="ses-start" type="time" required value={start} onChange={(e) => setStart(e.target.value)} className={inputFull} />
          </Field>
          <Field id="ses-end" label="Ends">
            <input id="ses-end" type="time" required value={end} onChange={(e) => setEnd(e.target.value)} className={inputFull} />
          </Field>
        </div>
        <Field id="ses-note" label="Note" hint="For example: Diwali Muhurat trading.">
          <input id="ses-note" maxLength={300} value={note} onChange={(e) => setNote(e.target.value)} className={inputFull} />
        </Field>
      </form>
    </Dialog>
  );
}

export default function MarketPage() {
  const { can } = useAuth();
  const write = can("ops:write");
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({ queryKey: ["market"], queryFn: api.marketCalendar });
  const [dialog, setDialog] = useState<{ open: boolean; day: string }>({ open: false, day: "" });
  const remove = useMutation({
    mutationFn: (id: number) => api.removeMarketSession(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["market"] });
      toast.success("Entry removed.");
    },
  });
  const d = q.data;
  const need = d?.exceptions.filter((r) => r.needs_times) ?? [];
  const columns: Column<Row>[] = [
    { key: "day", header: "Date", cell: (r) => <span className="whitespace-nowrap font-medium">{fmtDay(r.day)}</span> },
    { key: "type", header: "Type", cell: (r) => (r.kind === "SESSION" ? <StatusPill tone="info">Special session</StatusPill> : <StatusPill tone="neutral">Closed</StatusPill>) },
    { key: "hours", header: "Hours (IST)", cell: (r) => (r.start && r.end ? `${r.start} to ${r.end}` : <span className="text-ink-faint">No trading</span>) },
    {
      key: "note",
      header: "Note",
      hideBelow: "sm",
      cell: (r) => (
        <span className="flex flex-wrap items-center gap-2">
          {r.note.replace(/\*$/, "") || <span className="text-ink-faint">None</span>}
          {r.needs_times ? <StatusPill tone="warn">Hours needed</StatusPill> : null}
        </span>
      ),
    },
    { key: "source", header: "Source", hideBelow: "md", cell: (r) => (r.source === "nse" ? "NSE list" : "Added by hand") },
    {
      key: "action",
      header: "",
      className: "text-right",
      cell: (r) =>
        write ? (
          <span className="inline-flex gap-2">
            {r.needs_times ? <button type="button" onClick={() => setDialog({ open: true, day: r.day })} className={buttonClass("secondary", true)}>Add hours</button> : null}
            <ConfirmButton question={`Remove the entry for ${fmtDay(r.day)}?`} confirmLabel="Remove" tone="danger" onConfirm={() => remove.mutate(r.id)}>Remove</ConfirmButton>
          </span>
        ) : null,
    },
  ];
  return (
    <div className="space-y-6">
      <PageHeader
        title="Trading calendar"
        subtitle="When the live feed streams. Regular days follow 09:15 to 15:30 IST, Monday to Friday; holidays and special sessions below change that for their date."
        actions={write ? <button type="button" onClick={() => setDialog({ open: true, day: "" })} className={buttonClass("primary")}>Add special session</button> : null}
      />
      {q.isError ? <Alert tone="error" title="Could not load the calendar">Try again in a moment.</Alert> : null}
      {q.isLoading ? <div role="status" aria-label="Loading the calendar"><Skeleton className="h-24 w-full" /></div> : null}
      {d ? (
        <>
          <Panel title="Today">
            <p className="px-5 py-4 text-sm" data-testid="today">
              {fmtDay(d.today.day)}:{" "}
              {d.today.windows.length === 0 ? <span className="font-medium">no trading, the feed stays idle</span> : <span className="font-medium">{d.today.windows.map((w) => `${w.start} to ${w.end}`).join(" and ")} IST</span>}
            </p>
          </Panel>
          {need.length > 0 ? (
            <Alert tone="warn" title={need.length === 1 ? "1 special session needs its hours" : `${need.length} special sessions need their hours`}>
              NSE lists {need.map((r) => fmtDay(r.day)).join(", ")} as a special session but announces the hours later. Until you add them the feed stays idle that day.
            </Alert>
          ) : null}
          <Panel title="Upcoming exceptions">
            <DataTable caption="Upcoming holidays and special sessions" columns={columns} rows={d.exceptions} rowKey={(r) => String(r.id)} empty={<EmptyState icon="calendar" title="No exceptions">Until NSE lists a holiday or you add a special session, every Monday to Friday is a regular session.</EmptyState>} />
          </Panel>
          {remove.isError ? <Alert tone="error">{message(remove.error)}</Alert> : null}
        </>
      ) : null}
      <AddDialog open={dialog.open} day={dialog.day} onClose={() => setDialog((s) => ({ ...s, open: false }))} />
    </div>
  );
}
