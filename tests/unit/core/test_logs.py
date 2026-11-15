import json
import logging
from datetime import UTC, datetime

import pytest

from algo.core import logs
from algo.core.clock import SimClock

T = datetime(2026, 11, 15, 9, 30, tzinfo=UTC)


def capture():
    out: list[str] = []

    class H(logging.Handler):
        def emit(self, record):
            out.append(self.format(record))

    h = H()
    h.setFormatter(logs.JsonFormatter(SimClock(T)))
    log = logging.getLogger(f"t.{id(out)}")
    log.handlers, log.propagate = [h], False
    log.setLevel(logging.DEBUG)
    return log, out


def test_a_line_is_one_json_object_with_the_schema_fields_and_the_injected_time():
    log, out = capture()
    log.warning("order rejected: %s", "no cash")
    doc = json.loads(out[0])
    assert doc == {
        "ts": "2026-11-15T09:30:00+00:00",
        "level": "WARNING",
        "logger": log.name,
        "msg": "order rejected: no cash",
    }
    assert set(doc) == set(logs.BASE_FIELDS)


def test_correlation_ids_flow_into_every_line_inside_the_block_and_nest_and_unwind():
    log, out = capture()
    with logs.correlate(run_id="r1", strategy_id="s1"):
        log.info("a")
        with logs.correlate(order_id="o9", instrument_id=42):
            log.info("b")
        log.info("c")
    log.info("d")
    a, b, c, d = (json.loads(x) for x in out)
    assert (a["run_id"], a["strategy_id"], "order_id" in a) == ("r1", "s1", False)
    assert (b["run_id"], b["order_id"], b["instrument_id"]) == ("r1", "o9", 42)
    assert "order_id" not in c and c["run_id"] == "r1"
    assert not (set(d) & set(logs.CORRELATION_FIELDS))


def test_an_unknown_correlation_field_is_refused_so_the_schema_cannot_drift():
    with pytest.raises(ValueError, match="bogus"):
        with logs.correlate(bogus=1):
            pass


def test_extra_fields_exceptions_and_unserialisable_values_are_still_one_valid_line():
    log, out = capture()
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        log.exception("failed", extra={"order_id": "o1", "qty": object()})
    doc = json.loads(out[0])
    assert doc["order_id"] == "o1" and "RuntimeError: boom" in doc["exc"]
    assert isinstance(doc["qty"], str) and "\n" not in out[0]


def test_setup_installs_one_json_handler_on_the_root_and_is_idempotent():
    root = logging.getLogger()
    saved, level = root.handlers[:], root.level
    try:
        logs.setup(SimClock(T), level="INFO")
        logs.setup(SimClock(T), level="INFO")
        ours = [h for h in root.handlers if isinstance(h.formatter, logs.JsonFormatter)]
        assert len(ours) == 1 and root.level == logging.INFO
    finally:
        root.handlers[:] = saved
        root.setLevel(level)
