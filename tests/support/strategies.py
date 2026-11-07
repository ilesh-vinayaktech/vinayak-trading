"""Small reference strategies used to test the platform (not trading ideas)."""

from decimal import Decimal

from algo.strategy.base import Requirements, Strategy, StrategyParams


class HoldParams(StrategyParams):
    ids: tuple[int, ...]
    weights: tuple[Decimal, ...]
    lookback: int = 30


class HoldWeights(Strategy):
    """Buy and hold fixed target weights. Also records what the Context showed it."""

    id, version, Params = "hold", "1", HoldParams

    def __init__(self, params):
        super().__init__(params)
        self.seen = []  # (now, {iid: last bar ts})

    def universe(self, ctx):
        return list(self.params.ids)

    def requirements(self):
        return Requirements(lookback_days=self.params.lookback)

    def on_schedule(self, ctx):
        h = ctx.data.history(self.params.ids, self.params.lookback)
        self.seen.append((ctx.now(), {i: bars[-1].ts for i, bars in h.items() if bars}))
        return dict(zip(self.params.ids, self.params.weights, strict=True))


class Scripted(Strategy):
    """Returns pre-baked targets per call, for testing the engine's handling of them."""

    id, version, Params = "scripted", "1", HoldParams

    def __init__(self, params, script):
        super().__init__(params)
        self.script, self.calls = list(script), 0

    def universe(self, ctx):
        return list(self.params.ids)

    def on_schedule(self, ctx):
        self.calls += 1
        return self.script.pop(0) if self.script else None
