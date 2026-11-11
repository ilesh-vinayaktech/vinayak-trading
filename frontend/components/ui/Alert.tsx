import type { ReactNode } from "react";
import { Icon, type IconName } from "./Icon";

export type AlertTone = "info" | "warn" | "error" | "success";
const TONES: Record<AlertTone, { box: string; icon: IconName; role: "status" | "alert" }> = {
  info: { box: "border-blue-200 bg-blue-50 text-blue-900", icon: "info", role: "status" },
  success: { box: "border-emerald-200 bg-emerald-50 text-emerald-900", icon: "check", role: "status" },
  warn: { box: "border-amber-200 bg-amber-50 text-amber-900", icon: "alert", role: "status" },
  error: { box: "border-red-200 bg-red-50 text-red-900", icon: "alert", role: "alert" },
};

/** A message with an icon as well as colour (so meaning never depends on colour alone). Errors are announced as alerts. */
export function Alert({ tone = "info", title, children }: { tone?: AlertTone; title?: string; children?: ReactNode }) {
  const t = TONES[tone];
  return (
    <div role={t.role} className={`flex gap-3 rounded-lg border px-4 py-3 text-sm ${t.box}`}>
      <Icon name={t.icon} size={18} className="mt-0.5 shrink-0" />
      <div>
        {title ? <p className="font-medium">{title}</p> : null}
        {children ? <div className={title ? "mt-0.5" : ""}>{children}</div> : null}
      </div>
    </div>
  );
}

export function Avatar({ name }: { name: string }) {
  const initials = name.split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0]?.toUpperCase()).join("") || "?";
  return (
    <span aria-hidden="true" className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand text-xs font-semibold text-white">
      {initials}
    </span>
  );
}
