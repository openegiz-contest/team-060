#!/usr/bin/env python3
"""
Dispatcher console: serves the pit map (web/) and a thin API over Ditto.

  GET  /api/static    attributes of every twin (geometry, equipment data)
  GET  /api/state     features of every twin (live state)
  POST /api/scenario  {"ramp_a_closed": true, ...} -> control twin in Ditto
  POST /api/reset     all scenarios back to defaults

All data the page shows comes from Ditto; the server only adds the Ditto
credentials, which must not reach the browser.
"""

import json
import os
import sys
import time
import urllib.error
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import ditto
import model as M

WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
IDS = M.all_thing_ids()
_cache = {"t": 0.0, "body": b"[]"}


def fetch(fields):
    return ditto.get(f"/things?ids={','.join(IDS)}&fields={fields}", timeout=10) or []


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=WEB, **kw)

    def log_message(self, fmt, *args):
        pass

    def send_json(self, obj, status=200, raw=None):
        body = raw if raw is not None else json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        try:
            if self.path.startswith("/api/static"):
                return self.send_json(fetch("thingId,attributes"))
            if self.path.startswith("/api/state"):
                now = time.time()
                if now - _cache["t"] > 0.4:
                    _cache["body"] = json.dumps(fetch("thingId,features"), ensure_ascii=False).encode()
                    _cache["t"] = now
                return self.send_json(None, raw=_cache["body"])
            if self.path.startswith("/api/health"):
                return self.send_json({"ok": True})
        except (urllib.error.URLError, OSError, ValueError) as exc:
            return self.send_json({"error": str(exc)}, 502)
        return super().do_GET()

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
            if self.path.startswith("/api/reset"):
                body = dict(M.DEFAULT_SCENARIOS)
            elif not self.path.startswith("/api/scenario"):
                return self.send_json({"error": "not found"}, 404)
            done = {}
            for key, value in body.items():
                if key not in M.DEFAULT_SCENARIOS:
                    return self.send_json({"error": f"unknown scenario {key}"}, 400)
                ditto.request("PUT", f"/things/{M.thing('control')}/features/scenarios/properties/{key}", value)
                done[key] = value
            return self.send_json({"ok": True, "set": done})
        except (urllib.error.URLError, OSError, ValueError) as exc:
            return self.send_json({"error": str(exc)}, 502)


def main():
    port = int(os.environ.get("WEB_PORT", "8095"))
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"dispatcher console on :{port}, Ditto {ditto.DITTO_URL}", flush=True)
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
