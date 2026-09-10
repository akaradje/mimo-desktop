"""Bounded read-only UIA calls. Never retries desktop actions."""
import json
from pathlib import Path
import subprocess
import sys


def read_ui(hwnd):
    try:
        result = subprocess.run([sys.executable, str(Path(__file__).with_name('uia_worker.py')), str(hwnd)],
            capture_output=True, timeout=8, creationflags=subprocess.CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError('UI Automation timed out after 8 seconds; provider may be unresponsive') from exc
    if result.returncode:
        raise RuntimeError('UI Automation worker failed; check pywinauto installation')
    try:
        data = json.loads(result.stdout.decode('utf-8'))
    except (ValueError, UnicodeError) as exc:
        raise RuntimeError('UI Automation returned an invalid response') from exc
    if not data.get('ok'):
        raise RuntimeError('UI Automation unavailable: ' + str(data.get('error', 'unknown')))
    return data
