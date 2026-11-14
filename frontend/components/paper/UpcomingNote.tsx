import { fmtMoney } from "@/lib/formatting";
import type { PaperOrder } from "@/lib/schemas";

type Coming = PaperOrder["upcoming"][number];

const describe = (u: Coming) => (u.amount && u.kind === "dividend" ? `dividend ₹${fmtMoney(u.amount)} a share` : u.kind);

/** Corporate actions NSE has announced for a stock, a few days before they happen. Nothing is adjusted yet. */
export function UpcomingNote({ items }: { items: Coming[] }) {
  if (items.length === 0) return null;
  return (
    <ul className="mt-1 space-y-0.5 text-xs font-normal text-amber-700" aria-label="Announced corporate actions">
      {items.map((u) => (
        <li key={`${u.ex_date}-${u.kind}-${u.subject ?? ""}`} title={u.subject ?? undefined}>
          Ex-date {u.ex_date}: {describe(u)}
          {u.status === "review" ? " (needs checking)" : ""}
        </li>
      ))}
    </ul>
  );
}
