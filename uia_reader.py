"""Bounded read-only UIA calls over one long-lived worker. Never retries desktop actions.

The worker is reused so a warm provider is not rebuilt for every call. A stuck or
dead worker is discarded instead of reused, so a wedged provider cannot poison
later calls. Requests are serialized: the coordinator is single-threaded, and this
module does not add concurrency on top of it.

A timed-out read is retried once on a fresh worker (see read_ui). Injected input is
never retried; only reads, which cannot duplicate an action.
"""
import atexit
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading

DEFAULT_TIMEOUT = 8.0
GRACE_SECONDS = 0.5


class ProviderTimeout(RuntimeError):
    """The provider did not answer within the deadline.

    Distinct from the other transport failures because a timed-out read has no side
    effects to undo: the worker has no mutation commands. That is what makes one
    bounded retry safe here, unlike injected input.
    """


class UiaWorker:
    """One worker process, one request at a time.

    A reader thread drains stdout into a queue so a deadline can be enforced
    without blocking on a partial response. Each worker owns its own queue, so a
    replaced worker's reader cannot deliver a stale line to its successor.
    """

    def __init__(self, timeout=DEFAULT_TIMEOUT, script=None, python=None):
        self.timeout = timeout
        self.script = script or str(Path(__file__).with_name('uia_worker.py'))
        self.python = python or sys.executable
        self.process = None
        self.lines = queue.Queue()
        self.reader = None
        self.counter = 0

    def start(self):
        self.lines = queue.Queue()
        self.process = subprocess.Popen(
            [self.python, self.script, '--serve'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW)
        self.reader = threading.Thread(target=self._pump, args=(self.process.stdout, self.lines),
                                       daemon=True)
        self.reader.start()

    def _pump(self, stream, lines):
        try:
            for line in iter(stream.readline, b''):
                lines.put(line)
        except (OSError, ValueError):
            pass
        finally:
            # A closed pipe ends the worker: wake any waiter with a terminal marker.
            lines.put(None)

    def stop(self):
        """Close stdin so the worker can exit on EOF, then reap it; kill only if it refuses."""
        process, self.process = self.process, None
        self.reader = None
        if process is None:
            return
        try:
            if process.stdin is not None:
                process.stdin.close()
        except OSError:
            pass
        try:
            process.wait(timeout=GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                process.wait(timeout=GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                pass
        try:
            if process.stdout is not None:
                process.stdout.close()
        except OSError:
            pass

    def request(self, hwnd, verification=None):
        if self.process is None or self.process.poll() is not None:
            # Nothing has been sent yet, so replacing the transport cannot duplicate work.
            self.stop()
            self.start()
        self.counter += 1
        payload = json.dumps({'id': self.counter, 'hwnd': int(hwnd),
                              'verification': verification or {}}).encode('utf-8')
        try:
            self.process.stdin.write(payload + b'\n')
            self.process.stdin.flush()
        except (OSError, ValueError) as exc:
            raise RuntimeError('UI Automation worker could not accept a request') from exc
        try:
            line = self.lines.get(timeout=self.timeout)
        except queue.Empty:
            raise ProviderTimeout(f'UI Automation timed out after {self.timeout:g} seconds; '
                                  'provider may be unresponsive')
        if line is None:
            raise RuntimeError('UI Automation worker failed; check pywinauto installation')
        try:
            response = json.loads(line.decode('utf-8'))
        except (ValueError, UnicodeError) as exc:
            raise RuntimeError('UI Automation returned an invalid response') from exc
        if not isinstance(response, dict) or response.get('id') != self.counter:
            raise RuntimeError('UI Automation returned an invalid response')
        return response


_worker = None


def _acquire():
    global _worker
    if _worker is None:
        _worker = UiaWorker()
        _worker.start()
    return _worker


def _discard():
    """Drop the current worker. The next call starts a fresh one."""
    global _worker
    worker, _worker = _worker, None
    if worker is not None:
        worker.stop()


@atexit.register
def _shutdown():
    _discard()


def read_ui(hwnd, verification=None, retry_on_timeout=True):
    """Read-only UIA request. Transport failures discard the worker, never retry it.

    A timeout is the one bounded exception. It usually means a slow provider rather
    than a wedged one — a Chromium window that is busy re-rendering is the live case —
    and because the timed-out worker is discarded and a read mutates nothing, retrying
    on a fresh worker cannot duplicate an action. The retry is reported as `retried`
    so the doubled worst-case latency is never silent.

    Callers that poll pass retry_on_timeout=False: they already retry by design, and a
    nested retry would multiply the wait instead of bounding it.
    """
    attempts = 2 if retry_on_timeout else 1
    for attempt in range(1, attempts + 1):
        worker = _acquire()
        try:
            response = worker.request(hwnd, verification)
        except ProviderTimeout:
            _discard()
            if attempt == attempts:
                raise
            continue
        except Exception:
            _discard()
            raise
        if not response.get('ok'):
            raise RuntimeError('UI Automation unavailable: ' + str(response.get('error', 'unknown')))
        response.pop('id', None)
        if attempt > 1:
            response['retried'] = True
        return response
