from decimal import Decimal as D

from algo.sandbox.proxy import SandboxedProxy
from tests.support.adversarial import Counter, NoParams
from tests.unit.sandbox.helpers import ctx, sandbox


def test_the_proxy_takes_its_identity_from_the_strategy_and_its_decisions_from_the_worker():
    proxy = SandboxedProxy(Counter(NoParams()), sandbox("tests.support.adversarial:Counter"))
    try:
        assert (proxy.id, proxy.version) == ("adversarial", "1")  # in-process configuration
        assert proxy.requirements() == Counter(NoParams()).requirements()
        assert proxy.universe(ctx()) == [1]  # answered by the worker
        assert proxy.on_start(ctx()) is None
        assert proxy.on_schedule(ctx()) == {1: D("0.1"), 2: D("0.16")}  # day 16 of NOW
        assert proxy.on_schedule(ctx()) == {
            1: D("0.2"),
            2: D("0.16"),
        }  # the worker keeps its own state
    finally:
        proxy.close()
