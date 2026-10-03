# firmcall

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23116718.svg)](https://doi.org/10.5281/zenodo.23116718)

The plugin that writes a company's own plugin — and the administrator's path that puts the same rules on every
computer. A [Claude Code](https://claude.com/claude-code) plugin of Poly A1, for the person in a company who sets
AI up. Repository: [github.com/vadimchernets/firmcall](https://github.com/vadimchernets/firmcall).

**firmcall writes and checks; it buys nothing, opens no checkout and never asks for a card.** Seats and plans are
bought by the person responsible for the company's accounts (billcall counts them).

## What it does

We don't know a company's tasks in advance — firmcall asks. An interview turns the three to five things its
people do most into the company's own plugin, and one profile becomes everything the rollout needs:

| Command | What the company gets |
|---|---|
| `init` | A starting profile (`firm-profile.json`): tasks, red folders, budget, language, MDM. `--template legal / finance / marketing-agency / customer-support / small-business` starts from a neutral profile and fills in sector tasks and the open plugins they build on (a profile's own open plugins are kept beside the template's); without a template, `init` writes the example agency to edit. |
| `build` | `company-AI/`: the company's own plugin — one skill per task, with examples and tests — its private catalogue, a zip for the organisation's plugin library (Cowork and chat), and `managed/` with the rules file for every computer, the claude.ai console copy, `managed-mcp.json`, the shared `company-ai-policy.json`, install scripts, `rls.sql` and `ROLLOUT.md` with minutes, in the company's language. |
| `export --jamf` / `--intune` | The rules as a macOS configuration profile (domain `com.anthropic.claudecode`) plus a Jamf policy script for the files a profile cannot carry; an Intune platform script that writes them into `C:\Program Files\ClaudeCode\`. One file reaches many laptops. |
| `lint` | Any settings file or folder against what breaks a setup without a word: `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` or `DISABLE_GROWTHBOOK` (the phone remote stops), `DISABLE_TELEMETRY` / `DO_NOT_TRACK` under Trusted Devices, a global `ANTHROPIC_BASE_URL`, `modelPricing` and other managed-only keys in a user file, `Read(/Users/…)` with one slash, a deny rule only the claude.ai console carries. |
| `surface` | Where a plugin works: Claude Code, Cowork, chat (chat loads skills only; a top-level `bin/` is refused by the organisation's library). |
| `check` | A built folder: lint, the exports carry the rules whole, every plugin's surfaces. |
| `policy`, `rls` | Only the policy file; only the read-only row-level-security SQL (Postgres or Supabase). |

What the rules file holds: gatecall enabled for the red folders (its hook holds them on every route and opens them
to the red window only — routecall's `profile local-red`; a deny rule here would shut that window too, since a deny
at any level cannot be lifted), `disableBypassPermissionsMode`, the company's
catalogue and the open sector catalogues with `autoUpdate` on, `enabledPlugins`, `strictKnownMarketplaces`
(with `skills-dir`, so people's own skills keep loading), `disableSideloadFlags`, the MCP servers the company
provides (`managedMcpServers`) or fixes (`managed-mcp.json`), and `modelPricing` when billcall wrote contract
rates. Never a variable that switches the phone remote off, never a global model endpoint.

## Why a file on every computer, and the console too

The claude.ai console reaches cloud sessions; the file reaches every session on the computer, including a window
pointed at a cheaper or local model — such a window never fetches the console's settings. firmcall writes both
from one profile. The console copy also carries the red folders' deny rules in the path forms Claude Code
documents (`~/…`, `//…` absolute, `//c/…` on Windows, a bare folder name at any depth): a session that fetches it
is always a cloud one. `lint --server` reddens a deny rule that only the console carries, except a red folder's
Read or Edit rule when the device file enables gatecall, whose hook holds it there. The hook runs on Python 3, so
`managed/fallback/50-company.json` carries the device rules plus the red folders' deny, and `install.sh` /
`install.ps1` put that one in place on a computer with no working Python 3; run the script again once Python 3 is
there, and the red window opens the red folders.

**Checked live on 2026-10-02 with Claude Code 2.1.288**: `tests/live_window.py` starts a stand-in model on
127.0.0.1, points `ANTHROPIC_BASE_URL` at it (as a GLM or Ollama window would) and lets it ask for
`clients/secret.txt`. With firmcall's rules the read was refused and the secret never reached the model; without
the rule the same read went through — so the check can fail. Run it with `FIRMCALL_LIVE=1 python3 -m pytest -q`.

## Installing

```
/plugin marketplace add https://raw.githubusercontent.com/vadimchernets/poly-a1-plugins/main/.claude-plugin/marketplace.json
/plugin install firmcall@poly-a1
```

Then say "make our company its own plugin" or "put the same rules on all our laptops".

## What it needs

Python 3.8+ and its standard library — no dependencies, no network module. Skills run their script through
`hooks/python.sh` (PowerShell: `hooks/python.ps1`), which finds a real Python and never starts the Apple or
Microsoft Store stub. Installing the rules on a computer needs an administrator once (2 minutes); Jamf or Intune
needs the company's MDM console.

## Checks

`python3 -m pytest -q tests` — the build writes every file, the company's skills pass their own tests and redden
when a check is dropped, the catalogue and plugin pass `claude plugin validate`, the zip is reproducible, the Jamf
profile carries the rules whole and passes `plutil -lint`, the Intune script writes them, every lint rule reddens
and stays quiet where it should, surfaces, five languages, no network code. `python3 tools/mutate_code.py`
breaks firmcall's rules one by one in a copy and expects red; its last line counts the mutations that misbehaved.

## Licence

Apache-2.0. See `LICENSE` and `NOTICE`.
