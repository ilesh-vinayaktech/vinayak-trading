import { Badge } from "@/components/status/Badge";
import type { Dashboard } from "@/lib/schemas";

type Cards = NonNullable<Dashboard["scorecards"]>;

const TITLES: Record<keyof Cards, { title: string; question: string }> = {
  platform_correctness: { title: "Platform correctness", question: "Is what the platform computes and stores right?" },
  strategy_validity: { title: "Strategy validity", question: "Is there evidence that any strategy works?" },
  operational_reliability: { title: "Operational reliability", question: "Does it keep running?" },
};
const CARD_TONE = { OK: "good", ATTENTION: "warn", FAIL: "bad", INCOMPLETE: "neutral" } as const;
const ITEM_TONE = { PASS: "good", WARN: "warn", FAIL: "bad", UNKNOWN: "neutral" } as const;
const ITEM_WORD = { PASS: "pass", WARN: "warning", FAIL: "fail", UNKNOWN: "no evidence" } as const;

/** Three separate cards, never blended: a platform can be correct while no strategy is valid. Missing evidence is shown as such, never as a pass. */
export function Scorecards({ cards }: { cards: Cards }) {
  return (
    <div className="grid gap-4 md:grid-cols-3">
      {(Object.keys(TITLES) as (keyof Cards)[]).map((key) => {
        const card = cards[key];
        const { title, question } = TITLES[key];
        return (
          <section key={key} aria-label={title} className="rounded-xl border border-line bg-panel p-5 shadow-card">
            <h2 className="text-base font-semibold tracking-tight">{title}</h2>
            <p className="mb-3 text-xs text-ink-soft">{question}</p>
            <Badge tone={CARD_TONE[card.status]}>
              <span data-card-status>{card.status.toLowerCase()}</span>
            </Badge>
            <ul className="mt-3 space-y-2 text-sm">
              {card.items.map((i) => (
                <li key={i.name}>
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{i.name}</span>
                    <Badge tone={ITEM_TONE[i.status]}>
                      <span data-item-status>{ITEM_WORD[i.status]}</span>
                    </Badge>
                  </div>
                  <p className="text-xs text-ink-soft">{i.detail}</p>
                </li>
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}
