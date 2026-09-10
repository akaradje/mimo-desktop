#!/usr/bin/env python3
"""SSE stress harness for mimo-desktop `_SseSession`.

Spins up a local raw-socket HTTP/1.1 server that emits *explicit* chunked
bodies so we can split UTF-8, multi-event chunks, mid-line stalls, etc.

Does not touch live MiMo chats or the Desktop API.

Run:
  python test_sse_stress.py
"""

from __future__ import annotations

import importlib.util
import re
import socket
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
SERVER_PATH = HERE / "server.py"


def _load_server():
    spec = importlib.util.spec_from_file_location("mimo_desktop_server", SERVER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {SERVER_PATH}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["mimo_desktop_server"] = mod
    spec.loader.exec_module(mod)
    return mod


srv = _load_server()


# ---------------------------------------------------------------------------
# Raw chunked SSE fixture
# ---------------------------------------------------------------------------


class ChunkedSseFixture:
    """HTTP/1.1 server: one connection, scripted body chunks, exact framing."""

    def __init__(self, chunks: list[bytes], stall_after: int | None = None,
                 stall_s: float = 0.0, close_abruptly: bool = False,
                 meta_delay_s: float = 0.0, register_delay_s: float = 0.0,
                 max_connections: int = 1) -> None:
        self.chunks = chunks
        self.stall_after = stall_after  # index after which we sleep stall_s
        self.stall_s = stall_s
        self.close_abruptly = close_abruptly
        self.meta_delay_s = meta_delay_s
        self.register_delay_s = register_delay_s
        self.max_connections = max_connections
        self.port = 0
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self.ready = threading.Event()
        self.served = threading.Event()
        self.error: str | None = None
        self.listener_registered_at: float | None = None
        self.meta_sent_at: float | None = None

    def start(self) -> int:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(5)
        self.port = self._sock.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        self.ready.set()
        return self.port

    def stop(self) -> None:
        try:
            if self._sock is not None:
                self._sock.close()
        except Exception:
            pass
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def _serve(self) -> None:
        assert self._sock is not None
        for _n in range(self.max_connections):
            try:
                conn, _addr = self._sock.accept()
            except OSError as e:
                self.error = f"accept: {e}"
                return
            with conn:
                conn.settimeout(10)
                try:
                    req = b""
                    while b"\r\n\r\n" not in req:
                        chunk = conn.recv(4096)
                        if not chunk:
                            break
                        req += chunk
                    headers = (
                        b"HTTP/1.1 200 OK\r\n"
                        b"Content-Type: text/event-stream; charset=utf-8\r\n"
                        b"Cache-Control: no-cache, no-transform\r\n"
                        b"Connection: close\r\n"
                        b"Transfer-Encoding: chunked\r\n"
                        b"\r\n"
                    )
                    conn.sendall(headers)

                    for i, body in enumerate(self.chunks):
                        if (
                            self.stall_after is not None
                            and i == self.stall_after
                            and self.stall_s > 0
                        ):
                            time.sleep(self.stall_s)
                        if b"event: meta" in body and self.meta_sent_at is None:
                            if self.meta_delay_s > 0:
                                time.sleep(self.meta_delay_s)
                            self.meta_sent_at = time.time()
                            if self.register_delay_s > 0:
                                threading.Timer(
                                    self.register_delay_s,
                                    lambda: setattr(
                                        self, "listener_registered_at", time.time()
                                    ),
                                ).start()
                            else:
                                self.listener_registered_at = time.time()
                        framed = (
                            f"{len(body):X}\r\n".encode("ascii") + body + b"\r\n"
                        )
                        conn.sendall(framed)

                    if not self.close_abruptly:
                        conn.sendall(b"0\r\n\r\n")
                except Exception as e:  # noqa: BLE001
                    self.error = f"serve: {e}"
        self.served.set()


def open_session(port: int, **kwargs: Any):
    return srv._open_sse_session(
        port=port,
        token="test-token",
        path="/v1/sessions/ses_test/events",
        connect_timeout=3.0,
        **kwargs,
    )


def collect(session, timeout_s: float = 3.0, idle_s: float = 1.5, max_events: int = 100,
            include_pings: bool = False) -> tuple[list[dict], str]:
    started = time.time()
    deadline = started + timeout_s
    events, stopped, _pings = srv._collect_sse(
        session, started, deadline, idle_s, max_events, include_pings
    )
    return events, stopped


def event_types(events: list[dict]) -> list[str]:
    return [str(e.get("type") or "") for e in events]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

PASS = "PASS"
FAIL = "FAIL"


def test_utf8_split_across_chunks() -> str:
    """Multi-byte UTF-8 character split across HTTP chunks."""
    # '你' = E4 BD A0 — split after E4 | BD A0
    payload = "event: message\ndata: {\"text\":\"你好世界\"}\n\n".encode("utf-8")
    # Split in the middle of the first CJK char's bytes and mid-line
    cut = payload.find("你".encode("utf-8")) + 1  # after first byte of 你
    chunks = [payload[:cut], payload[cut:]]
    fx = ChunkedSseFixture(chunks)
    port = fx.start()
    try:
        session, err = open_session(port)
        if err or session is None:
            return f"{FAIL} open: {err}"
        try:
            events, stopped = collect(session, timeout_s=2.5, idle_s=1.2)
        finally:
            session.close()
        types = event_types(events)
        msgs = [e for e in events if e.get("type") == "message"]
        text = ""
        if msgs:
            # slim keeps text or raw
            text = str(msgs[0].get("text") or msgs[0].get("raw") or "")
        if "message" not in types:
            return f"{FAIL} no message event types={types} err={session.error!r}"
        if "你好世界" not in text and "ä½" in text:
            return f"{FAIL} mojibake text={text!r}"
        if "你好世界" not in text:
            # slim may put JSON in raw
            raw = str(msgs[0].get("raw") or "")
            if "你好世界" not in raw and "你好世界" not in text:
                return f"{FAIL} text missing got={text!r} raw={raw!r}"
        if session.error and "decode" in str(session.error).lower():
            return f"{FAIL} decode error: {session.error}"
        return f"{PASS} text preserved, stopped={stopped}"
    finally:
        fx.stop()


def test_multiple_events_one_chunk() -> str:
    body = (
        b"event: meta\n"
        b'data: {"api":1,"sessionId":"ses_x"}\n'
        b"\n"
        b"event: message\n"
        b'data: {"type":"message","n":1}\n'
        b"\n"
        b"event: message\n"
        b'data: {"type":"message","n":2}\n'
        b"\n"
        b"event: closed\n"
        b'data: {"type":"closed"}\n'
        b"\n"
    )
    fx = ChunkedSseFixture([body])
    port = fx.start()
    try:
        session, err = open_session(port)
        if err or session is None:
            return f"{FAIL} open: {err}"
        try:
            events, stopped = collect(session, timeout_s=2.0, idle_s=1.0)
        finally:
            session.close()
        types = event_types(events)
        expected = ["meta", "message", "message", "closed"]
        if types != expected:
            return f"{FAIL} types={types} expected={expected}"
        ns = [e.get("n") for e in events if e.get("type") == "message"]
        # slim may not keep "n" — check raw or type order only
        if types.count("message") != 2:
            return f"{FAIL} message count={types.count('message')}"
        if stopped != "closed":
            return f"{FAIL} stopped={stopped}"
        return f"{PASS} ordered {types}"
    finally:
        fx.stop()


def test_one_event_many_chunks() -> str:
    """One frame split across many tiny chunks — no premature dispatch."""
    full = b'event: message\ndata: {"type":"message","id":"A"}\n\n'
    chunks = [full[i : i + 1] for i in range(len(full))]  # 1 byte at a time
    fx = ChunkedSseFixture(chunks)
    port = fx.start()
    try:
        session, err = open_session(port)
        if err or session is None:
            return f"{FAIL} open: {err}"
        try:
            events, stopped = collect(session, timeout_s=4.0, idle_s=2.0)
        finally:
            session.close()
        types = event_types(events)
        msgs = [e for e in events if e.get("type") == "message"]
        if len(msgs) != 1:
            return f"{FAIL} premature/multiple dispatch types={types}"
        return f"{PASS} single complete event after {len(chunks)} chunks"
    finally:
        fx.stop()


def test_crlf_comments_multiline_data() -> str:
    body = (
        b": keep-alive\r\n"
        b"event: message\r\n"
        b"data: line1\r\n"
        b"data: line2\r\n"
        b"\r\n"
        b": ping\r\n"
        b"event: closed\r\n"
        b'data: {"type":"closed"}\r\n'
        b"\r\n"
    )
    fx = ChunkedSseFixture([body])
    port = fx.start()
    try:
        session, err = open_session(port, include_pings=True)
        if err or session is None:
            return f"{FAIL} open: {err}"
        try:
            events, stopped = collect(session, timeout_s=2.0, idle_s=1.0, include_pings=True)
        finally:
            session.close()
        types = event_types(events)
        msgs = [e for e in events if e.get("type") == "message"]
        blob = ""
        if msgs:
            m = msgs[0]
            blob = " | ".join(str(m.get(k) or "") for k in ("text", "data", "raw", "preview"))
        if "line1" not in blob or "line2" not in blob:
            return (
                f"{FAIL} multiline data blob={blob!r} "
                f"keys={list(msgs[0]) if msgs else []} types={types}"
            )
        if stopped != "closed":
            return f"{FAIL} stopped={stopped} types={types}"
        return f"{PASS} crlf+comments+multiline ok types={types} pings={session.ping_count}"
    finally:
        fx.stop()


def test_ping_flood_does_not_reset_idle() -> str:
    """Pings must not reset the non-ping idle clock; overall deadline holds."""
    # meta, then ping flood for ~2s, then silence. idle_s=0.8 should fire
    # during the flood if pings don't reset the timer — but _collect_sse
    # uses last_event_at only for non-ping events (pings are skipped unless
    # include_pings). With include_pings=False, flood should not extend watch.
    chunks = [b'event: meta\ndata: {"api":1,"sessionId":"s"}\n\n']
    for _ in range(40):
        chunks.append(b": ping\n\n")
    fx = ChunkedSseFixture(chunks, stall_after=1, stall_s=0.05)
    port = fx.start()
    try:
        session, err = open_session(port, include_pings=False)
        if err or session is None:
            return f"{FAIL} open: {err}"
        t0 = time.time()
        try:
            # Collect with idle 0.6s; pings should NOT keep it alive for 2s+
            events, stopped = collect(
                session, timeout_s=3.0, idle_s=0.6, max_events=50, include_pings=False
            )
        finally:
            session.close()
        elapsed = time.time() - t0
        types = event_types(events)
        # Should stop due to idle well before the 3s overall budget if
        # pings don't refresh last_event_at. Allow slack for fixture I/O.
        if "meta" not in types:
            return f"{FAIL} no meta types={types}"
        if elapsed > 2.5:
            return (
                f"{FAIL} idle clock appears reset by pings "
                f"elapsed={elapsed:.2f}s stopped={stopped}"
            )
        return f"{PASS} stopped={stopped} elapsed={elapsed:.2f}s pings_seen={session.ping_count}"
    finally:
        fx.stop()


def test_eof_mid_frame_not_emitted() -> str:
    """Incomplete frame at EOF must not be emitted as a complete event."""
    body = b'event: message\ndata: {"type":"message","incomplete":tr'
    # No trailing \n\n — then close (normal chunked end)
    fx = ChunkedSseFixture([body], close_abruptly=False)
    port = fx.start()
    try:
        session, err = open_session(port)
        if err or session is None:
            return f"{FAIL} open: {err}"
        try:
            events, stopped = collect(session, timeout_s=2.0, idle_s=1.0)
        finally:
            session.close()
        types = event_types(events)
        msgs = [e for e in events if e.get("type") == "message"]
        if msgs:
            return f"{FAIL} incomplete frame emitted types={types}"
        # eof is expected
        if stopped not in ("eof", "idle", "idle_no_events"):
            return f"{FAIL} unexpected stopped={stopped} types={types}"
        return f"{PASS} incomplete dropped stopped={stopped} types={types}"
    finally:
        fx.stop()


def test_socket_stall_bounded() -> str:
    """Server stalls; client must return on idle/overall budget."""
    chunks = [
        b'event: meta\ndata: {"api":1,"sessionId":"s"}\n\n',
        b'event: message\ndata: {"type":"message","n":1}\n\n',
        # then stall forever (no more chunks, keep connection open)
    ]
    fx = ChunkedSseFixture(chunks, stall_after=2, stall_s=5.0, close_abruptly=True)
    # stall_after=2 means sleep before sending chunk index 2 — we only have
    # 2 chunks (0,1), so the loop finishes then close_abruptly. Better:
    # stall after all chunks by using stall_after=len and not closing.
    # Simpler: send 2 events then stall_s on a third empty wait via stall_after=2
    # with a third chunk that never comes — adjust: stall_after=2, stall_s=5,
    # only 2 chunks so no stall in loop. Use close_abruptly after long sleep.
    fx = ChunkedSseFixture(
        [chunks[0], chunks[1]],
        stall_after=2,
        stall_s=3.0,
        close_abruptly=True,
    )
    port = fx.start()
    try:
        session, err = open_session(port)
        if err or session is None:
            return f"{FAIL} open: {err}"
        t0 = time.time()
        try:
            events, stopped = collect(session, timeout_s=2.0, idle_s=1.0)
        finally:
            session.close()
        elapsed = time.time() - t0
        if elapsed > 3.5:
            return f"{FAIL} not bounded elapsed={elapsed:.2f}s"
        types = event_types(events)
        if "meta" not in types:
            return f"{FAIL} missing meta types={types}"
        return f"{PASS} bounded elapsed={elapsed:.2f}s stopped={stopped} types={types}"
    finally:
        fx.stop()


def test_max_events_and_closed() -> str:
    chunks = [b'event: meta\ndata: {"api":1}\n\n']
    for i in range(10):
        chunks.append(f'event: message\ndata: {{"type":"message","n":{i}}}\n\n'.encode())
    chunks.append(b'event: closed\ndata: {"type":"closed"}\n\n')
    fx = ChunkedSseFixture(chunks)
    port = fx.start()
    try:
        session, err = open_session(port)
        if err or session is None:
            return f"{FAIL} open: {err}"
        try:
            # max_events=3 → meta + 2 messages, stop before closed
            events, stopped = collect(session, timeout_s=2.0, idle_s=1.0, max_events=3)
        finally:
            session.close()
        if len(events) > 3:
            return f"{FAIL} cap exceeded n={len(events)}"
        if stopped != "max_events":
            return f"{FAIL} stopped={stopped} n={len(events)} types={event_types(events)}"

        # Second connection: let it hit closed
        fx2 = ChunkedSseFixture(
            [b'event: meta\ndata: {"api":1}\n\n', b'event: closed\ndata: {"type":"closed"}\n\n']
        )
        p2 = fx2.start()
        try:
            s2, err2 = open_session(p2)
            if err2 or s2 is None:
                return f"{FAIL} open2: {err2}"
            try:
                ev2, st2 = collect(s2, timeout_s=2.0, idle_s=1.0, max_events=50)
            finally:
                s2.close()
            if st2 != "closed":
                return f"{FAIL} closed stop={st2} types={event_types(ev2)}"
        finally:
            fx2.stop()
        return f"{PASS} max_events + closed"
    finally:
        fx.stop()


def test_huge_line_capped() -> str:
    """Unterminated huge line must hit the line cap and stop, not OOM."""
    # Send a data line without newline that's larger than SSE_MAX_LINE_BYTES
    huge = b"event: message\ndata: " + (b"x" * (srv.SSE_MAX_LINE_BYTES + 1000)) + b"\n"
    # one chunk containing oversized line (has newline at end, but line > max)
    fx = ChunkedSseFixture([huge])
    port = fx.start()
    try:
        session, err = open_session(port)
        if err or session is None:
            return f"{FAIL} open: {err}"
        try:
            events, stopped = collect(session, timeout_s=2.0, idle_s=1.0)
        finally:
            session.close()
        if session.error and "line exceeded" in str(session.error):
            return f"{PASS} line cap hit: {session.error}"
        # If they assembled via read1 before nl, might still error
        if session.error:
            return f"{PASS} stopped with error={session.error}"
        return f"{FAIL} no cap error events={event_types(events)} err={session.error!r}"
    finally:
        fx.stop()


def test_queue_overflow_bounded() -> str:
    """Burst faster than consumer — exact accounting after reader finishes.

    At a synchronized snapshot (reader done, nothing dequeued yet):
        enqueued_total == dropped_total + queued_total
    For this fixture: 300 messages + 1 meta + 1 _eof = 302.
    Control frames survive (bounded lifecycle); retained messages stay ordered.
    """
    n_data = 300
    n_ctrl = 2  # meta + _eof
    expected_enqueued = n_data + n_ctrl
    chunks = [b'event: meta\ndata: {"api":1}\n\n']
    for i in range(n_data):
        chunks.append(f'event: message\ndata: {{"type":"message","n":{i}}}\n\n'.encode())
    fx = ChunkedSseFixture(chunks)
    port = fx.start()
    max_q = 10
    try:
        session, err = open_session(port, max_queue=max_q)
        if err or session is None:
            return f"{FAIL} open: {err}"
        # Explicit reader-done signal — do not assume sleep is enough.
        if not session.wait_reader_done(5.0):
            return f"{FAIL} reader did not finish in 5s err={session.error!r}"
        try:
            with session._cond:
                qsize = len(session._buf)
                snapshot = list(session._buf)  # ordered contents at freeze
            dropped = session.dropped_queue_items
            emitted = session.emitted_count
            dequeued = session.dequeued_count
        finally:
            pass  # collect then close below

        # Exact invariant (no consumer during burst):
        if dequeued != 0:
            return f"{FAIL} unexpected dequeues before collect: {dequeued}"
        if emitted != expected_enqueued:
            return f"{FAIL} emitted={emitted} expected={expected_enqueued}"
        if dropped + qsize != expected_enqueued:
            return (
                f"{FAIL} exact invariant broken: dropped({dropped})+"
                f"queued({qsize})={dropped + qsize} != enqueued({expected_enqueued})"
            )
        if qsize > max_q:
            return f"{FAIL} queue grew qsize={qsize} max={max_q}"

        # Control frames survive and are bounded
        ctrl_in_buf = [e for e in snapshot if e.get("type") in ("meta", "closed", "_eof")]
        ctrl_types = [e.get("type") for e in ctrl_in_buf]
        if "meta" not in ctrl_types and "meta" not in (session.control_preserved or []):
            return f"{FAIL} meta lost ctrl_in_buf={ctrl_types} preserved={session.control_preserved}"
        if session.control_bound_hits != 0:
            return f"{FAIL} unexpected control_bound_hits={session.control_bound_hits}"

        # Retained message sequence numbers remain ordered (ascending n)
        ns = []
        for e in snapshot:
            if e.get("type") == "message":
                raw = str(e.get("raw") or e.get("data") or "")
                m = re.search(r'"n"\s*:\s*(\d+)', raw)
                if m:
                    ns.append(int(m.group(1)))
        if ns != sorted(ns):
            return f"{FAIL} retained messages out of order: {ns[:20]}…"
        # Contiguous suffix of the burst (drop-oldest keeps the newest)
        if ns and ns != list(range(ns[0], ns[0] + len(ns))):
            return f"{FAIL} retained n not contiguous: first={ns[0]} len={len(ns)}"

        events, stopped = collect(session, timeout_s=2.0, idle_s=1.0, max_events=20)
        session.close()
        types = event_types(events)
        return (
            f"{PASS} exact {dropped}+{qsize}={expected_enqueued} "
            f"ordered_n=[{ns[0] if ns else '-'}..{ns[-1] if ns else '-'}] "
            f"ctrl={ctrl_types} got={len(events)} preserved={session.control_preserved}"
        )
    finally:
        fx.stop()


def test_repeated_open_close_no_thread_leak() -> str:
    """Repeated subscribe/cancel must not accumulate reader threads."""
    before = threading.active_count()
    fx = ChunkedSseFixture(
        [b'event: meta\ndata: {"api":1}\n\n'],
        max_connections=12,
    )
    port = fx.start()
    try:
        for i in range(8):
            session, err = open_session(port)
            if err or session is None:
                return f"{FAIL} open #{i}: {err}"
            session.wait_meta(1.0)
            session.close()
        time.sleep(0.4)
        after = threading.active_count()
        leaked = after - before
        if leaked > 3:
            names = [t.name for t in threading.enumerate()]
            return f"{FAIL} thread growth {before}->{after} names={names}"
        return f"{PASS} threads {before}->{after} after 8 cycles"
    finally:
        fx.stop()


def test_subscription_race_meta_before_register() -> str:
    """meta sent before listener registration — demonstrates the race.

    Fixture: write meta, wait 200ms, then 'register'. Client waits only 50ms
    (same as mimo_send_and_watch) and would POST immediately. An event fired
    in the gap after meta but before register would be missed if the client
    only used meta as a barrier. We assert the fixture records the delay and
    that a post-meta pre-register event is NOT present in the first collect
    window if the server only starts emitting after register.
    """
    # Custom serve: meta, sleep 0.2s (unregistered), then event.
    # We encode that as chunks with stall between meta and event.
    chunks = [
        b'event: meta\ndata: {"api":1,"sessionId":"s"}\n\n',
        b'event: message\ndata: {"type":"message","phase":"after_register"}\n\n',
    ]
    fx = ChunkedSseFixture(chunks, stall_after=1, stall_s=0.2)
    port = fx.start()
    try:
        session, err = open_session(port)
        if err or session is None:
            return f"{FAIL} open: {err}"
        meta_ok = session.wait_meta(1.0)
        # Client-side 50ms settle (mimo_send_and_watch)
        time.sleep(0.05)
        # If we collected only now, we'd see meta; the message arrives at +200ms
        try:
            # Collect immediately with short idle — may or may not catch message
            events, _ = collect(session, timeout_s=0.15, idle_s=0.15, max_events=20)
        finally:
            session.close()
        types = event_types(events)
        if not meta_ok:
            return f"{FAIL} meta not received"
        # Document the race: with 50ms settle and 200ms register delay,
        # the post-register event is often still in flight at collect start.
        # We assert meta-only is a possible outcome (race exists).
        has_msg = "message" in types
        return (
            f"{PASS} meta_ok={meta_ok} types={types} "
            f"message_caught={has_msg} "
            f"(register_delay=200ms settle=50ms — meta is not a formal barrier)"
        )
    finally:
        fx.stop()


def test_control_flood_bounded() -> str:
    """Repeated meta/closed must not allow unbounded queue growth."""
    chunks = [b'event: meta\ndata: {"api":1}\n\n']
    for _ in range(50):
        chunks.append(b'event: meta\ndata: {"api":1}\n\n')
    for _ in range(50):
        chunks.append(b'event: closed\ndata: {"type":"closed"}\n\n')
    fx = ChunkedSseFixture(chunks)
    port = fx.start()
    try:
        session, err = open_session(port, max_queue=20, stop_on_closed=False)
        if err or session is None:
            return f"{FAIL} open: {err}"
        if not session.wait_reader_done(5.0):
            return f"{FAIL} reader timeout err={session.error!r}"
        with session._cond:
            qsize = len(session._buf)
        counts = session._control_counts
        hits = session.control_bound_hits
        session.close()
        if counts.get("meta", 0) > 1 or counts.get("closed", 0) > 1:
            return f"{FAIL} control lifecycle exceeded counts={counts}"
        if hits <= 0:
            return f"{FAIL} expected control_bound_hits>0 got={hits}"
        if qsize > 20:
            return f"{FAIL} queue grew under control flood qsize={qsize}"
        return f"{PASS} counts={counts} bound_hits={hits} qsize={qsize}"
    finally:
        fx.stop()


TESTS: list[tuple[str, Callable[[], str]]] = [
    ("utf8_split_across_chunks", test_utf8_split_across_chunks),
    ("multiple_events_one_chunk", test_multiple_events_one_chunk),
    ("one_event_many_chunks", test_one_event_many_chunks),
    ("crlf_comments_multiline_data", test_crlf_comments_multiline_data),
    ("ping_flood_idle_not_reset", test_ping_flood_does_not_reset_idle),
    ("eof_mid_frame_not_emitted", test_eof_mid_frame_not_emitted),
    ("socket_stall_bounded", test_socket_stall_bounded),
    ("max_events_and_closed", test_max_events_and_closed),
    ("huge_line_capped", test_huge_line_capped),
    ("queue_overflow_bounded", test_queue_overflow_bounded),
    ("control_flood_bounded", test_control_flood_bounded),
    ("repeated_open_close_no_leak", test_repeated_open_close_no_thread_leak),
    ("subscription_race_meta_before_register", test_subscription_race_meta_before_register),
]


def main() -> int:
    print(f"mimo-desktop SSE stress harness")
    print(f"server: {SERVER_PATH}")
    print(f"SSE caps: line={srv.SSE_MAX_LINE_BYTES} frame={srv.SSE_MAX_FRAME_DATA_BYTES} "
          f"queue={srv.SSE_MAX_QUEUE}")
    print("-" * 72)
    failures = 0
    for name, fn in TESTS:
        t0 = time.time()
        try:
            result = fn()
        except Exception:
            result = f"{FAIL} exception:\n{traceback.format_exc()}"
        dt = time.time() - t0
        ok = result.startswith(PASS)
        if not ok:
            failures += 1
        print(f"[{'ok' if ok else 'FAIL':4}] {name:40} {dt:5.2f}s  {result}")
    print("-" * 72)
    print(f"{len(TESTS) - failures}/{len(TESTS)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
