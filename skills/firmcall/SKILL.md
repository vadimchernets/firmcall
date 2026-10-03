---
name: firmcall
description: Write a company's own Claude plugin and put the same rules on every computer. Use it when someone sets AI up for a company - "make us a plugin for our contracts / reports / tickets", "the same rules on every laptop", rolling Claude Code out with Jamf or Intune, the claude.ai admin console, Cowork plugins for the team, which folders the AI must never read, which MCP servers the company allows, or when a settings file should be checked before it reaches everyone. It writes and checks; it buys nothing.
argument-hint: "[init | build | export | lint | surface | check | rls] [what the company needs]"
allowed-tools: Bash(sh "${CLAUDE_PLUGIN_ROOT}/hooks/python.sh" firmcall say skills/firmcall/scripts/firmcall.py *) PowerShell(${CLAUDE_PLUGIN_ROOT}/hooks/python.ps1 firmcall say skills/firmcall/scripts/firmcall.py *) Read Write Edit
---

# firmcall: the company's own plugin, and its rules on every computer

## Running firmcall's scripts (Mac, Linux, Windows)

Every command here is written for the **Bash** tool and starts with
`sh "${CLAUDE_PLUGIN_ROOT}/hooks/python.sh" firmcall say skills/firmcall/scripts/firmcall.py`. If your shell tool is
**PowerShell** (Windows without Git Bash), only the start changes: the launcher's path bare, with no quotes and no
`&` — `${CLAUDE_PLUGIN_ROOT}/hooks/python.ps1 firmcall say skills/firmcall/scripts/firmcall.py …` — on one line.
Only if that path has a space in it, write `& "${CLAUDE_PLUGIN_ROOT}/hooks/python.ps1" …` (the person is asked
once). Never call `python3`, `python` or `py` yourself. If the launcher says firmcall "is paused" until this computer
has Python 3, say so in one plain line and write the files by hand from the shapes below.

The user said: $ARGUMENTS

Answer in the person's language. **firmcall writes and checks; it buys nothing.** Seats are bought by the person
responsible for the company's accounts (billcall counts them).

## 1. The interview (10 minutes)

The company knows its own work best; ask, one question at a time, in plain words:

1. What does the company do, and how many people? (A sector template may fit: run
   `… firmcall.py templates` and offer the closest — legal, finance, marketing agency, customer support,
   small business.)
2. **Which three to five things do your people do most often** that a capable assistant could do or prepare?
   For each: when it happens, what goes in, the steps, what comes out, and how a good result is recognised
   (these become the skill's checks), and one real example with the words a good answer must contain.
3. Which folders must never be read by any AI (contracts, HR, client data)? These are the red folders.
4. A daily or monthly AI budget, if any. The language of the team. Mac, Windows or both; Jamf, Intune or none.
5. Systems the agent should reach (a CRM, a database) — as MCP servers each person signs in to, or read-only
   database access.

Start from `… firmcall.py init --company "<name>" --language <code> [--template <sector>]`, then edit
`firm-profile.json` with their answers (the full shape is `${CLAUDE_PLUGIN_ROOT}/data/examples/agency-10.json`;
read it first). Show them the tasks back in their words before building.

## 2. Build (1 minute)

`… firmcall.py build firm-profile.json --out company-AI` (add `--jamf` and/or `--intune` for many computers).
It prints where each surface works. Then run the company's own tests:
`python3 -m pytest -q tests` inside `company-AI/<slug>-plugins/<slug>-ai` — through the launcher is not needed
for the company's plugin if they have Python; otherwise read the tests and check by eye. Then
`… firmcall.py check company-AI` must say 0 problems.

Tell them what they now have, in their words: their own assistant skills, the rules for every computer, and
`ROLLOUT.md` — the steps with minutes. Walk them through ROLLOUT.md step by step; each step names its minutes.

## 3. The administrator's path

- **One computer**: `sudo sh company-AI/managed/install.sh` (Mac, Linux) or `install.ps1` in an administrator
  PowerShell (Windows) — 2 minutes. Then `/status` in Claude Code names the managed settings.
- **Many computers**: the Jamf profile and script, or the Intune platform script — 10 minutes in their console.
- **Cloud sessions**: paste `managed/server-managed-settings.json` in claude.ai > Organization settings > Claude
  Code > Managed settings. Both are needed: a window on another model never reads the console.
- **Cowork and chat**: claude.ai > Organization settings > Plugins & skills — the repository or the zip.
- **The phone remote**: an Owner turns Remote Control on at claude.ai/admin-settings/claude-code.

## 4. Lint before anything reaches everyone

`… firmcall.py lint <file or folder> [--trusted-devices] [--server console.json]` on any settings the company
already has. Say each finding plainly and fix it with them:
- `remote-off`: `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` or `DISABLE_GROWTHBOOK` — the phone remote stops for
  everyone. Remove it (routecall keeps it inside a local-red window only).
- `trusted-devices-off`: `DISABLE_TELEMETRY` / `DO_NOT_TRACK` while Trusted Devices is required.
- `global-base-url`: a model endpoint for every session; give a cheaper model its own window (routecall).
- `managed-only-key`: such a key does nothing outside managed settings (`modelPricing` among them).
- `single-slash-path`: `Read(/Users/…)` anchors at the settings file; absolute is `//Users/…`.
- `bypassable-rule`: a deny rule only the console carries; put it in the device file too. A red folder's Read or
  Edit rule is the exception: the device file enables gatecall instead, whose hook holds the folder on every route
  and opens it to the red window (routecall's `profile local-red`) only.

## 5. Where a plugin works

`… firmcall.py surface <plugin folder>`: Claude Code loads everything; Cowork loads skills, hooks and agents;
chat loads skills only. A top-level `bin/` is refused by the organisation's plugin library — scripts go into
`skills/<name>/scripts/`.

## 6. Databases

`… firmcall.py rls firm-profile.json` prints the SQL for a read-only role with row-level security: the agent
reads each person's own rows and writes nothing. The database owner runs it (10 minutes).
