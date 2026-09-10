# Changelog

## 1.9.2

- Refine the activity badge into a rounded charcoal capsule with an animated
  activity orbit, action subtitle, subtle outline, and separate timer chip.
- Animate only while a desktop tool is running; preserve focus-wait/error colors.
- Avoid default STATIC text repainting over the custom renderer.

## 1.9.1

- Restyle the activity indicator as a compact rounded dark card with human-readable
  action labels, muted secondary text, right-aligned elapsed time, and state colors.
- Preserve non-activating/click-through behavior; release custom fonts and brushes.

## 1.9.0

- Add a visible native activity badge with operation, elapsed time, completion/error/focus-wait states.
- Isolate status IPC in a bounded background queue; do not expose text, clipboard data, or window titles.
- Use a disabled, non-activating, topmost native window; opt out with `MIMO_DESKTOP_OVERLAY=0`.
- Add smoothstep pointer motion on an absolute monotonic schedule; skip overdue frames instead of adding drift.
- Ease pointer travel before coordinate/element clicks and scroll; split wheel input into paced ticks.
- Retain exact endpoint, target checks, Escape cancellation, and drag release cleanup.
- Add motion and indicator regression tests; 64 unit tests.

## 1.8.0

- Separate input delivery from semantic verification in `result_contract.py`.
- Add explicit `desktop_paste_text` as the recommended mixed-script transport.
- Add `desktop_verify_text` using UIA ValuePattern/TextPattern, without returning document contents.
- Add configurable cross-window pickup/drop dwell with cancellation and target checks.
- Document architectural boundaries, compatibility, and postcondition limitations.
- 28 tools; 57 unit tests; native editor text match/mismatch live checks.

## 1.7.0

- Add `desktop_inspect`: screenshot plus a bounded UI Automation tree.
- Add `desktop_click_element`: revalidate runtime identity and geometry before clicking.
- Add `desktop_verify_element`: exact accessible-name checks without claiming full document verification.
- Add `desktop_set_window_rect`: move/resize with requested versus actual geometry.
- Isolate read-only UIA provider calls in an 8-second subprocess timeout.
- Add structured desktop error results and elapsed timing on normal results.
- Add pywinauto dependency and real native-checkbox / window-layout checks.
- 26 tools; 50 unit tests; 8 single-window and 2 cross-window live scenarios.

## 1.6.2

- Return structured `waiting_for_focus` errors with manual recovery instructions.
- Suppress repeated activation attempts after Windows refuses foreground until
  the target is observed already in foreground.
- Invalidate observations on focus failures and test refusal, recovery, and tool output.

## 1.6.1

- Add explicit `method: clipboard` to text entry for application/IME Unicode mis-mapping.
- Keep key-event typing as the default; clipboard mode replaces and retains clipboard text.
- Recheck foreground after clipboard access, and do not paste after clipboard errors.
- Add regression coverage for mixed Thai/Latin encoding and clipboard resource cleanup.
- Document fresh-observation recovery for focus changes and consumed/expired IDs.

## 1.6.0

- Add cross-window dragging with two observed window IDs.
- Add Ctrl, Shift, and Alt modifiers to both drag tools.
- Retain up to eight recent window observations when explicitly requested.
- Share mouse/modifier release cleanup and test real two-window drops.
- Publish portable paths, English documentation, MIT licensing, and Windows CI.

## 1.5.0

- Add smooth single-window dragging, optional waypoints, and Escape cancellation.
- Check target identity and geometry throughout the gesture.
- Invalidate stale observations when a refresh fails.

## 1.4.0

- Add window listing, observation, clicking, Unicode typing, key chords, and scrolling.
- Add physical-pixel DPI handling and one-use observation tokens.

## 1.3.4

- Raise the bounded JSON response limit to 16 MiB.
- Reject oversized responses explicitly instead of parsing truncated JSON as text.

## 1.3.x

- Use MCP-compatible newline-delimited JSON-RPC over stdio.
- Add bounded SSE parsing, ordered overflow accounting, and reader shutdown.
- Add window-only screenshots and automatic temporary-directory ACL verification.
