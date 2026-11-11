"use client";

import { useState } from "react";

/** A one-time link (invitation or reset) shown to the administrator, who passes it on if the mail does not arrive. */
export function CopyLink({ label, url }: { label: string; url: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="space-y-1 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm" role="status">
      <div className="font-medium">{label}</div>
      <code className="block break-all font-mono text-xs" data-testid="one-time-link">{url}</code>
      <button
        type="button"
        onClick={() => {
          void navigator.clipboard?.writeText(url);
          setCopied(true);
        }}
        className="rounded-md border border-line bg-white px-2 py-1 text-xs hover:bg-slate-50"
      >
        {copied ? "Copied" : "Copy link"}
      </button>
      <p className="text-xs text-amber-900">Anyone with this link can set the password for this account. It works once and expires.</p>
    </div>
  );
}
