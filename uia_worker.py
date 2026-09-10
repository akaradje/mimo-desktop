"""Read-only UI Automation worker; providers are isolated behind a process timeout."""
import collections
import json
import sys


def inspect(hwnd):
    from pywinauto.uia_element_info import UIAElementInfo
    root = UIAElementInfo(hwnd)
    pending = collections.deque([(root, 0)])
    rows = []
    visited = 0
    truncated = False
    while pending and visited < 200:
        element, depth = pending.popleft()
        visited += 1
        try:
            raw = element.element
            password = bool(raw.CurrentIsPassword)
            if password:
                # Do not inspect names, values, or descendants of password controls.
                continue
            rect = element.rectangle
            identity = list(raw.GetRuntimeId())
            name = element.name
            row = {'runtime_id': identity, 'name': name[:500], 'name_truncated': len(name) > 500,
                   'control_type': element.control_type, 'automation_id': element.automation_id[:500],
                   'enabled': bool(element.enabled), 'visible': bool(element.visible),
                   'rect': [rect.left, rect.top, rect.right, rect.bottom], 'depth': depth}
            rows.append(row)
            if depth < 8:
                children = element.children()
                room = max(0, 200-visited-len(pending))
                pending.extend((child, depth+1) for child in children[:room])
                truncated |= len(children) > room
            else:
                truncated = True
        except Exception:
            truncated = True
    return {'elements': rows, 'truncated': truncated or bool(pending),
            'limits': {'nodes': 200, 'depth': 8}}


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        print(json.dumps({'ok': True, **inspect(int(sys.argv[1]))}, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}))
