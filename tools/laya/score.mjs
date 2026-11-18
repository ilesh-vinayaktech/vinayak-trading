// Score market headlines with Laya (local ONNX model, no API key, nothing leaves this machine).
// stdin: a JSON array of {id, text}. stdout: a JSON array of {id, sentiment, confidence, pick, up, down}.
//   sentiment: -1 (bad for the share price) .. +1 (good), the mean of two independent readings of the same headline:
//     pick = P(positive) - P(negative) from a three-way choice (negative / neutral / positive), and up - down from two yes/no questions.
//   confidence: the model's own probability for its three-way choice (0..1): a headline it is unsure about has a low one.
// Chosen on 38 headlines labelled by hand (see TODO 6.14): the single five-step rubric did worse (61% right) than the keyword list (74%); this combination got 82%.
// usage: node score.mjs < headlines.json
import { Laya } from "@receptron/laya";

const QUESTIONS = {
  pick: {
    type: "choice",
    instructions: "Is this news good or bad for the share prices of the companies or the market it is about? Pick neutral if it is only a listing, a recommendation list, a guide, or has no clear effect.",
    criteria: {
      negative: "bad for share prices: falls, losses, selloffs, outflows, warnings, downgrades, weak earnings",
      neutral: "no clear effect: lists, previews, guides, routine filings, mixed or unrelated",
      positive: "good for share prices: gains, record highs, inflows, upgrades, buy calls, strong earnings, oversubscribed issues",
    },
  },
  up: { type: "noul", instructions: "Will this news push share prices up?" },
  down: { type: "noul", instructions: "Will this news push share prices down?" },
};

const chunks = [];
for await (const c of process.stdin) chunks.push(c);
const items = JSON.parse(Buffer.concat(chunks).toString("utf8"));
if (items.length === 0) {
  process.stdout.write("[]");
  process.exit(0);
}
const laya = await Laya.load({ cacheDir: process.env.LAYA_CACHE ?? undefined });
const clamp = (x) => Math.max(-1, Math.min(1, x));
const out = [];
for (const { id, text } of items) {
  const a = (await laya.systemOne({ headline: text }, QUESTIONS)).answers;
  const pick = a.pick.probabilities.positive - a.pick.probabilities.negative;
  const upDown = a.up.noul - a.down.noul;
  out.push({ id, sentiment: clamp((pick + upDown) / 2), confidence: a.pick.answer_confidence, pick, up: a.up.noul, down: a.down.noul });
}
process.stdout.write(JSON.stringify(out));
