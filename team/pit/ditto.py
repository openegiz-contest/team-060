"""Minimal Ditto HTTP client (stdlib only)."""

import base64
import json
import os
import urllib.error
import urllib.request

DITTO_URL = os.environ.get("DITTO_URL", "http://localhost:8080").rstrip("/")
DITTO_USER = os.environ.get("DITTO_USER", "ditto")
DITTO_PASSWORD = os.environ.get("DITTO_PASSWORD", "")
AUTH = "Basic " + base64.b64encode(f"{DITTO_USER}:{DITTO_PASSWORD}".encode()).decode()


def _req(method, path, body=None, timeout=15):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(f"{DITTO_URL}/api/2{path}", data=data, method=method,
                                 headers={"Authorization": AUTH, "Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=timeout)


def request(method, path, body=None, timeout=15):
    with _req(method, path, body, timeout) as r:
        return r.status


def get(path, timeout=15):
    """GET a JSON resource; None on 404."""
    try:
        with _req("GET", path, None, timeout) as r:
            return json.loads(r.read() or b"null")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
