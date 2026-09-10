# Security and trust model

This server can read application content, send keyboard/mouse input, and submit
MiMo turns. Run it only in a trusted local MCP host, under your own Windows account.

- Transport is local stdio; the server does not open a public network listener.
- The MiMo API uses a loopback address and a bearer token read from the app's
  `desktop-api.json`. Never publish that file.
- Observation IDs, foreground checks, and window identity checks reduce accidental
  targeting. They are not an authorization boundary or a sandbox.
- Screenshots, window titles, and session contents can contain private information.
  Tool results are visible to the MCP host and its configured model provider.
- Key-based redaction is best effort. Secrets inside free text are not reliably removed.
- A cancelled drag can leave partial effects. Input cleanup cannot undo a completed drop.
- The server does not bypass UAC, secure desktop, or application elevation boundaries.
- Force-quit and message submission have real side effects. Host-side permission
  controls and the operator's intent remain important.

For a suspected vulnerability, avoid posting credentials or exploit details in a
public issue. Use GitHub's **Report a vulnerability** option if available. Otherwise
open a minimal issue requesting a private contact channel without sensitive details.
