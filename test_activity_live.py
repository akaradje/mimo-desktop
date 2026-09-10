"""Opt-in native indicator test; verifies visibility and no foreground change."""
import json
from pathlib import Path
import subprocess
import sys
import time
import desktop_control as d


def main():
    if '--run' not in sys.argv:
        print('Pass --run to display a short activity indicator test.')
        return 0
    foreground = d.U.GetForegroundWindow()
    process = subprocess.Popen([sys.executable,str(Path(__file__).with_name('activity_overlay.py'))],
        stdin=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        for state in ('running','waiting_for_focus','done'):
            process.stdin.write((json.dumps({'operation':'indicator_test','state':state,'time':time.monotonic()})+'\n').encode())
            process.stdin.flush()
            time.sleep(.3)
            desktop = d.Desktop(None,None,None)
            windows = [w for w in desktop.list_windows({})['windows'] if w['pid']==process.pid]
            assert len(windows)==1, 'Indicator is not visible'
            assert d.U.GetForegroundWindow()==foreground, 'Indicator changed foreground'
        print('PASS indicator visible, state updates, foreground unchanged')
    finally:
        process.stdin.close()
        process.wait(timeout=5)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
