# Security

## What firmcall touches

- **The company profile** the person writes with it (`firm-profile.json`), read-only.
- **Writes** only into the folder named with `--out` (default `company-AI/`): the company's plugin, its
  catalogue, a zip, the rules files and the install scripts. It refuses a folder that is not empty unless
  `--force` is given.
- **Never** writes Claude Code's system folders itself. `managed/install.sh` and `install.ps1` do that when an
  administrator runs them; Jamf and Intune do it when the administrator uploads the exports.

## What it never does

- Never buys, subscribes, opens a checkout or asks for a card, a password or an API key.
- Never goes to the network: Python's standard library only; no network module is imported (a test fails the
  build if one appears). `tests/live_window.py` starts a stand-in model on 127.0.0.1 for the live check; it
  is a test, not part of the plugin people run.
- Never puts a credential into the rules: `managed-mcp.json` and `managedMcpServers` are readable by every user
  of a computer, so people sign in to MCP servers with their own accounts.

## Reporting

Open an issue on github.com/vadimchernets/firmcall, or write to the author through the Poly A1 support address.
