"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { PageHeader } from "@/components/layout/PageHeader";
import { Card, ErrorBox, Loading } from "@/components/status/LoadState";
import { api } from "@/lib/api/client";
import { fmtDateTime } from "@/lib/formatting";
import { inputClass } from "@/components/ui/styles";

const input = inputClass;

export default function AuditPage() {
  const [action, setAction] = useState("");
  const events = useQuery({ queryKey: ["audit", action], queryFn: () => api.audit({ action: action || undefined, limit: 100 }) });
  return (
    <div className="space-y-4">
      <PageHeader title="Audit log" subtitle="Every sign-in, access change and security event, newest first. It is append-only: entries cannot be edited or removed." />
      <Card title="Events">
        <div className="mb-3 space-y-1">
          <label htmlFor="action" className="text-sm font-medium">Show</label>
          <select id="action" value={action} onChange={(e) => setAction(e.target.value)} className={`${input} block`}>
            <option value="">Everything</option>
            <option value="auth.">Sign-in and security</option>
            <option value="user.">User administration</option>
          </select>
        </div>
        {events.isError ? <ErrorBox error={events.error} what="the audit log" /> : null}
        {events.isLoading ? <Loading what="events" /> : null}
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-xs text-ink-soft">
              <tr>
                <th className="py-2 pr-4 font-medium">When</th>
                <th className="py-2 pr-4 font-medium">Who</th>
                <th className="py-2 pr-4 font-medium">Action</th>
                <th className="py-2 pr-4 font-medium">Address</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {events.data?.events.map((e) => (
                <tr key={e.id}>
                  <td className="py-2 pr-4 whitespace-nowrap text-ink-soft">{fmtDateTime(e.at)}</td>
                  <td className="py-2 pr-4">{e.actor}</td>
                  <td className="py-2 pr-4 font-mono text-xs">{e.action}</td>
                  <td className="py-2 pr-4 text-ink-soft">{e.ip ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {events.data && events.data.events.length === 0 ? <p className="py-3 text-sm text-ink-soft">No events.</p> : null}
      </Card>
    </div>
  );
}
