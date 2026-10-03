# Changelog

## 0.1.1 — 2026-10-03

- Zenodo DOI: the repository is archived on Zenodo; this release is the first one it records (same content as 0.1.0).

## 0.1.0 — 2026-10-02

- First release: `init`, `templates`, `build`, `export --jamf/--intune`, `lint`, `surface`, `check`, `policy`, `rls`.
- `build` writes the company's own plugin (one skill per task, with examples and tests), its private catalogue, a
  zip for the organisation's plugin library, `managed-settings.d/50-company.json`, the claude.ai console copy,
  `managed-mcp.json` when the MCP set is fixed, `company-ai-policy.json`, install scripts, the Jamf profile and
  script, the Intune script, `rls.sql` and `ROLLOUT.md` in the company's language.
- Sector templates: legal, finance, marketing agency, customer support, small business.
- Live check `tests/live_window.py`: with a real Claude Code talking to a stand-in model endpoint, the deny rule
  a cloud window carries for a red folder keeps it unread (and without the rule the same read goes through).
- The red folders' deny rules go to the claude.ai console copy only; the device file enables gatecall instead, whose
  hook holds them on every route and opens them to the red window (routecall's `profile local-red`) — a deny rule
  in the device file would shut that window too. A profile with red folders gets gatecall and `fail_closed: true`;
  `install.sh` / `install.ps1` put `managed/fallback/50-company.json` (the same rules plus the plain deny) on a
  computer with no working Python 3, where the hook cannot run.
- `init --template` starts from a neutral profile (nothing of the example agency); a profile's own open plugins
  are kept beside the template's.
