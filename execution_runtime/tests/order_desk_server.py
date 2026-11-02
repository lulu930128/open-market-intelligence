"""Explicit loopback-only FAKE test server; never part of ordinary OMI startup.

Run: python -m execution_runtime.tests.order_desk_server --port 38414
POST / opens an isolated disposable fixture. GET /?session_id=... is read-only.
"""

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import RLock
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from .order_desk_fake import CONTRACT, OrderDeskFake


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=38414)
    args = parser.parse_args()
    sessions, lock = {}, RLock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def reply(self, status, body):
            encoded = json.dumps(body, ensure_ascii=True, allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self):
            sid = parse_qs(urlsplit(self.path).query).get("session_id", [""])[0]
            with lock:
                if not sid:
                    return self.reply(200, {"contract": CONTRACT, "mode": "FAKE_ONLY", "live_broker": "NOT_DEPLOYED"})
                if sid not in sessions:
                    return self.reply(404, {"code": "FAKE_SESSION_EXPIRED"})
                self.reply(200, {"session_id": sid, **sessions[sid].read()})

        def do_POST(self):
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if size <= 0 or size > 65536:
                    raise ValueError("INVALID_BODY_SIZE")
                body = json.loads(self.rfile.read(size))
                with lock:
                    if body == {"type": "open_demo"}:
                        if len(sessions) >= 16:
                            raise ValueError("FAKE_SESSION_LIMIT")
                        sid = str(uuid4())
                        sessions[sid] = OrderDeskFake()
                        return self.reply(200, {"session_id": sid, **sessions[sid].read()})
                    if type(body) is not dict or set(body) != {"session_id", "command"}:
                        raise ValueError("INVALID_ENVELOPE")
                    sid = body["session_id"]
                    if sid not in sessions:
                        raise ValueError("FAKE_SESSION_EXPIRED")
                    fixture = sessions[sid]
                    try:
                        result = fixture.dispatch(body["command"])
                    except (ValueError, TypeError, KeyError) as error:
                        return self.reply(409, {"code": str(error), "session_id": sid, "snapshot": fixture.read()})
                    self.reply(200, {"session_id": sid, **fixture.read(), "result": result})
            except (ValueError, TypeError, KeyError):
                self.reply(400, {"code": "INVALID_FAKE_REQUEST"})

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"FAKE_ONLY Order Desk fixture on 127.0.0.1:{server.server_port}; live broker NOT_DEPLOYED", flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        for fixture in sessions.values():
            fixture.close()


if __name__ == "__main__":
    main()
