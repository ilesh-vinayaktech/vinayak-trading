import os
import sys
from pathlib import Path

from algo.sandbox.guards import Policy, decide, scan_source

ROOT = str(Path(__file__).resolve().parents[3] / "src")
POLICY = Policy(read_roots=(ROOT, sys.prefix, "/usr/lib/python3.12"))


def ruling(event, *args, policy=POLICY):
    return decide(event, args, policy)


def test_network_and_process_and_native_code_events_are_refused():
    for ev in ("socket.__new__", "socket.connect", "socket.getaddrinfo", "socket.bind"):
        assert "network" in ruling(ev, object(), ("1.1.1.1", 53))
    for ev in (
        "subprocess.Popen",
        "os.system",
        "os.exec",
        "os.fork",
        "os.forkpty",
        "os.posix_spawn",
        "os.spawn",
        "os.kill",
    ):
        assert "process" in ruling(ev, "x")
    assert "native" in ruling("ctypes.dlopen", "libc.so.6")
    assert "native" in ruling("ctypes.cdata", 1)
    loading = Policy(read_roots=(ROOT,), loading=True)
    assert (
        ruling("ctypes.dlopen", "libpq.so", policy=loading) is None
    )  # while the platform is being imported
    assert "network" in ruling(
        "socket.connect", object(), ("1.1.1.1", 53), policy=loading
    )  # everything else stays refused


def test_changes_to_files_are_refused_whatever_the_path():
    for ev in (
        "os.remove",
        "os.rename",
        "os.mkdir",
        "os.rmdir",
        "os.chmod",
        "os.truncate",
        "os.symlink",
        "shutil.rmtree",
        "shutil.copyfile",
    ):
        assert "change files" in ruling(ev, "/tmp/x")


def test_reading_is_only_allowed_under_the_allowed_roots():
    assert ruling("open", ROOT + "/algo/strategy/base.py", "r", os.O_RDONLY) is None
    assert ruling("open", sys.prefix + "/lib/x.py", "rb", None) is None
    assert ruling("open", b"/usr/lib/python3.12/json/__init__.py", "r", 0) is None
    assert ruling("open", 7, "r", 0) is None  # a file descriptor that is already open
    assert "outside" in ruling("open", "/etc/passwd", "r", 0)
    assert "outside" in ruling("open", os.path.expanduser("~/.ssh/id_rsa"), "r", 0)
    assert "outside" in ruling(
        "open", ROOT + "/../.env", "r", 0
    )  # the project's secrets sit beside src
    assert "outside" in ruling(
        "open", ROOT + "-evil/x", "r", 0
    )  # a sibling that only shares the prefix


def test_symlinks_cannot_lead_out_of_the_allowed_roots(tmp_path):
    inside = tmp_path / "root"
    inside.mkdir()
    (tmp_path / "secret").write_text("x")
    (inside / "link").symlink_to(tmp_path / "secret")
    p = Policy(read_roots=(str(inside),))
    assert "outside" in decide("open", (str(inside / "link"), "r", 0), p)


def test_any_write_mode_or_flag_is_refused_even_inside_the_allowed_roots():
    for mode in ("w", "a", "x", "r+", "wb", "ab+"):
        assert "write" in ruling("open", ROOT + "/algo/x.py", mode, None)
    for flag in (os.O_WRONLY, os.O_RDWR, os.O_CREAT | os.O_RDONLY, os.O_TRUNC, os.O_APPEND):
        assert "write" in ruling("open", ROOT + "/algo/x.py", None, flag)


def test_denied_imports_are_refused_by_root_package_and_only_when_armed():
    armed = Policy(
        read_roots=(ROOT,), denied_imports=frozenset({"subprocess", "ctypes", "requests"})
    )
    for name in ("subprocess", "ctypes.util", "requests.adapters"):
        assert "import" in decide("import", (name, None, [], [], []), armed)
    assert decide("import", ("json", None, [], [], []), armed) is None
    assert (
        decide("import", ("ctypes", None, [], [], []), POLICY) is None
    )  # not armed: the platform may load what it needs
    assert (
        ruling("sys.settrace") is None and ruling("exec", object()) is None
    )  # events the guard has no opinion on


def test_calling_the_system_clock_is_found_in_strategy_source():
    ok = "def f(ctx):\n    t = ctx.now()\n    return t.date()\n"
    assert scan_source(ok) == []
    bad = "import time, datetime\nfrom datetime import date, datetime as dt\ndef f():\n    a = time.time()\n    b = datetime.datetime.now()\n    c = date.today()\n    d = dt.utcnow()\n    e = time.time_ns()\n"
    found = scan_source(bad)
    assert [f.split(":")[0] for f in found] == [
        "line 4",
        "line 5",
        "line 6",
        "line 7",
        "line 8",
    ] and all("clock" in f for f in found)


def test_unparseable_source_is_a_finding_not_a_crash():
    assert scan_source("def (:")[0].startswith("line 1") or "syntax" in scan_source("def (:")[0]
