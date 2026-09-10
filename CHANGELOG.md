# Changelog

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
