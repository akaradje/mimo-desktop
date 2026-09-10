"""ACL failure paths: restriction/verification failure must not write PNG."""

from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "s", str(Path(__file__).resolve().with_name("server.py"))
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def test_restrict_ok() -> str:
    td = Path(tempfile.mkdtemp(prefix="mimo-shot-ok-"))
    try:
        ok, note, dacl = m._restrict_dir_acl(td)
        print("  note:", note)
        print("  dacl head:", (dacl or "")[:300].replace("\n", " | "))
        return "PASS" if ok else f"FAIL {note}"
    finally:
        import shutil

        shutil.rmtree(td, ignore_errors=True)


def test_verify_rejects_unrestricted_temp() -> str:
    """Fresh mkdtemp under %TEMP% still has inheritance — verify must fail."""
    td = Path(tempfile.mkdtemp(prefix="mimo-shot-inherit-"))
    try:
        account, sid = m._current_windows_account()
        ok, note, summary = m._verify_dir_dacl(td, account, sid)
        print("  note:", note)
        if ok:
            return "FAIL unrestricted TEMP passed verification"
        if not str(note).startswith("acl:failed"):
            return f"FAIL unexpected note: {note}"
        return f"PASS rejected ({note})"
    finally:
        import shutil

        shutil.rmtree(td, ignore_errors=True)


def test_capture_refuses_when_acl_fails(monkey_fail: bool = True) -> str:
    """If _restrict_dir_acl fails, capture must not leave a PNG in the dir."""
    # Simulate by calling the write path logic: create dir, fail restrict, rmtree
    # Directly invoke tool_capture_window after patching restrict.
    orig = m._restrict_dir_acl

    def _fail(d):
        return False, "acl:forced-fail", ""

    m._restrict_dir_acl = _fail
    try:
        # Capture needs a real window; if MiMo is running this will try PrintWindow.
        # We only care that the ACL branch refuses before write when no save_path.
        r = m.tool_capture_window({})
        r.pop("_image_b64", None)
        print("  result ok=", r.get("ok"), "err=", r.get("error"), "acl=", r.get("acl"))
        if r.get("ok") is True:
            return "FAIL capture succeeded despite ACL failure"
        if "refusing" not in str(r.get("error") or "").lower() and "acl" not in str(r.get("error") or "").lower():
            return f"FAIL unexpected error: {r.get('error')}"
        if r.get("path"):
            p = Path(r["path"])
            if p.exists():
                return f"FAIL screenshot written at {p}"
        return "PASS refused without writing"
    finally:
        m._restrict_dir_acl = orig


if __name__ == "__main__":
    print("=== restrict_ok ===")
    print(test_restrict_ok())
    print("=== verify_rejects_unrestricted_temp ===")
    print(test_verify_rejects_unrestricted_temp())
    print("=== capture_refuses_when_acl_fails ===")
    print(test_capture_refuses_when_acl_fails())
