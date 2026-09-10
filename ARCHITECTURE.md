# Architecture: observe, deliver, verify

## Visible activity and motion scheduling (1.9.0)

`activity.py` sends operation/state/time events through a bounded queue to a
separate native Win32 overlay process. No MCP JSON-RPC output is written by the
helper. NOACTIVATE and disabled-window styles prevent it from taking focus or
receiving mouse hits. Native painting keeps text readable despite disabled state.
The indicator is best-effort and is not used to infer whether an input succeeded.

`motion.py` separates interpolation/timing from Win32 validation and movement
callbacks. A monotonic absolute schedule prevents per-frame validation cost from
accumulating into timing drift. Smoothstep easing reduces abrupt acceleration;
late frames are skipped, but the final point is always emitted. Safety checks
remain before each delivered point, and exceptions still unwind drag cleanup.
This intentionally favors target correctness over claiming constant 60 FPS.

Version 1.8.0 makes a critical distinction explicit: successful input injection
is not successful application behavior. A Windows input API can accept every
event while the editor transforms Unicode or the destination rejects a drop.

## Layers

```mermaid
flowchart TD
    Host[MCP host] --> RPC[server.py: JSON-RPC and tool dispatch]
    RPC --> Desktop[desktop_control.py: observation and operation coordinator]
    Desktop --> Win32[Win32 input and window geometry]
    Desktop --> Clipboard[clipboard_text.py: explicit clipboard transport]
    Desktop --> Reader[uia_reader.py: bounded subprocess request]
    Reader --> Worker[uia_worker.py: read-only UIA provider adapter]
    Worker --> App[Application accessibility provider]
    Desktop --> Contract[result_contract.py: delivery vs verification]
    Contract --> Host
```

### Observation and validation

An observation binds HWND, PID, executable path, and physical client geometry.
The in-memory ID expires after 60 seconds and is consumed by an action. UI element
actions also revalidate runtime ID, name, control type, automation ID, and bounds.
These are freshness checks, not authentication or a sandbox. The application can
change between any two calls; Windows does not make screenshots and input atomic.

### Delivery adapters

- **Unicode SendInput:** retained for compatibility and apps where it works.
  KEYEVENTF_UNICODE reaches the application's input path, where IMEs or app logic
  may transform it. The server cannot fix that by counting injected events.
- **Explicit clipboard paste:** `desktop_paste_text` publishes CF_UNICODETEXT and
  sends Ctrl+V after rechecking foreground. It is the recommended mixed-script path.
  It does not silently change the default of the existing typing API, select all,
  restore old clipboard contents, or automatically retry an incorrect insertion.
- **Mouse drag:** coordinate motion plus button/modifier events. Cross-window
  pickup and drop dwell are configurable; during dwell the target and Escape state
  are checked every 25 ms plus provider/check overhead. Cleanup attempts release
  even after failure. This is not an OLE IDataObject/IDropTarget implementation.

Clipboard allocation uses movable global memory; ownership transfers to Windows
only after SetClipboardData succeeds. A private message-only window provides
clipboard ownership. Text remains in the clipboard because an asynchronous paste
may read it after the tool returns; an immediate restore would introduce a race.

## Result contract

| Operation | Result meaning |
|---|---|
| Input operation | `outcome: input_delivered`, `verification: not_performed` |
| Exact text readback matches | `outcome: verified`, `matched: true` |
| Exact text differs | `outcome: mismatch`, `matched: false` |
| Provider cannot expose text | `outcome: unavailable`, `matched: null` |
| Window geometry | `geometry_verified` or `geometry_mismatch` |

`ok` retains backward-compatible meaning: the operation returned normally.
Clients must inspect `outcome`/`verification` to determine what evidence exists.
`verified` is scoped to a particular text assertion, not the entire task.
Name-only checks remain a separate tool and cannot prove document contents.

## Exact text verification

1. Inspect the editor after input, obtaining a fresh element observation.
2. Select the actual editor element, not the window title or a toolbar button.
3. Call `desktop_verify_text` with `expected_text`.
4. The coordinator revalidates the element and requests readback in the worker.
5. The worker tries UIA ValuePattern, then TextPattern. It compares exact text
   without whitespace normalization and returns the result without actual contents.

Expected text is limited to 2,000 characters and sent through subprocess stdin,
not command-line arguments. TextPattern reads at most 4,097 characters so it can
detect over-limit content. ValuePattern has no length parameter and can return a
larger value before the limit check. Password controls are not traversed or read.
There is no OCR-based guess, and unavailable providers never count as a match.

Each provider call is isolated in a subprocess with an eight-second timeout.
An operation can perform more than one provider call, so this is not an eight-second
overall tool deadline. Killing a stuck reader is safe because that worker has no
mutation commands. A persistent worker could reduce startup latency, but would
need independent cancellation and provider-recovery design; it is not claimed here.

## Recovery states

```mermaid
stateDiagram-v2
    [*] --> Observed
    Observed --> Rejected: expired, changed, invalid
    Observed --> WaitingForFocus: foreground unavailable
    Observed --> InputDelivered: validated input
    InputDelivered --> Observed: inspect again
    Observed --> Verified: exact text readback matches
    Observed --> Mismatch: readback differs
    Observed --> Unavailable: provider cannot read text
    WaitingForFocus --> Observed: user selects window and fresh observation
```

The host orchestrates this sequence; it is not an automatic workflow engine.
No operation automatically repeats a paste or drop. A refused activation suppresses
further activation attempts for that target until foreground is observed manually.
This respects Windows focus arbitration instead of injecting unrelated Alt keys
or forcing thread-input attachment. It does not eliminate user focus assistance.

## Drag reliability and limits

`pickup_ms` defaults to 150 and `drop_ms` to 300; both accept 50–2,000 ms.
These waits give the source/destination processing time and can be tuned, but
they do not prove why a particular Explorer-to-Notepad drop failed. Window geometry,
target visibility, input cleanup, and readback are separate concerns. The release
does not automatically verify file-open semantics and does not claim universal
drag-and-drop acceptance. An app-specific postcondition is still required.

## Tests and evidence

Unit tests cover contracts, identity changes, clipboard failures, and invalid dwell.
Live fixture tests check real window input and native editor text readback, including
a same-length-independent exact comparison and deliberate mismatch. These complement
but do not replace user testing with Notepad, Explorer, specific IMEs, and custom apps.
