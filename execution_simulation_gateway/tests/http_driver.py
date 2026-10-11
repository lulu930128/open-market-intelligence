"""ASGI HTTP protocol driver, no sockets and no direct route invocation.

httpx is absent in the repository venv. This driver exercises the ASGI callable
using real http.request/response messages including chunked request bodies.
"""

import json


async def request(app, method, path, *, headers=None, body=None, raw=None, chunks=None, before_receive=None):
    payload = raw if raw is not None else (b'' if body is None else json.dumps(body).encode())
    pieces = chunks if chunks is not None else [payload]
    sent = []
    offset = 0

    async def receive():
        nonlocal offset
        if before_receive:
            before_receive()
        if offset >= len(pieces):
            return {'type': 'http.disconnect'}
        chunk = pieces[offset]
        offset += 1
        return {'type': 'http.request', 'body': chunk, 'more_body': offset < len(pieces)}

    async def send(message):
        sent.append(message)

    path, separator, query = path.partition('?')
    scope = {'type': 'http', 'asgi': {'version': '3.0', 'spec_version': '2.3'},
             'http_version': '1.1', 'method': method, 'scheme': 'https', 'path': path,
             'raw_path': path.encode(), 'root_path': '', 'query_string': query.encode(),
             'headers': [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
             'client': ('synthetic-client', 0), 'server': ('synthetic.invalid', 0)}
    await app(scope, receive, send)
    assert len(sent) == 2 and sent[0]['type'] == 'http.response.start'
    assert sent[1]['type'] == 'http.response.body'
    assert (b'cache-control', b'no-store') in sent[0]['headers']
    result = json.loads(sent[1]['body'])
    assert result['simulated'] is True and result['broker_connected'] is False and result['test_only'] is True
    assert result['version'] == 'v1'
    return sent[0]['status'], result
