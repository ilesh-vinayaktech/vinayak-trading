import type { Tone } from "@/components/status/Badge";
import type { TicketStatus, UserRow } from "@/lib/schemas";

export const statusTone = (s: UserRow["status"]): Tone => (s === "ACTIVE" ? "good" : s === "INVITED" ? "warn" : s === "SUSPENDED" ? "bad" : "neutral");

/** "user.role_changed" -> "Role changed" for the activity lists. */
export function actionLabel(action: string): string {
  const tail = action.split(".").slice(1).join(" ") || action;
  const text = tail.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export const ticketTone = (s: TicketStatus): Tone => (s === "OPEN" ? "warn" : s === "RESOLVED" ? "good" : "neutral");
