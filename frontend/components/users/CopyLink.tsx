"use client";

import { useState } from "react";
import { Icon } from "@/components/ui/Icon";
import { buttonClass } from "@/components/ui/styles";

/** A one-time link (invitation or reset) shown to the administrator, who passes it on if the mail does not arrive. */
export function CopyLink({ label, url }: { label: string; url: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="space-y-2 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm" role="status">
      <div className="flex items-center gap-2 font-medium text-amber-950">
        <Icon name="alert" size={16} /> {label}
      </div>
      <code className="block break-all rounded-md border border-amber-200 bg-white px-2.5 py-2 font-mono text-xs" data-testid="one-time-link">{url}</code>
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={() => {
            void navigator.clipboard?.writeText(url);
            setCopied(true);
          }}
          className={buttonClass("secondary", true)}
        >
          {copied ? "Copied" : "Copy link"}
        </button>
        <p className="text-xs text-amber-900">Anyone with this link can set the password for this account. It works once and expires.</p>
      </div>
    </div>
  );
}
