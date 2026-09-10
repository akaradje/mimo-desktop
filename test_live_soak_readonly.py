#!/usr/bin/env python3
"""Read-only live Desktop API soak — no turn injection, no quit.

Checks health, sessions, messages (truncated), short SSE watch.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

import os

CRED = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))) / "Xiaomi MiMo AI" / "desktop-api.json"


def api(method: str, path: str, timeout: float = 10.0):
    cred = json.loads(CRED.read_text(encoding="utf-8"))
    url = f"http://127.0.0.1:{cred['port']}{path}"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {cred['token']}"},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read(2_000_000)
        return resp.status, json.loads(raw.decode("utf-8")) if raw else None


def main() -> int:
    t0 = time.time()
    steps = []

    def step(name: str, fn):
        st = time.time()
        try:
            r = fn()
            steps.append((name, True, time.time() - st, r))
            print(f"  ok  {name:20} {time.time()-st:5.2f}s  {str(r)[:120]}")
        except Exception as e:
            steps.append((name, False, time.time() - st, str(e)))
            print(f"  ERR {name:20} {time.time()-st:5.2f}s  {e}")

    print("Read-only live Desktop API soak (no send, no quit)")
    step("health", lambda: api("GET", "/v1/health"))
    step("sessions", lambda: [
        {"id": s.get("id"), "title": s.get("title")}
        for s in (api("GET", "/v1/sessions?limit=5")[1] or [])
    ])

    def messages():
        st, body = api("GET", "/v1/sessions?limit=1")
        if not body:
            return "no sessions"
        sid = body[0]["id"]
        # Full body via http.client — soak only counts, never dumps.
        import http.client as hc

        cred = json.loads(CRED.read_text(encoding="utf-8"))
        conn = hc.HTTPConnection("127.0.0.1", int(cred["port"]), timeout=20)
        try:
            conn.request(
                "GET",
                f"/v1/sessions/{sid}/messages",
                headers={"Authorization": f"Bearer {cred['token']}"},
            )
            resp = conn.getresponse()
            raw = resp.read()
            msgs = json.loads(raw.decode("utf-8"))
            n = len(msgs) if isinstance(msgs, list) else type(msgs).__name__
            return f"sid={sid} n={n} http={resp.status} bytes={len(raw)}"
        finally:
            conn.close()

    step("messages", messages)

    def sse_brief():
        # Use the server module's session for decoded reads
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "mimo_desktop_server",
            str(Path(__file__).resolve().with_name("server.py")),
        )
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader
        spec.loader.exec_module(mod)
        cred = json.loads(CRED.read_text(encoding="utf-8"))
        st, body = api("GET", "/v1/sessions?limit=1")
        sid = body[0]["id"]
        session, err = mod._open_sse_session(
            port=int(cred["port"]),
            token=str(cred["token"]),
            path=f"/v1/sessions/{sid}/events",
            connect_timeout=3.0,
        )
        if err or session is None:
            return f"open failed {err}"
        try:
            session.wait_meta(2.0)
            started = time.time()
            events, stopped, pings = mod._collect_sse(
                session, started, started + 4.0, 2.0, 20, False
            )
            stats = session.drain_stats()
            return {
                "stopped": stopped,
                "events": len(events),
                "types": [e.get("type") for e in events],
                "dropped": stats.get("dropped_events"),
                "history_complete": stats.get("dropped_events") == 0,
            }
        finally:
            session.close()

    step("sse_watch", sse_brief)

    fails = [s for s in steps if not s[1]]
    print("-" * 60)
    print(f"total {time.time()-t0:.2f}s  {len(steps)-len(fails)}/{len(steps)} ok")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
