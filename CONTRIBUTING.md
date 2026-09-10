# Contributing

Thanks for helping make desktop automation more predictable.

## Development setup

Use Windows 10/11 and Python 3.11 or later. Clone the repository, create a virtual
environment, and install `requirements.txt`. Run the unit and local SSE tests
before submitting a change:

```powershell
python -m unittest test_desktop_control test_api_body
python test_sse_stress.py
```

The live tests require an unlocked interactive desktop. They move the pointer
and type into disposable test windows. Do not run them in a background CI job.

```powershell
python test_desktop_live.py --run
python test_cross_window_live.py --run
```

## Pull requests

- Describe the user-visible problem and the resulting behavior.
- Add regression coverage for input cleanup, target validation, or protocol changes.
- Include the Windows version, display scaling, Python version, and relevant test results.
- Preserve cleanup on error; do not automatically retry a destructive input sequence.
- Keep credentials, screenshots, session histories, and machine-specific paths out of commits.

When reporting an issue, include a minimal reproduction and sanitized errors.
Do not attach `desktop-api.json`; it contains a bearer token.

Contributions are provided under this repository's MIT License.
