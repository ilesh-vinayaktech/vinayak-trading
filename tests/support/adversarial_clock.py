"""A strategy that reads the system clock: refused before it ever runs."""

import time

from tests.support.adversarial import _Base


class ReadsTheClock(_Base):
    def on_schedule(self, ctx):
        return {1: time.time()}
