#!/usr/bin/env python3
"""Independent MCP stdio client against mimo-desktop (no host SDK).

Validates: initialize/version negotiation, tools/list, a read-only call,
an error result, screenshot image content, clean shutdown.

NDJSON framing only — matches @modelcontextprotocol/sdk stdio.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

PY = sys.executable
SERVER = str(Path(__file__).resolve().with_name("server.py"))


class McpStdioClient:
    def __init__(self) -> None:
        self.proc = subprocess.Popen(
            [PY, SERVER],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
        )
        self._id = 0
        self._lock = threading.Lock()
        self.stderr_tail = b""

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    def send(self, obj: dict[str, Any]) -> None:
        assert self.proc.stdin is not None
        data = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
        self.proc.stdin.write(data)
        self.proc.stdin.flush()

    def request(self, method: str, params: dict[str, Any] | None = None,
                timeout: float = 20.0) -> dict[str, Any]:
        rid = self._next_id()
        msg: dict[str, Any] = {"jsonrpc": "2.0", "id": rid, "method": method}
        if params is not None:
            msg["params"] = params
        self.send(msg)
        deadline = time.time() + timeout
        assert self.proc.stdout is not None
        while time.time() < deadline:
            line = self.proc.stdout.readline()
            if not line:
                raise RuntimeError("server closed stdout")
            line = line.strip()
            if not line:
                continue
            resp = json.loads(line.decode("utf-8"))
            if resp.get("id") == rid:
                return resp
            # ignore unexpected notifications
        raise TimeoutError(f"no response for {method} id={rid}")

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        self.send(msg)

    def close(self) -> None:
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()
        try:
            if self.proc.stderr:
                self.stderr_tail = self.proc.stderr.read()[-2000:]
        except Exception:
            pass


def main() -> int:
    failures: list[str] = []
    skipped: list[str] = []
    shot_dir = tempfile.TemporaryDirectory(prefix='mcp-client-test-')
    client = McpStdioClient()
    try:
        # --- initialize ---
        init = client.request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "independent-mcp-client", "version": "0.1"},
            },
        )
        result = init.get("result") or {}
        info = result.get("serverInfo") or {}
        proto = result.get("protocolVersion")
        caps = result.get("capabilities") or {}
        print(f"initialize: proto={proto} server={info} caps={list(caps)}")
        if proto != "2024-11-05":
            failures.append(f"protocolVersion={proto}")
        if info.get("name") != "mimo-desktop":
            failures.append(f"serverInfo.name={info.get('name')}")
        if "tools" not in caps:
            failures.append("missing tools capability")
        client.notify("notifications/initialized")

        # --- tools/list ---
        tl = client.request("tools/list")
        tools = (tl.get("result") or {}).get("tools") or []
        names = sorted(t.get("name") or "" for t in tools)
        print(f"tools/list: {len(names)} tools")
        required = {
            "mimo_status",
            "mimo_list_sessions",
            "mimo_watch_events",
            "mimo_send_and_watch",
            "mimo_capture_window",
            "mimo_get_preferences",
            "desktop_list_windows",
            "desktop_observe",
            "desktop_click",
            "desktop_type_text",
            "desktop_press_key",
            "desktop_scroll",
            "desktop_drag",
            "desktop_drag_between",
            "desktop_inspect",
            "desktop_click_element",
            "desktop_verify_element",
            "desktop_set_window_rect",
            "desktop_paste_text",
            "desktop_verify_text",
        }
        missing = required - set(names)
        if missing:
            failures.append(f"missing tools: {missing}")
        # every tool has schema
        for t in tools:
            if "inputSchema" not in t:
                failures.append(f"no schema: {t.get('name')}")

        # --- read-only call ---
        st = client.request("tools/call", {"name": "mimo_status", "arguments": {}})
        st_result = st.get("result") or {}
        text = ""
        for b in st_result.get("content") or []:
            if b.get("type") == "text":
                text = b.get("text") or ""
        print(f"mimo_status isError={st_result.get('isError')} text_len={len(text)}")
        if st_result.get("isError"):
            failures.append(f"mimo_status isError: {text[:200]}")
        if "process_count" not in text and "ok" not in text:
            failures.append("mimo_status text missing expected keys")

        # --- error result (unknown tool) ---
        bad = client.request("tools/call", {"name": "no_such_tool", "arguments": {}})
        bad_result = bad.get("result") or {}
        print(f"unknown tool isError={bad_result.get('isError')}")
        if not bad_result.get("isError"):
            failures.append("unknown tool should be isError=true")

        # --- error result (bad args on real tool) ---
        bad2 = client.request(
            "tools/call",
            {"name": "mimo_watch_events", "arguments": {"session_id": "!!!bad"}},
        )
        bad2_result = bad2.get("result") or {}
        b2text = ""
        for b in bad2_result.get("content") or []:
            if b.get("type") == "text":
                b2text = b.get("text") or ""
        print(f"bad session isError={bad2_result.get('isError')} snippet={b2text[:80]!r}")
        # business error may set isError via ok:false
        if not bad2_result.get("isError") and '"ok": false' not in b2text:
            failures.append("bad session_id should fail")

        # --- screenshot image content (read-only, MiMo window) ---
        shot_path = Path(shot_dir.name) / "capture.png"
        cap = client.request(
            "tools/call",
            {
                "name": "mimo_capture_window",
                "arguments": {
                    "save_path": str(shot_path),
                    "include_frame": False,
                    "focus": False,
                },
            },
            timeout=25.0,
        )
        cap_result = cap.get("result") or {}
        has_image = any(b.get("type") == "image" for b in cap_result.get("content") or [])
        cap_text = ""
        for b in cap_result.get("content") or []:
            if b.get("type") == "text":
                cap_text = b.get("text") or ""
        print(
            f"capture isError={cap_result.get('isError')} has_image={has_image} "
            f"file={shot_path.exists()} size={shot_path.stat().st_size if shot_path.exists() else 0}"
        )
        if cap_result.get("isError"):
            # Window may be minimized or unavailable — not a protocol failure
            if 'no MiMo main window found' in cap_text or 'minimized' in cap_text.lower():
                skipped.append('MiMo capture: window unavailable/minimized')
            else:
                failures.append(f'capture error: {cap_text[:200]}')
            print(f"  capture unavailable/failed: {cap_text[:200]}")
        else:
            if not has_image:
                failures.append("capture success but no MCP image content block")
            if not shot_path.exists():
                failures.append("capture success but save_path missing")
            elif shot_path.stat().st_size < 1000:
                failures.append(f"screenshot too small: {shot_path.stat().st_size}")

        # --- ping ---
        pong = client.request("ping", timeout=5.0)
        if "result" not in pong and "error" not in pong:
            failures.append("ping: no result")

        # --- clean shutdown: close stdin, expect exit 0 ---
        client.close()
        code = client.proc.returncode
        print(f"shutdown: returncode={code}")
        if code not in (0, None):
            # None if still running — wait a bit
            try:
                code = client.proc.wait(timeout=3)
            except Exception:
                client.proc.kill()
                code = client.proc.returncode
            print(f"shutdown after wait: returncode={code}")
        if code not in (0,):
            failures.append(f"exit code {code}")
            if client.stderr_tail:
                print("stderr tail:", client.stderr_tail.decode("utf-8", "replace")[-500:])

    except Exception as e:
        failures.append(f"exception: {type(e).__name__}: {e}")
        import traceback

        traceback.print_exc()
        try:
            client.close()
        except Exception:
            pass

    shot_dir.cleanup()
    print("-" * 60)
    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print('CHECKS PASSED WITH SKIPS: ' + '; '.join(skipped) if skipped else 'ALL CHECKS PASSED')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
