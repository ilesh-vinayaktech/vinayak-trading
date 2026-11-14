import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from algo.data.providers.nse_client import HEADERS, NotPublished, NseClient, NseHttpError


@pytest.fixture
def server():
    """Real local HTTP server: scripted status codes per path, records request headers."""
    state = {"script": {}, "seen": [], "hits": {}}

    class H(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            n = state["hits"][self.path] = state["hits"].get(self.path, 0) + 1
            state["seen"].append(dict(self.headers))
            codes = state["script"].get(self.path, [200])
            code = codes[min(n, len(codes)) - 1]
            if code == 0:  # drop the connection without a response (RemoteDisconnected)
                self.close_connection = True
                return
            self.send_response(code)
            self.end_headers()
            if code == 200:
                self.wfile.write(b"payload")

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    state["base"] = f"http://127.0.0.1:{srv.server_port}"
    yield state
    srv.shutdown()


def client(sleeps, **kw):
    return NseClient(sleep=sleeps.append, **kw)


def test_ok_sends_browser_headers(server):
    assert client([]).get(server["base"] + "/f") == b"payload"
    assert server["seen"][0]["User-Agent"] == HEADERS["User-Agent"]
    assert server["seen"][0]["Referer"] == HEADERS["Referer"]


def test_404_is_not_published_and_not_retried(server):
    server["script"]["/f"] = [404]
    sleeps = []
    with pytest.raises(NotPublished) as e:
        client(sleeps).get(server["base"] + "/f")
    assert e.value.status == 404 and server["hits"]["/f"] == 1


def test_other_4xx_not_retried(server):
    server["script"]["/f"] = [403]
    with pytest.raises(NseHttpError) as e:
        client([]).get(server["base"] + "/f")
    assert e.value.status == 403 and server["hits"]["/f"] == 1


def test_retries_5xx_and_429_with_exponential_backoff(server):
    server["script"]["/f"] = [503, 429, 200]
    sleeps = []
    assert client(sleeps, min_interval=0).get(server["base"] + "/f") == b"payload"
    assert [s for s in sleeps if s] == [1.0, 2.0] and server["hits"]["/f"] == 3


def test_gives_up_after_retries(server):
    server["script"]["/f"] = [500]
    with pytest.raises(NseHttpError) as e:
        client([], retries=2, min_interval=0).get(server["base"] + "/f")
    assert e.value.status == 500 and server["hits"]["/f"] == 3


def test_network_error_retried_then_raised():
    sleeps = []
    with pytest.raises(OSError):
        client(sleeps, retries=1, min_interval=0, timeout=0.5).get("http://127.0.0.1:1/x")
    assert sleeps == [1.0]


def test_min_interval_throttles(server):
    now = [100.0]
    sleeps = []
    c = NseClient(min_interval=1.0, sleep=sleeps.append, clock=lambda: now[0])
    c.get(server["base"] + "/a")
    now[0] += 0.25
    c.get(server["base"] + "/b")
    assert sleeps == [0.75]
    now[0] += 5
    c.get(server["base"] + "/c")
    assert sleeps == [0.75]  # enough time passed: no extra wait


def test_session_cookie_is_kept_across_calls_and_accept_header_sent():
    seen = []

    class H(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            seen.append((self.path, self.headers.get("Cookie"), self.headers.get("Accept")))
            if self.path == "/page":
                self.send_response(403)  # warm-up page may even fail but still sets the cookie
                self.send_header("Set-Cookie", "sid=abc; Path=/")
                self.end_headers()
                return
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    c = NseClient(sleep=lambda s: None, min_interval=0)
    c.warm(base + "/page")
    assert c.get(base + "/api", accept="application/json") == b"{}"
    srv.shutdown()
    assert seen[1] == ("/api", "sid=abc", "application/json")


def test_not_published_is_the_shared_provider_error(server):
    from algo.data.providers.base import NotPublishedError

    server["script"]["/x"] = [404]
    with pytest.raises(NotPublishedError):
        client([]).get(server["base"] + "/x")


def test_a_dropped_connection_is_retried_like_other_transient_trouble(server):
    server["script"]["/f"] = [0, 0, 200]
    sleeps = []
    assert client(sleeps, min_interval=0).get(server["base"] + "/f") == b"payload"
    assert [s for s in sleeps if s] == [1.0, 2.0] and server["hits"]["/f"] == 3


def test_a_connection_that_keeps_dropping_is_raised_after_the_retries(server):
    import http.client

    server["script"]["/f"] = [0]
    with pytest.raises(http.client.RemoteDisconnected):
        client([], retries=2, min_interval=0).get(server["base"] + "/f")
    assert server["hits"]["/f"] == 3


def test_a_new_session_forgets_the_old_cookies_and_still_works(server):
    import http.cookiejar

    def jar_of(c):
        return next(h for h in c._opener.handlers if hasattr(h, "cookiejar")).cookiejar

    c = client([])
    old = jar_of(c)
    old.set_cookie(
        http.cookiejar.Cookie(
            0,
            "nsit",
            "abc",
            None,
            False,
            "127.0.0.1",
            False,
            False,
            "/",
            True,
            False,
            None,
            False,
            None,
            None,
            {},
        )  # fmt: skip
    )
    assert len(old) == 1
    c.new_session()  # NSE stops answering one session after a few hundred calls: start another
    assert jar_of(c) is not old and len(jar_of(c)) == 0
    assert c.get(server["base"] + "/x") == b"payload"
