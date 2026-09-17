# Changelog

## 1.11.2

- Keep a failed tool call machine-readable. The desktop handlers return a structured
  payload (`ok`/`status`/`error`/`next_action`) for the failures they expect, but an
  unexpected exception escaped that contract as a bare string — `ModuleNotFoundError:
  No module named 'PIL'` is the live case — which a client that parses the payload
  cannot interpret. Such a failure now reports `status: operation_failed` with the
  exception type preserved in `error`.
- Add `test_uia_live.py`, an opt-in live check for the two provider-backed tools.
  It derives its expected values from the live provider instead of hardcoding names,
  sends no input, and restores the window that was in front. Run it with
  `python test_uia_live.py --run`.
- 106 unit tests.

## 1.11.1

- Make the one-shot `uia_worker.py` diagnostic entry point accept the same request
  shape as `--serve`. It previously read `hwnd` only from `argv[1]` and forwarded the
  entire request as the verification payload, so a diagnostic run did not reproduce
  what the server sends. Omitting the argument surfaced as `list index out of range`
  instead of naming the missing field, and a `{"verification": ...}` payload was
  passed through unwrapped, which silently reported the target as absent.
- `hwnd` is now read from `{"hwnd": N}` on stdin, with the positional form still
  accepted, and a missing or non-integer value reports what is required.
- 103 unit tests.

## 1.11.0

- Make the whole process per-monitor DPI aware, not just the tool thread. A capture
  taken outside a tool call — `mimo_capture_window` is the live case — was virtualized
  to 96 DPI on a scaled display, so the same window reported different pixel geometry
  depending on which path captured it.
- Verify every pointer move with a readback. `SetCursorPos` reports success even when
  the desktop clamps the point, so a click could otherwise land somewhere other than
  the observed target while every call still looked successful. A clamped or refused
  move now raises and no button event is sent.
- Click UI elements at the provider's clickable point when it exposes one, falling back
  to the rectangle centre. An element whose click point falls outside the visible client
  area is rejected with a specific error instead of a confusing bounds error.
- 95 unit tests.

## 1.10.0

- Add `desktop_wait_for`: read-only polling for `window_visible`, `window_gone`, and
  `element_present`, with bounded `timeout_ms`/`interval_ms` and Escape cancellation.
  It sends no input and needs no observation, so waiting cannot disturb the target.
  A timeout returns `satisfied: false` and `outcome: condition_not_met`, which is a
  truthful answer rather than a failure. 15 desktop tools.
- Add optional case-insensitive `title_contains`/`path_contains` and exact `pid`
  filters to `desktop_list_windows`. `total_visible` still reports the unfiltered
  count, so a filter that hides everything is visible as such.
- Keep one UI Automation worker alive instead of starting a process per call, and
  replace it — never reuse it — after a timeout, a crash, or an unreadable response.
  A provider that answers with an error keeps its worker. Requests stay serialized
  and the reader still owns the eight-second deadline.
- 84 unit tests.

## 1.9.3

- Recheck foreground, target geometry, and Escape state after a drag's final
  dwell, immediately before the button is released. A late focus loss, Escape
  press, or window change now still unwinds the release path instead of leaving
  a mouse button or modifier key held down.
- Add a regression test covering focus-loss, Escape, and geometry-change
  failures during the final dwell, asserting the button and modifiers are
  released; 65 unit tests.

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
