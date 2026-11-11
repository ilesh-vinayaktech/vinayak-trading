/** One source for control styling, so every screen's inputs and buttons look and behave the same. */

/** Text inputs, selects and textareas. Width is left to the caller (or use `inputFull`). */
export const inputClass =
  "rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-ink shadow-sm placeholder:text-ink-faint focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand/25 disabled:bg-slate-50 disabled:text-ink-faint";
export const inputFull = `${inputClass} block w-full`;

export type ButtonVariant = "primary" | "secondary" | "danger" | "ghost";
const VARIANTS: Record<ButtonVariant, string> = {
  primary: "bg-brand text-white shadow-sm hover:bg-brand-dark",
  secondary: "border border-slate-300 bg-white text-ink shadow-sm hover:bg-slate-50",
  danger: "bg-red-600 text-white shadow-sm hover:bg-red-700",
  ghost: "text-ink-soft hover:bg-slate-100 hover:text-ink",
};
export function buttonClass(variant: ButtonVariant = "primary", small = false): string {
  return `inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${small ? "px-2.5 py-1 text-xs" : "px-3.5 py-2 text-sm"} ${VARIANTS[variant]}`;
}
