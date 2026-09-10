"""Best-effort visual activity channel, isolated from MCP stdout and desktop input."""
import atexit
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time


class Activity:
    def __init__(self):
        self.events = queue.Queue(maxsize=32)
        self.thread = None
        self.process = None

    def emit(self, operation, state='running'):
        if os.environ.get('MIMO_DESKTOP_OVERLAY', '1') == '0':
            return
        if self.thread is None:
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()
        item = {'operation': operation, 'state': state, 'time': time.monotonic()}
        try:
            self.events.put_nowait(item)
        except queue.Full:
            pass  # UI telemetry must never block a desktop action.

    def _run(self):
        try:
            self.process = subprocess.Popen([sys.executable, str(Path(__file__).with_name('activity_overlay.py'))],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW)
            while True:
                item = self.events.get()
                if item is None:
                    break
                self.process.stdin.write((json.dumps(item)+'\n').encode('utf-8'))
                self.process.stdin.flush()
        except (OSError, BrokenPipeError):
            pass
        finally:
            if self.process and self.process.stdin:
                self.process.stdin.close()

    def close(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()


activity = Activity()
atexit.register(activity.close)
