import asyncio
from http import HTTPStatus

import pytest
from websockets.asyncio.server import serve

from algo.data.providers.kite import KiteTokenExpired
from algo.live.kite_socket import connect


async def run_server(handler, *, reject=None):
    def process(connection, request):
        if reject is not None:
            return connection.respond(reject, "refused\n")
        return None

    return await serve(handler, "127.0.0.1", 0, process_request=process)


def url_of(server):
    return f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}"


def test_it_sends_the_credentials_in_the_query_and_speaks_text_out_and_binary_in():
    seen = {}

    async def handler(ws):
        seen["path"] = ws.request.path
        seen["msg"] = await ws.recv()
        await ws.send(b"\x00")  # a heartbeat
        await ws.send('{"type": "message"}')

    async def main():
        server = await run_server(handler)
        async with server, connect("KEY", "TOK", url=url_of(server)) as sock:
            await sock.send('{"a": "subscribe"}')
            first, second = await sock.recv(), await sock.recv()
            return first, second

    first, second = asyncio.run(main())
    assert seen["path"] == "/?api_key=KEY&access_token=TOK" and seen["msg"] == '{"a": "subscribe"}'
    assert (first, second) == (b"\x00", '{"type": "message"}')


@pytest.mark.parametrize("status", [HTTPStatus.FORBIDDEN, HTTPStatus.UNAUTHORIZED])
def test_a_refused_login_is_a_token_problem_never_something_to_retry(status):
    async def main():
        server = await run_server(lambda ws: None, reject=status)
        async with server, connect("KEY", "BAD", url=url_of(server)):
            pass

    with pytest.raises(KiteTokenExpired):
        asyncio.run(main())


def test_any_other_refusal_or_an_unreachable_server_is_a_retryable_connection_error():
    async def refused():
        server = await run_server(lambda ws: None, reject=HTTPStatus.BAD_GATEWAY)
        async with server, connect("K", "T", url=url_of(server)):
            pass

    async def unreachable():
        async with connect("K", "T", url="ws://127.0.0.1:1"):
            pass

    for coro in (refused, unreachable):
        with pytest.raises(OSError):
            asyncio.run(coro())


def test_a_dropped_connection_surfaces_as_a_connection_error_on_the_next_read():
    async def handler(ws):
        await ws.close()

    async def main():
        server = await run_server(handler)
        async with server, connect("K", "T", url=url_of(server)) as sock:
            await sock.recv()

    with pytest.raises(ConnectionError):
        asyncio.run(main())


def test_sending_on_a_closed_connection_is_a_connection_error_too():
    async def handler(ws):
        await ws.close()

    async def main():
        server = await run_server(handler)
        async with server, connect("K", "T", url=url_of(server)) as sock:
            await asyncio.sleep(0.2)
            await sock.send("x")

    with pytest.raises(ConnectionError):
        asyncio.run(main())


def test_a_peer_that_is_not_a_websocket_server_is_a_connection_error_not_a_crash():
    async def main():
        async def hang_up(reader, writer):
            writer.close()

        server = await asyncio.start_server(hang_up, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        async with server, connect("K", "T", url=f"ws://127.0.0.1:{port}"):
            pass

    with pytest.raises(ConnectionError):
        asyncio.run(main())
