"""Strategies that misbehave on purpose. The sandbox must stop each one without hurting the platform."""

import os
import socket
from decimal import Decimal

from algo.strategy.base import Strategy, StrategyParams


class NoParams(StrategyParams):
    pass


class _Base(Strategy):
    id, version, Params = "adversarial", "1", NoParams

    def universe(self, ctx):
        return [1]

    def on_schedule(self, ctx):
        return None


class Honest(_Base):
    def on_schedule(self, ctx):
        print("this goes to stderr, not into the protocol")
        return {1: Decimal("0.5")}


class OpensASocket(_Base):
    def on_schedule(self, ctx):
        socket.create_connection(("1.1.1.1", 80), timeout=1)


class ReadsSecrets(_Base):
    def on_schedule(self, ctx):
        return {1: Decimal(len(open(os.path.expanduser("~/.ssh/id_rsa")).read()))}


class ReadsTheProjectEnvFile(_Base):
    path = ""

    def on_schedule(self, ctx):
        return {1: Decimal(len(open(self.path).read()))}


class WritesAFile(_Base):
    def on_schedule(self, ctx):
        with open("/tmp/sandbox-escape.txt", "w") as f:
            f.write("x")


class RunsACommand(_Base):
    def on_schedule(self, ctx):
        os.system("echo hello > /tmp/sandbox-escape.txt")


class ForkBomb(_Base):
    def on_schedule(self, ctx):
        while True:
            os.fork()


class SpinsForever(_Base):
    def on_schedule(self, ctx):
        while True:
            pass


class EatsMemory(_Base):
    def on_schedule(self, ctx):
        return {1: Decimal(len(bytearray(8 * 1024**3)))}


class SwallowsTheViolation(_Base):
    def on_schedule(self, ctx):
        try:
            open("/etc/passwd").read()
        except BaseException:  # noqa: BLE001, S110
            pass
        return {1: Decimal(1)}


class DiesSuddenly(_Base):
    def on_schedule(self, ctx):
        os._exit(3)


class RaisesNormally(_Base):
    def on_schedule(self, ctx):
        raise ValueError("a plain bug")


class ReturnsGarbage(_Base):
    def on_schedule(self, ctx):
        return {"INFY": 0.5}


class ReadsEnvironment(_Base):
    def on_schedule(self, ctx):
        return {1: Decimal(len(os.environ))}


class ConnectsToTheDatabase(_Base):
    def on_schedule(self, ctx):
        import psycopg  # the platform already loaded it, so only the network can stop this

        psycopg.connect("postgresql://postgres:postgres@127.0.0.1:5433/algo", connect_timeout=2)


class Counter(_Base):
    """Stateful: what it holds is what it has been asked so far, and it must survive a restart."""

    def __init__(self, params):
        super().__init__(params)
        self.calls = 0

    def on_schedule(self, ctx):
        self.calls += 1
        return {1: Decimal(self.calls) / 10, 2: Decimal(ctx.now().day) / 100}

    def get_state(self):
        return {"calls": self.calls}

    def set_state(self, state):
        self.calls = state["calls"]


class ReadsTheClockSneakily(_Base):
    """Not found by the source scan (the module is bound to a short name), so the runtime patch has to stop it."""

    def on_schedule(self, ctx):
        t = __import__("time")
        return {1: Decimal(t.time())}
