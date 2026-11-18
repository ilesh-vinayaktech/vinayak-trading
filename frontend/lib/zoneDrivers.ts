/** Plain-language words for each market-zone signal: a question, what is measured, and what a greedy or fearful reading means. */
export type DriverWords = { title: string; what: string; greed: string; fear: string };

export const DRIVER_WORDS: Record<string, DriverWords> = {
  momentum: {
    title: "Is the market trending up?",
    what: "The Nifty 500 against its average price over the last 6 months.",
    greed: "The market is well above its usual level: buyers are in control.",
    fear: "The market is below its usual level: sellers are in control.",
  },
  breadth: {
    title: "Are most stocks doing well?",
    what: "The share of stocks trading above their 50-day average price.",
    greed: "Most stocks are in an uptrend, so the rise is broad.",
    fear: "Most stocks are in a downtrend, so the weakness is broad.",
  },
  highs_lows: {
    title: "Winners or losers at the extremes?",
    what: "Stocks hitting a new 52-week high against stocks hitting a new 52-week low.",
    greed: "Far more stocks are hitting yearly highs than lows.",
    fear: "Far more stocks are hitting yearly lows than highs.",
  },
  volatility: {
    title: "Is the market calm or nervous?",
    what: "India VIX, the market's fear gauge. It rises when traders expect big swings.",
    greed: "Traders are calm: the fear gauge is low.",
    fear: "Traders are nervous: the fear gauge is high.",
  },
  advance_decline: {
    title: "More stocks up than down?",
    what: "Stocks that rose against stocks that fell, averaged over 10 days.",
    greed: "Gainers are beating losers day after day.",
    fear: "Losers are beating gainers day after day.",
  },
  stocks_vs_bonds: {
    title: "Stocks or safe government bonds?",
    what: "How shares have done against government bonds over 20 days. Bonds are where cautious money hides.",
    greed: "Money is moving into shares and away from safe bonds.",
    fear: "Money is hiding in safe bonds and leaving shares.",
  },
  risk_appetite: {
    title: "Are investors chasing risky stocks?",
    what: "Jumpy (high-beta) stocks against steady (low-volatility) stocks over 20 days.",
    greed: "Investors prefer the jumpy, high-reward stocks.",
    fear: "Investors prefer steady, defensive stocks.",
  },
  size_appetite: {
    title: "Small companies or big ones?",
    what: "Small-company stocks against large-company stocks over 20 days. Small caps do best when people feel bold.",
    greed: "Small, riskier companies are beating the big ones.",
    fear: "Investors are sticking to the big, safer companies.",
  },
  gold_demand: {
    title: "Are investors running to gold?",
    what: "Shares against gold over 10 days. Gold is the classic safe haven.",
    greed: "Shares are beating gold: nobody is rushing for safety.",
    fear: "Gold is beating shares: people are seeking safety.",
  },
  fii_positioning: {
    title: "What are foreign investors betting on?",
    what: "Foreign institutions' open bets in Nifty futures: bets on a rise minus bets on a fall.",
    greed: "Foreign institutions are leaning towards a rise.",
    fear: "Foreign institutions are leaning towards a fall.",
  },
};

const FALLBACK: DriverWords = { title: "", what: "", greed: "This signal is pushing towards greed.", fear: "This signal is pushing towards fear." };

/** How far a 0 to 100 score is from neutral, as the points it adds to (or takes from) the overall score when `count` signals are averaged. */
export const pointsFromNeutral = (score: number, count: number) => (count > 0 ? (score - 50) / count : 0);

export function effectText(key: string, score: number): { text: string; lean: "greed" | "fear" | "neutral"; strength: string } {
  const w = DRIVER_WORDS[key] ?? FALLBACK;
  if (score >= 70) return { text: w.greed, lean: "greed", strength: "Strongly greedy" };
  if (score >= 55) return { text: w.greed, lean: "greed", strength: "Leaning greedy" };
  if (score > 45) return { text: "Nothing unusual here: it is close to its normal level.", lean: "neutral", strength: "Normal" };
  if (score > 30) return { text: w.fear, lean: "fear", strength: "Leaning fearful" };
  return { text: w.fear, lean: "fear", strength: "Strongly fearful" };
}
