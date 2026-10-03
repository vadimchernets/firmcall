#!/usr/bin/env python3
"""firmcall: the plugin that writes a company's own plugin, and the administrator's path.

From one company profile (`firm-profile.json`, written with the person in an interview) it builds the
folder `company-AI/`:

  <slug>-plugins/                  the company's private catalogue, ready to be pushed as a repository
    .claude-plugin/marketplace.json
    <slug>-ai/                     the company's own plugin: one skill per task, with examples and tests
  <slug>-ai-<version>.zip          the same plugin as one file, for the organisation's plugin library
                                   (claude.ai Organization settings > Plugins & skills, used by Cowork)
  managed/
    managed-settings.d/50-company.json   the rules file for every computer (file-based managed settings); the red
                                   folders are held there by gatecall's hook, which opens them to the red window only
    server-managed-settings.json   the same rules for the claude.ai admin console (cloud sessions), plus the red
                                   folders' deny rules - a session that fetches them is never the red window
    fallback/50-company.json       the device rules plus that deny, which install.sh / install.ps1 put in place on a
                                   computer with no working Python 3 (gatecall's hook needs it)
    managed-mcp.json               only when the company fixes its MCP servers
    company-ai-policy.json         the policy file the company plugins read (gatecall, routecall, billcall)
    install.sh, install.ps1        put the files in the system folder of one computer
    jamf/<slug>.mobileconfig       the rules as a macOS configuration profile (domain com.anthropic.claudecode)
    jamf/claude-files.sh           the Jamf policy script for the files a profile cannot carry
    intune/Set-<Slug>ClaudePolicy.ps1   the Intune platform script that writes the files on Windows
    rls.sql                        read-only role with row-level security, when the profile names databases
  ROLLOUT.md                       the administrator's steps with minutes, in the company's language

`lint` checks any settings file against the facts that break a company's setup without a word:
variables that switch the phone remote off, a global ANTHROPIC_BASE_URL, managed-only keys in a file
that is not managed, a deny rule only the claude.ai console carries (skipped when a session goes to
another endpoint), a path written with one leading slash where an absolute path was meant.
`surface` says on which surface a plugin works: Claude Code, Cowork, chat.

Facts as read on 2026-10-02 (code.claude.com/docs/en/managed-settings, /permissions, /plugins/org,
/managed-mcp, /remote-control; claude.com/docs/plugins/org-rollout). Python standard library only;
it never goes to the network and never buys anything.
"""
import argparse
import io
import json
import os
import plistlib
import re
import shutil
import sys
import uuid
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
LANG_DIR = os.path.join(ROOT, "lang")
DATA = os.path.join(ROOT, "data")
TEMPLATES = os.path.join(DATA, "templates")
LANGS = ("en", "es", "pt", "ru", "uk")

POLICY_NAME = "company-ai-policy.json"
SETTINGS_DROPIN = "50-company.json"
MANAGED_DIRS = {
    "darwin": "/Library/Application Support/ClaudeCode",
    "linux": "/etc/claude-code",
    "win32": "C:\\Program Files\\ClaudeCode",
}
MDM_DOMAIN = "com.anthropic.claudecode"
OFFICIAL = {"source": "github", "repo": "anthropics/claude-plugins-official"}
POLY_A1_URL = "https://raw.githubusercontent.com/vadimchernets/poly-a1-plugins/main/.claude-plugin/marketplace.json"
POLY_A1_COMPANY = ("billcall", "gatecall", "firmcall", "routecall", "decidecall", "teamcall")
# The plugin whose hook holds the red folders on every laptop and opens them only to the red window (routecall's
# profile local-red). A deny rule in the device file cannot do that: a deny at any level cannot be lifted.
GATECALL = "gatecall"
GATECALL_ID = "gatecall@poly-a1"
# What `init --template` starts from: nothing of another company. The template brings its tasks and the open
# plugins it builds on; the red folders, the budget, MCP servers and databases are this company's to name.
NEUTRAL_PROFILE = {"schema": 1, "version": "0.1.0", "tasks": [], "red_paths": [], "yellow_paths": [],
                   "training_folders": [], "profiles": ["default"], "allowed_providers": [], "deny_providers": [],
                   "trusted_devices": False, "marketplace": {}, "poly_a1_plugins": ["billcall", "gatecall"],
                   "mcp": {}, "databases": []}

# code.claude.com/docs/en/remote-control (2026-10-02): "If you set CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC or
# DISABLE_GROWTHBOOK, Remote Control is unavailable." DISABLE_TELEMETRY / DO_NOT_TRACK keep it "unless your
# organization requires Trusted Devices".
REMOTE_OFF_ENV = ("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "DISABLE_GROWTHBOOK")
TRUSTED_OFF_ENV = ("DISABLE_TELEMETRY", "DO_NOT_TRACK")
# A session routed away from api.anthropic.com loses Remote Control and skips server-managed settings
# (managed-settings: remote settings are fetched only when the session talks to Anthropic's API directly).
ROUTE_ENV = ("ANTHROPIC_BASE_URL", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY")
# Keys Claude Code reads only from a managed source ("Keys only a managed source can set", plus
# modelPricing, which the settings reference scopes to managed settings).
MANAGED_ONLY = {
    "allowAllClaudeAiMcps", "allowedChannelPlugins", "allowManagedHooksOnly", "allowManagedMcpServersOnly",
    "allowManagedPermissionRulesOnly", "blockedMarketplaces", "channelsEnabled", "disableCommandPluginSources",
    "disableSideloadFlags", "forceRemoteSettingsRefresh", "managedMcpServers", "managedSourcesBehavior",
    "parentSettingsBehavior", "pluginSuggestionMarketplaces", "pluginTrustMessage", "policyHelper",
    "strictKnownMarketplaces", "strictPluginOnlyCustomization", "wslInheritsWindowsSettings", "modelPricing",
    "allowClaudeInChromeWithManagedMcp",
}
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
TASK_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")


class Problem(Exception):
    """Input firmcall cannot use. Printed as one line; exit 2."""


# ---------------------------------------------------------------- words --------------------------

def load_json(path, what):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except OSError as err:
        raise Problem("%s cannot be read: %s (%s)" % (what, path, err.strerror))
    except ValueError as err:
        raise Problem("%s is not valid JSON: %s (%s)" % (what, path, err))


def lang_words(code):
    words = load_json(os.path.join(LANG_DIR, "en.json"), "the English words")
    if code in LANGS and code != "en":
        words = dict(words, **load_json(os.path.join(LANG_DIR, "%s.json" % code), "the %s words" % code))
    return words


def say(words, key, **values):
    text = words.get(key, key)
    try:
        return text.format(**values)
    except (KeyError, IndexError, ValueError):
        return text


def dump(obj):
    return json.dumps(obj, ensure_ascii=False, indent=2) + "\n"


def write(path, text, mode=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    if mode:
        os.chmod(path, mode)
    return path


# ---------------------------------------------------------------- the profile ------------------------

def templates():
    out = {}
    if os.path.isdir(TEMPLATES):
        for name in sorted(os.listdir(TEMPLATES)):
            if name.endswith(".json"):
                out[name[:-5]] = load_json(os.path.join(TEMPLATES, name), "the template %s" % name)
    return out


def check_profile(p):
    """-> the profile with defaults filled in; Problem on anything that cannot be built."""
    if not isinstance(p, dict):
        raise Problem("the profile must be one JSON object")
    p = dict(p)
    if not p.get("company"):
        raise Problem("the profile has no company name (\"company\")")
    slug = p.get("slug") or re.sub(r"[^a-z0-9]+", "-", str(p["company"]).lower()).strip("-")[:40]
    if not SLUG.match(slug or ""):
        raise Problem("the slug %r must be lower-case letters, digits and dashes" % slug)
    p["slug"] = slug
    p.setdefault("language", "en")
    if p["language"] not in LANGS:
        raise Problem("language %r: firmcall speaks %s" % (p["language"], ", ".join(LANGS)))
    p.setdefault("version", "0.1.0")
    p.setdefault("tasks", [])
    template = p.get("template")
    if template:
        known = templates()
        if template not in known:
            raise Problem("no template %r; there are: %s" % (template, ", ".join(known)))
        t = known[template]
        have = {task.get("id") for task in p["tasks"]}
        p["tasks"] = list(p["tasks"]) + [task for task in t.get("tasks", []) if task.get("id") not in have]
        # The template's open plugins join the profile's own ones; a profile's list never hides the template's.
        own = [u for u in (p.get("upstream") or []) if isinstance(u, dict)]
        mine = {(u.get("marketplace"), u.get("repo")) for u in own}
        p["upstream"] = own + [u for u in t.get("upstream", []) if (u.get("marketplace"), u.get("repo")) not in mine]
    if not p["tasks"]:
        raise Problem("the profile has no task: name at least one thing the company's people do often")
    seen = set()
    for task in p["tasks"]:
        tid = task.get("id")
        if not TASK_ID.match(str(tid or "")):
            raise Problem("task id %r must be lower-case letters, digits and dashes" % tid)
        if tid in seen:
            raise Problem("task id %r appears twice" % tid)
        seen.add(tid)
        for key in ("title", "when"):
            if not task.get(key):
                raise Problem("task %s has no %r" % (tid, key))
        if not task.get("steps"):
            raise Problem("task %s has no steps" % tid)
    for key in ("red_paths", "yellow_paths", "training_folders", "copy_folders", "allowed_providers",
                "deny_providers", "profiles", "upstream", "poly_a1_plugins", "databases"):
        value = p.get(key) or []
        if isinstance(value, str):
            value = [value]
        p[key] = list(value)
    if not p["profiles"]:
        p["profiles"] = ["default"]
    for name in p["poly_a1_plugins"]:
        if name not in POLY_A1_COMPANY:
            raise Problem("poly_a1_plugins: %r is not one of %s" % (name, ", ".join(POLY_A1_COMPANY)))
    if p["red_paths"] and GATECALL not in p["poly_a1_plugins"]:
        # Red folders are held on every laptop by gatecall's hook, so a company that names them gets gatecall.
        p["poly_a1_plugins"].append(GATECALL)
    if p.get("base_url") or any(k in (p.get("env") or {}) for k in ROUTE_ENV):
        raise Problem("the profile sets a global model endpoint (ANTHROPIC_BASE_URL or a cloud provider): it switches "
                      "the phone remote and the claude.ai console rules off for everyone. A cheaper model goes into "
                      "one window instead - routecall profile")
    mcp = p.get("mcp") or {}
    if mcp and mcp.get("mode") not in ("provided", "fixed", "none"):
        raise Problem("mcp.mode must be provided, fixed or none")
    p["mcp"] = mcp
    lock = dict({"disable_bypass": True, "strict_marketplaces": True, "disable_sideload": True,
                 "permission_rules_only": False}, **(p.get("lock") or {}))
    p["lock"] = lock
    p.setdefault("trusted_devices", False)
    p.setdefault("marketplace", {})
    if not isinstance(p["marketplace"], dict):
        raise Problem("marketplace must be an object such as {\"repo\": \"your-org/%s-plugins\"}" % slug)
    return p


# ---------------------------------------------------------------- the rules ------------------------

def deny_patterns(path):
    """Permission patterns for one red folder, in the forms code.claude.com/docs/en/permissions gives:
    `~/x` from home, `//x` absolute (Windows drives as //c/...), a bare name at any depth under the project."""
    raw = str(path).strip().replace("\\", "/").rstrip("/")
    if not raw:
        return []
    m = re.match(r"^([A-Za-z]):/(.*)$", raw)
    if m:
        base = "//%s/%s" % (m.group(1).lower(), m.group(2))
    elif raw.startswith("~/"):
        base = raw
    elif raw.startswith("/"):
        base = "/" + raw            # one slash would anchor at the settings file; two mean the filesystem root
    else:
        base = raw.lstrip("./")
    return ["Read(%s/**)" % base, "Edit(%s/**)" % base]


def company_marketplace(p):
    repo = (p.get("marketplace") or {}).get("repo")
    if repo:
        return {"source": "github", "repo": repo}
    url = (p.get("marketplace") or {}).get("url")
    if url:
        return {"source": "url", "url": url}
    path = (p.get("marketplace") or {}).get("path")
    if path:
        return {"source": "directory", "path": path}
    return {"source": "github", "repo": "your-org/%s-plugins" % p["slug"]}


def red_rules(p):
    """Read and Edit deny rules for every red folder: what a session on a cloud model never reads."""
    deny = []
    for path in p["red_paths"]:
        deny += deny_patterns(path)
    return deny


def settings_for(p, console=False):
    """The managed settings: the device file every computer gets, or (console=True) the claude.ai console's.

    The red folders' deny rules go to the console - a session that fetches it talks to api.anthropic.com, so it is
    never the red window - and routecall writes them into every cloud window. The device file is read by the red
    window too, and a deny rule at any level cannot be lifted, so there gatecall's hook holds the red folders on
    every route and opens them only to the red window (routecall's profile local-red)."""
    s = {}
    deny = red_rules(p) if (console or GATECALL not in p["poly_a1_plugins"]) else []
    deny += list((p.get("permissions") or {}).get("deny") or [])
    perms = {}
    if deny:
        perms["deny"] = sorted(set(deny), key=deny.index)
    for key in ("allow", "ask"):
        if (p.get("permissions") or {}).get(key):
            perms[key] = list(p["permissions"][key])
    if p["lock"].get("disable_bypass"):
        perms["disableBypassPermissionsMode"] = "disable"
    if perms:
        s["permissions"] = perms
    if p["lock"].get("permission_rules_only"):
        s["allowManagedPermissionRulesOnly"] = True

    name = "%s-ai" % p["slug"]
    # The official catalogue is registered explicitly: under an allowlist it registers itself only in an
    # interactive terminal, never in a -p run (code.claude.com/docs/en/plugins/org).
    known = {"claude-plugins-official": {"source": OFFICIAL},
             name: {"source": company_marketplace(p), "autoUpdate": True}}
    enabled = {"%s@%s" % (name, name): True}
    allow = [OFFICIAL, company_marketplace(p), {"source": "skills-dir"}]
    for up in p["upstream"]:
        src = {"source": "github", "repo": up["repo"]}
        known[up["marketplace"]] = {"source": src, "autoUpdate": True}
        allow.append(src)
        for plug in up.get("plugins", []):
            enabled["%s@%s" % (plug, up["marketplace"])] = True
    if p["poly_a1_plugins"]:
        src = {"source": "url", "url": POLY_A1_URL}
        known["poly-a1"] = {"source": src, "autoUpdate": True}
        allow.append(src)
        for plug in p["poly_a1_plugins"]:
            enabled["%s@poly-a1" % plug] = True
    s["extraKnownMarketplaces"] = known
    s["enabledPlugins"] = enabled
    if p["lock"].get("strict_marketplaces"):
        s["strictKnownMarketplaces"] = allow
    if p["lock"].get("disable_sideload"):
        s["disableSideloadFlags"] = True

    mcp = p["mcp"]
    if mcp.get("mode") == "provided" and mcp.get("servers"):
        s["managedMcpServers"] = mcp["servers"]
    if mcp.get("allowed"):
        s["allowedMcpServers"] = list(mcp["allowed"])
        s["allowManagedMcpServersOnly"] = True
    if mcp.get("denied"):
        s["deniedMcpServers"] = list(mcp["denied"])
    if p.get("model_pricing"):
        s["modelPricing"] = p["model_pricing"]
    if p.get("env"):
        s["env"] = dict(p["env"])
    for key in ("availableModels", "model", "cleanupPeriodDays"):
        if key in p:
            s[key] = p[key]
    return s


def policy_for(p):
    keys = ("company", "country", "language", "profiles", "red_paths", "yellow_paths", "training_folders",
            "copy_folders", "markers", "journal", "fail_closed", "max_usd_per_day", "max_usd_per_month",
            "allowed_providers", "deny_providers", "privacy_level", "trusted_devices")
    out = {"schema": 1}
    for key in keys:
        if key in p and p[key] not in (None, ""):
            out[key] = p[key]
    out.setdefault("markers", True)
    out.setdefault("journal", True)
    # With red folders the laptop's guard is gatecall's hook: if the hook itself fails, the step stops.
    out.setdefault("fail_closed", bool(p.get("red_paths")))
    return out


def mcp_file_for(p):
    mcp = p["mcp"]
    if mcp.get("mode") == "fixed":
        return {"mcpServers": dict(mcp.get("servers") or {})}
    if mcp.get("mode") == "none":
        return {"mcpServers": {}}
    return None


# ---------------------------------------------------------------- lint ------------------------------

def lint_settings(doc, managed=True, trusted_devices=False, server=None, where="settings"):
    """-> list of (level, code, text). level is 'error' or 'warn'."""
    out = []
    if not isinstance(doc, dict):
        return [("error", "not-an-object", "%s must hold one JSON object - Claude Code refuses to start on a managed "
                                           "document that is not one" % where)]
    env = doc.get("env") or {}
    for var in REMOTE_OFF_ENV:
        if var in env:
            out.append(("error", "remote-off", "%s sets %s: Remote Control (the phone remote) becomes unavailable for "
                                               "everyone it reaches. Leave it out; keep it only inside a local-red window "
                                               "(routecall)" % (where, var)))
    for var in TRUSTED_OFF_ENV:
        if var in env and trusted_devices:
            out.append(("error", "trusted-devices-off", "%s sets %s while the organisation requires Trusted Devices: "
                                                        "Remote Control stops. Leave it out" % (where, var)))
    for var in ROUTE_ENV:
        if var in env:
            out.append(("error", "global-base-url", "%s sets %s for every session: the phone remote, cloud sessions "
                                                    "and the claude.ai console rules stop. Give a cheaper model its own "
                                                    "window (routecall profile)" % (where, var)))
    if not managed:
        for key in sorted(k for k in doc if k in MANAGED_ONLY):
            level = "error" if key == "modelPricing" else "warn"
            out.append((level, "managed-only-key", "%s is not managed settings, and Claude Code reads %s only from a "
                                                   "managed source - here it does nothing" % (where, key)))
    perms = doc.get("permissions") or {}
    for kind in ("deny", "ask", "allow"):
        for rule in perms.get(kind) or []:
            m = re.match(r"^(Read|Edit)\((/[^/].*)\)$", str(rule))
            if m and re.match(r"^/(Users|home|etc|var|opt|private|Volumes|mnt|srv)/", m.group(2)):
                out.append(("error", "single-slash-path", "%s: %s anchors at the settings file's folder, not at the "
                                                          "filesystem root - write //%s" % (where, rule, m.group(2)[1:])))
    strict = doc.get("strictKnownMarketplaces")
    if strict == []:
        out.append(("warn", "all-marketplaces-locked", "strictKnownMarketplaces is empty: every catalogue is locked "
                                                      "out, Anthropic's official one too"))
    elif isinstance(strict, list) and not any(isinstance(e, dict) and e.get("source") == "skills-dir" for e in strict):
        out.append(("warn", "skills-dir-stops", "strictKnownMarketplaces has no {\"source\": \"skills-dir\"} entry: "
                                                "the plugins people keep in ~/.claude/skills stop loading"))
    if doc.get("allowManagedMcpServersOnly") and not doc.get("allowedMcpServers"):
        out.append(("warn", "no-mcp-allowed", "allowManagedMcpServersOnly without allowedMcpServers admits no MCP "
                                              "server people add"))
    if server is not None:
        here = set(perms.get("deny") or [])
        # gatecall's hook on the device holds file reads and edits of the red folders on every route, so a Read or
        # Edit rule that only the console carries is not bypassed when the device file enables gatecall.
        guarded = (doc.get("enabledPlugins") or {}).get(GATECALL_ID) is True
        for rule in (server.get("permissions") or {}).get("deny") or []:
            if rule in here or (guarded and re.match(r"^(Read|Edit)\(", str(rule))):
                continue
            out.append(("error", "bypassable-rule", "%s is only in the claude.ai console settings: a session sent "
                                                    "to another endpoint (a local model, a gateway, Bedrock) never "
                                                    "fetches them. Put it in the device file too" % rule))
    return out


def lint_path(path, managed=None, trusted_devices=False, server=None):
    if os.path.isdir(path):
        found = []
        for folder, _dirs, files in os.walk(path):
            for f in sorted(files):
                full = os.path.join(folder, f)
                if f.endswith(".json") and (f == SETTINGS_DROPIN or f.startswith("managed-settings")
                                            or f == "server-managed-settings.json"):
                    found += lint_path(full, True, trusted_devices, server)
                elif f == "settings.json" or f == "settings.local.json":
                    found += lint_path(full, False, trusted_devices, None)
        return found
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as err:
        return [("error", "unreadable", "%s cannot be read as JSON (%s) - a managed file like this stops Claude Code "
                                        "from starting" % (path, err))]
    if managed is None:
        name = os.path.basename(path)
        managed = name.startswith("managed-settings") or "managed-settings.d" in path or name == SETTINGS_DROPIN \
            or name == "server-managed-settings.json"
    srv = load_json(server, "the console settings") if isinstance(server, str) else server
    return lint_settings(doc, managed=managed, trusted_devices=trusted_devices, server=srv, where=path)


# ---------------------------------------------------------------- surfaces --------------------------

def surface_lint(plugin):
    """-> (lines, problems): where a plugin folder works. Facts: claude.com/docs/plugins/org-rollout - "Hooks
    and agents load in Cowork and Claude Code and not in chat, and a local MCP server doesn't run in chat";
    organisation sync "rejects a plugin with a top-level bin/ directory"."""
    has = lambda rel: os.path.exists(os.path.join(plugin, rel))  # noqa: E731
    problems = []
    if not has(".claude-plugin/plugin.json"):
        problems.append("no .claude-plugin/plugin.json - not a plugin")
    skills = sorted(d for d in os.listdir(os.path.join(plugin, "skills"))
                    if os.path.isfile(os.path.join(plugin, "skills", d, "SKILL.md"))) if has("skills") else []
    if not skills:
        problems.append("no skills/<name>/SKILL.md - chat and Cowork would get nothing")
    if has("bin"):
        problems.append("a top-level bin/ folder: the organisation's plugin library refuses the plugin (Cowork, chat); "
                        "move the scripts into skills/<name>/scripts/")
    hooks, agents = has("hooks/hooks.json"), has("agents")
    local_mcp = False
    if has(".mcp.json"):
        try:
            servers = load_json(os.path.join(plugin, ".mcp.json"), ".mcp.json").get("mcpServers", {})
            local_mcp = any(isinstance(v, dict) and (v.get("command") or v.get("type") == "stdio") for v in servers.values())
        except Problem as err:
            problems.append(str(err))
    parts = ["skills"] + (["hooks"] if hooks else []) + (["agents"] if agents else [])
    code = "Claude Code %s (%s)" % ("ok" if skills else "NO", ", ".join(parts + (["MCP"] if has(".mcp.json") else [])))
    cowork = "Cowork %s (%s)" % ("NO" if (has("bin") or not skills) else "ok", ", ".join(parts))
    chat_skip = [x for x, on in (("hooks", hooks), ("agents", agents), ("local MCP", local_mcp)) if on]
    chat = "chat %s (skills only%s)" % ("NO" if (has("bin") or not skills) else "ok",
                                         "; skipped there: " + ", ".join(chat_skip) if chat_skip else "")
    return [code, cowork, chat], problems


# ---------------------------------------------------------------- building ---------------------------

def skill_text(task, p, words):
    lines = ["---", "name: %s" % task["id"],
             "description: %s. %s %s." % (task["title"].rstrip("."), say(words, "skill_use_when"), task["when"].rstrip(".")),
             "---", "",
             "# %s" % task["title"], "", "## %s" % say(words, "skill_when"), "", task["when"], "",
             "## %s" % say(words, "skill_steps"), ""]
    lines += ["%d. %s" % (i, step) for i, step in enumerate(task["steps"], 1)]
    if task.get("inputs"):
        lines += ["", "## %s" % say(words, "skill_inputs"), ""] + ["- %s" % x for x in task["inputs"]]
    if task.get("output"):
        lines += ["", "## %s" % say(words, "skill_output"), "", task["output"]]
    checks = task.get("checks") or []
    if checks:
        lines += ["", "## %s" % say(words, "skill_checks"), ""] + ["- [ ] %s" % c for c in checks]
    rules = []
    if p["red_paths"]:
        rules.append(say(words, "skill_rule_red", paths=", ".join(p["red_paths"])))
    rules.append(say(words, "skill_rule_language"))
    lines += ["", "## %s" % say(words, "skill_rules"), ""] + ["- %s" % r for r in rules]
    if task.get("examples"):
        lines += ["", say(words, "skill_examples")]
    return "\n".join(lines) + "\n"


SKILL_TESTS = '''"""Tests of the company's own skills, written by firmcall. Run: python3 -m pytest -q tests"""
import json
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS = os.path.join(ROOT, "skills")


def front(text):
    m = re.match(r"^---\\n(.*?)\\n---\\n", text, re.S)
    out = {}
    for line in (m.group(1) if m else "").splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            out[key.strip()] = value.strip()
    return out


class Skills(unittest.TestCase):
    def test_every_skill_names_itself_and_says_when(self):
        names = sorted(os.listdir(SKILLS))
        self.assertTrue(names)
        for name in names:
            text = open(os.path.join(SKILLS, name, "SKILL.md"), encoding="utf-8").read()
            meta = front(text)
            self.assertEqual(meta.get("name"), name)
            self.assertIn(%(use)s, meta.get("description", ""))
            self.assertLess(len(meta.get("description", "")), 1024)

    def test_every_check_is_in_the_skill(self):
        for name in os.listdir(SKILLS):
            text = open(os.path.join(SKILLS, name, "SKILL.md"), encoding="utf-8").read()
            path = os.path.join(SKILLS, name, "examples.json")
            data = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {"checks": [], "examples": []}
            for check in data.get("checks", []):
                self.assertIn(check, text)
            for ex in data.get("examples", []):
                self.assertTrue(ex.get("input"))
                self.assertTrue(ex.get("must_include"), "an example needs the words a good answer must hold")

    def test_red_folders_stay_named_in_every_skill(self):
        red = %(red)s
        for name in os.listdir(SKILLS):
            text = open(os.path.join(SKILLS, name, "SKILL.md"), encoding="utf-8").read()
            for path in red:
                self.assertIn(path, text)

    def test_no_bin_folder(self):
        self.assertFalse(os.path.exists(os.path.join(ROOT, "bin")), "the organisation's plugin library refuses bin/")


if __name__ == "__main__":
    unittest.main()
'''


def plugin_files(p, words):
    """-> {relative path inside the plugin: text}"""
    name = "%s-ai" % p["slug"]
    files = {}
    manifest = {"name": name, "version": p["version"],
                "description": say(words, "plugin_description", company=p["company"],
                                   tasks=", ".join(t["title"] for t in p["tasks"])),
                "author": {"name": p["company"]}}
    files[".claude-plugin/plugin.json"] = dump(manifest)
    for task in p["tasks"]:
        files["skills/%s/SKILL.md" % task["id"]] = skill_text(task, p, words)
        files["skills/%s/examples.json" % task["id"]] = dump({"checks": task.get("checks") or [],
                                                              "examples": task.get("examples") or []})
    files["tests/test_skills.py"] = SKILL_TESTS % {"red": json.dumps(p["red_paths"], ensure_ascii=False),
                                                   "use": json.dumps(say(words, "skill_use_when"), ensure_ascii=False)}
    readme = ["# %s" % name, "", say(words, "plugin_readme", company=p["company"]), ""]
    readme += ["- **%s** (`/%s:%s`): %s" % (t["title"], name, t["id"], t["when"]) for t in p["tasks"]]
    readme += ["", "```", "python3 -m pytest -q tests", "```", ""]
    files["README.md"] = "\n".join(readme)
    return files


def catalogue_for(p, words):
    name = "%s-ai" % p["slug"]
    return {"name": name, "owner": {"name": p["company"]},
            "metadata": {"description": say(words, "catalogue_description", company=p["company"]),
                         "version": p["version"]},
            "plugins": [{"name": name, "source": "./%s" % name, "version": p["version"],
                         "description": say(words, "plugin_description", company=p["company"],
                                            tasks=", ".join(t["title"] for t in p["tasks"])),
                         "category": "productivity"}]}


def plugin_zip(files, top):
    """One top folder <plugin>/, files sorted and dated 1980-01-01, so the same profile gives the same bytes."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in sorted(files):
            info = zipfile.ZipInfo("%s/%s" % (top, rel), (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, files[rel].encode("utf-8"))
    return buf.getvalue()


def mobileconfig(p, settings):
    """A macOS configuration profile: the settings in the managed preferences domain com.anthropic.claudecode,
    as Forced mcx_preference_settings (the shape of Anthropic's own template in anthropics/claude-code
    examples/mdm, read 2026-10-02). UUIDs are derived from the slug, so a rebuild replaces the same profile."""
    ns = uuid.uuid5(uuid.NAMESPACE_DNS, "%s.firmcall.claude-code" % p["slug"])
    inner = str(uuid.uuid5(ns, "payload")).upper()
    outer = str(uuid.uuid5(ns, "profile")).upper()
    ident = "com.%s.claudecode" % re.sub(r"[^a-z0-9]", "", p["slug"]) or "company"
    payload = {
        "PayloadDisplayName": "Claude Code", "PayloadIdentifier": "%s.%s" % (ident, inner),
        "PayloadType": "com.apple.ManagedClient.preferences", "PayloadUUID": inner, "PayloadVersion": 1,
        "PayloadContent": {MDM_DOMAIN: {"Forced": [{"mcx_preference_settings": settings}]}},
    }
    profile = {
        "PayloadDisplayName": "%s - Claude Code" % p["company"],
        "PayloadDescription": "Claude Code managed settings for %s, written by firmcall." % p["company"],
        "PayloadIdentifier": ident, "PayloadOrganization": p["company"], "PayloadScope": "System",
        "PayloadType": "Configuration", "PayloadUUID": outer, "PayloadVersion": 1, "PayloadContent": [payload],
    }
    return plistlib.dumps(profile, fmt=plistlib.FMT_XML, sort_keys=True)


def sh_file_block(path_var, name, text):
    marker = "FIRMCALL_EOF"
    if marker in text:
        raise Problem("a file holds the text %s" % marker)
    return "cat > \"$%s/%s\" <<'%s'\n%s%s\nchmod 644 \"$%s/%s\"\n" % (path_var, name, marker, text, marker, path_var, name)


def jamf_script(p, policy, mcp):
    lines = ["#!/bin/sh", "# Jamf policy script for %s, written by firmcall." % p["company"],
             "# The configuration profile carries the rules; this script puts the two files a profile cannot",
             "# carry into Claude Code's system folder: the company policy and, when fixed, managed-mcp.json.",
             "set -eu", "DIR=\"/Library/Application Support/ClaudeCode\"", "mkdir -p \"$DIR\"",
             sh_file_block("DIR", POLICY_NAME, dump(policy))]
    if mcp is not None:
        lines.append(sh_file_block("DIR", "managed-mcp.json", dump(mcp)))
    lines.append("echo \"firmcall: files written to $DIR\"")
    return "\n".join(lines) + "\n"


def ps_here(text):
    if "'@" in text:
        raise Problem("a file holds the text '@")
    return "@'\n%s'@" % text


def intune_script(p, settings, policy, mcp):
    out = ["<#", "Claude Code rules for %s, written by firmcall." % p["company"],
           "Intune: Devices > Scripts and remediations > Platform scripts > Add (Windows 10 and later).",
           "  Run this script using the logged on credentials: No",
           "  Run script in 64 bit PowerShell Host: Yes",
           "Writes managed-settings.d\\%s, %s%s into C:\\Program Files\\ClaudeCode\\." % (
               SETTINGS_DROPIN, POLICY_NAME, " and managed-mcp.json" if mcp is not None else ""),
           "#>", "$ErrorActionPreference = 'Stop'", "$dir = Join-Path $env:ProgramFiles 'ClaudeCode'",
           "New-Item -ItemType Directory -Path (Join-Path $dir 'managed-settings.d') -Force | Out-Null",
           "$utf8 = New-Object System.Text.UTF8Encoding($false)",
           "function Put($rel, $text) { [System.IO.File]::WriteAllText((Join-Path $dir $rel), $text, $utf8); "
           "Write-Output \"Wrote $(Join-Path $dir $rel)\" }",
           "Put 'managed-settings.d\\%s' %s" % (SETTINGS_DROPIN, ps_here(dump(settings))),
           "Put '%s' %s" % (POLICY_NAME, ps_here(dump(policy)))]
    if mcp is not None:
        out.append("Put 'managed-mcp.json' %s" % ps_here(dump(mcp)))
    return "\r\n".join("\r\n".join(chunk.split("\n")) for chunk in out) + "\r\n"


INSTALL_SH = """#!/bin/sh
# Puts the company's Claude Code rules into this computer's system folder. Run once, as an administrator:
#   sudo sh install.sh
# macOS: /Library/Application Support/ClaudeCode   Linux and WSL: /etc/claude-code
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
case "$(uname -s)" in
  Darwin) DIR="/Library/Application Support/ClaudeCode" ;;
  *) DIR="/etc/claude-code" ;;
esac
if [ "$(id -u)" != "0" ]; then echo "firmcall: run it as an administrator: sudo sh $0"; exit 1; fi
# gatecall's hook holds the red folders, and it runs on Python 3. A computer with no working Python 3 gets the
# same rules with a plain deny for the red folders instead; run this again once Python 3 is there, and the red
# window (routecall's profile local-red) can open them.
python_ok() {
  for py in /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
    [ -x "$py" ] || continue
    if [ "$py" = /usr/bin/python3 ] && [ "$(uname -s)" = Darwin ] && ! xcode-select -p >/dev/null 2>&1; then
      continue
    fi
    "$py" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' >/dev/null 2>&1 && return 0
  done
  return 1
}
RULES="$HERE/managed-settings.d/%(dropin)s"
if [ -f "$HERE/fallback/%(dropin)s" ] && ! python_ok; then
  RULES="$HERE/fallback/%(dropin)s"
  echo "firmcall: no working Python 3 here - the red folders get a plain deny rule on this computer. Install Python 3 (on a Mac: xcode-select --install) and run this again: then gatecall holds them and the red window opens them."
fi
mkdir -p "$DIR/managed-settings.d"
install -m 644 "$RULES" "$DIR/managed-settings.d/%(dropin)s"
install -m 644 "$HERE/%(policy)s" "$DIR/%(policy)s"
[ -f "$HERE/managed-mcp.json" ] && install -m 644 "$HERE/managed-mcp.json" "$DIR/managed-mcp.json"
echo "firmcall: the rules are in $DIR - start Claude Code and run /status: 'Setting sources' names them."
"""

INSTALL_PS1 = """# Puts the company's Claude Code rules into C:\\Program Files\\ClaudeCode. Run once in an administrator PowerShell:
#   powershell -ExecutionPolicy Bypass -File install.ps1
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$dir = Join-Path $env:ProgramFiles 'ClaudeCode'
New-Item -ItemType Directory -Path (Join-Path $dir 'managed-settings.d') -Force | Out-Null
# gatecall's hook holds the red folders and runs on Python 3; with no working Python 3 this computer gets the same
# rules with a plain deny for the red folders (run this again once Python 3 is installed).
$rules = Join-Path $here 'managed-settings.d\\%(dropin)s'
$fallback = Join-Path $here 'fallback\\%(dropin)s'
$py = Get-Command python3, python, py -ErrorAction SilentlyContinue | Where-Object { $_.Source -notlike '*WindowsApps*' } | Select-Object -First 1
if ((Test-Path $fallback) -and -not $py) {
  $rules = $fallback
  Write-Output "firmcall: no working Python 3 here - the red folders get a plain deny rule on this computer. Install Python 3 and run this again: then gatecall holds them and the red window opens them."
}
Copy-Item $rules (Join-Path $dir 'managed-settings.d\\%(dropin)s') -Force
Copy-Item (Join-Path $here '%(policy)s') (Join-Path $dir '%(policy)s') -Force
if (Test-Path (Join-Path $here 'managed-mcp.json')) { Copy-Item (Join-Path $here 'managed-mcp.json') (Join-Path $dir 'managed-mcp.json') -Force }
Write-Output "firmcall: the rules are in $dir - start Claude Code and run /status."
"""


def rls_sql(p):
    """Read-only role with row-level security per person, for a database the company's agent reads."""
    out = ["-- Read-only access for the company's AI agent, written by firmcall for %s." % p["company"],
           "-- Each person sees only their own rows; the agent's role can read, never write.", ""]
    for db in p["databases"]:
        role = db.get("role") or "%s_ai_readonly" % p["slug"].replace("-", "_")
        schema = db.get("schema") or "public"
        engine = db.get("engine") or "postgres"
        if not re.match(r"^[a-z_][a-z0-9_]*$", role) or not re.match(r"^[a-z_][a-z0-9_]*$", schema):
            raise Problem("databases: role and schema must be plain lower-case SQL names")
        who = ("(current_setting('request.jwt.claims', true)::json ->> 'email')" if engine == "supabase"
               else "current_user")
        out += ["-- %s, schema %s" % (engine, schema),
                "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '%s') THEN CREATE ROLE %s NOLOGIN; "
                "END IF; END $$;" % (role, role),
                "GRANT USAGE ON SCHEMA %s TO %s;" % (schema, role),
                "-- then give the role to the login the agent's connector uses: GRANT %s TO <that login>;" % role]
        for t in db.get("tables") or []:
            table, col = t.get("name"), t.get("owner_column")
            if not all(re.match(r"^[a-z_][a-z0-9_]*$", str(x or "")) for x in (table, col)):
                raise Problem("databases: table and owner_column must be plain lower-case SQL names")
            out += ["GRANT SELECT ON %s.%s TO %s;" % (schema, table, role),
                    "ALTER TABLE %s.%s ENABLE ROW LEVEL SECURITY;" % (schema, table),
                    "DROP POLICY IF EXISTS %s_own_rows ON %s.%s;" % (role, schema, table),
                    "CREATE POLICY %s_own_rows ON %s.%s FOR SELECT TO %s USING (%s = %s);"
                    % (role, schema, table, role, col, who)]
        out.append("")
    return "\n".join(out)


def rollout(p, words, has_mcp, have):
    name = "%s-ai" % p["slug"]
    steps = [
        say(words, "rollout_catalogue", folder="%s-plugins" % p["slug"]),
        say(words, "rollout_tests", folder="%s-plugins/%s" % (p["slug"], name)),
        say(words, "rollout_device"),
    ]
    if "jamf" in have:
        steps.append(say(words, "rollout_jamf", slug=p["slug"]))
    if "intune" in have:
        steps.append(say(words, "rollout_intune", script="Set-%sClaudePolicy.ps1" % p["slug"].title().replace("-", "")))
    steps += [say(words, "rollout_console"), say(words, "rollout_cowork", zip="%s-%s.zip" % (name, p["version"])),
              say(words, "rollout_remote"), say(words, "rollout_check")]
    if has_mcp:
        steps.append(say(words, "rollout_mcp"))
    if p["databases"]:
        steps.append(say(words, "rollout_rls"))
    lines = ["# %s" % say(words, "rollout_title", company=p["company"]), "", say(words, "rollout_intro"), ""]
    lines += ["%d. %s" % (i, s) for i, s in enumerate(steps, 1)]
    return "\n".join(lines) + "\n"


def build(profile_path, out, mdm=None, force=False):
    p = check_profile(load_json(profile_path, "the company profile"))
    words = lang_words(p["language"])
    settings = settings_for(p)
    problems = [x for x in lint_settings(settings, managed=True, trusted_devices=p["trusted_devices"],
                                         where="the rules file") if x[0] == "error"]
    if problems:
        raise Problem("; ".join(t for _l, _c, t in problems))
    if os.path.exists(out) and os.listdir(out) and not force:
        raise Problem("%s is not empty; pass --force to write over it" % out)
    name = "%s-ai" % p["slug"]
    written = []
    files = plugin_files(p, words)
    for rel, text in files.items():
        written.append(write(os.path.join(out, "%s-plugins" % p["slug"], name, rel), text))
    written.append(write(os.path.join(out, "%s-plugins" % p["slug"], ".claude-plugin", "marketplace.json"),
                         dump(catalogue_for(p, words))))
    zpath = os.path.join(out, "%s-%s.zip" % (name, p["version"]))
    with open(zpath, "wb") as fh:
        fh.write(plugin_zip(files, name))
    written.append(zpath)
    m = os.path.join(out, "managed")
    policy = policy_for(p)
    mcp = mcp_file_for(p)
    written.append(write(os.path.join(m, "managed-settings.d", SETTINGS_DROPIN), dump(settings)))
    written.append(write(os.path.join(m, "server-managed-settings.json"), dump(settings_for(p, console=True))))
    if p["red_paths"]:
        # The same rules plus the red folders' deny, for a computer where gatecall's hook cannot run: install.sh and
        # install.ps1 put this one in place when they find no working Python 3.
        written.append(write(os.path.join(m, "fallback", SETTINGS_DROPIN), dump(settings_for(p, console=True))))
    written.append(write(os.path.join(m, POLICY_NAME), dump(policy)))
    if mcp is not None:
        written.append(write(os.path.join(m, "managed-mcp.json"), dump(mcp)))
    written.append(write(os.path.join(m, "install.sh"),
                         INSTALL_SH % {"dropin": SETTINGS_DROPIN, "policy": POLICY_NAME}, 0o755))
    written.append(write(os.path.join(m, "install.ps1"), INSTALL_PS1 % {"dropin": SETTINGS_DROPIN, "policy": POLICY_NAME}))
    have = set()
    kinds = mdm if mdm else p.get("mdm")
    if isinstance(kinds, str):
        kinds = [kinds]
    for kind in kinds or []:
        if kind not in ("jamf", "intune", "none"):
            raise Problem("mdm %r: firmcall exports for jamf and intune" % kind)
        if kind in ("jamf", "intune"):
            written += export(p, settings, policy, mcp, m, kind)
            have.add(kind)
    if p["databases"]:
        written.append(write(os.path.join(m, "rls.sql"), rls_sql(p)))
    written.append(write(os.path.join(out, "ROLLOUT.md"), rollout(p, words, mcp is not None, have)))
    return p, written


def export(p, settings, policy, mcp, m, kind):
    if kind == "jamf":
        path = os.path.join(m, "jamf", "%s.mobileconfig" % p["slug"])
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(mobileconfig(p, settings))
        return [path, write(os.path.join(m, "jamf", "claude-files.sh"), jamf_script(p, policy, mcp), 0o755)]
    if kind == "intune":
        script = "Set-%sClaudePolicy.ps1" % p["slug"].title().replace("-", "")
        return [write(os.path.join(m, "intune", script), intune_script(p, settings, policy, mcp))]
    raise Problem("export: --jamf or --intune")


def export_check(folder):
    """The rules travel whole: every deny rule of the device file is in the Jamf profile and in the Intune script."""
    m = os.path.join(folder, "managed")
    rules = load_json(os.path.join(m, "managed-settings.d", SETTINGS_DROPIN), "the rules file")
    deny = (rules.get("permissions") or {}).get("deny") or []
    problems = []
    jamf = os.path.join(m, "jamf")
    if os.path.isdir(jamf):
        for f in os.listdir(jamf):
            if f.endswith(".mobileconfig"):
                with open(os.path.join(jamf, f), "rb") as fh:
                    prof = plistlib.load(fh)
                try:
                    inner = prof["PayloadContent"][0]["PayloadContent"][MDM_DOMAIN]["Forced"][0]["mcx_preference_settings"]
                except (KeyError, IndexError, TypeError):
                    inner = {}
                if inner != rules:
                    problems.append("%s does not carry the rules file whole" % f)
                if not os.path.exists(os.path.join(jamf, "claude-files.sh")):
                    problems.append("jamf/claude-files.sh is missing: the policy file would not reach the Macs")
    intune = os.path.join(m, "intune")
    if os.path.isdir(intune):
        whole = dump(rules)
        for f in os.listdir(intune):
            text = open(os.path.join(intune, f), encoding="utf-8").read().replace("\r\n", "\n")
            if SETTINGS_DROPIN not in text or whole not in text or any(rule not in text for rule in deny):
                problems.append("%s does not write the rules file whole" % f)
    return problems


# ---------------------------------------------------------------- commands ---------------------------

def parser():
    ap = argparse.ArgumentParser(prog="firmcall.py", description="The company's own plugin and the rules on every computer.")
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("init", help="write a starting company profile")
    s.add_argument("--out", default="firm-profile.json")
    s.add_argument("--template", help="a sector template (see: templates)")
    s.add_argument("--company", default="Our company")
    s.add_argument("--language", default="en", choices=LANGS)
    sub.add_parser("templates", help="the sector templates and the open plugins each one builds on")
    s = sub.add_parser("build", help="build company-AI/ from the profile")
    s.add_argument("profile")
    s.add_argument("--out", default="company-AI")
    s.add_argument("--jamf", action="store_true")
    s.add_argument("--intune", action="store_true")
    s.add_argument("--force", action="store_true")
    s = sub.add_parser("export", help="the Jamf profile or the Intune script for a profile")
    s.add_argument("profile")
    s.add_argument("--out", default="company-AI")
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--jamf", action="store_true")
    g.add_argument("--intune", action="store_true")
    s = sub.add_parser("lint", help="check a settings file or folder")
    s.add_argument("path")
    s.add_argument("--managed", action="store_true", default=None)
    s.add_argument("--not-managed", dest="managed", action="store_false")
    s.add_argument("--trusted-devices", action="store_true")
    s.add_argument("--server", help="the settings pasted into the claude.ai console, to compare")
    s = sub.add_parser("surface", help="where a plugin works: Claude Code, Cowork, chat")
    s.add_argument("plugin")
    s = sub.add_parser("check", help="check a built company-AI/ folder: rules, exports, surfaces")
    s.add_argument("folder")
    s = sub.add_parser("policy", help="write only company-ai-policy.json from the profile")
    s.add_argument("profile")
    s.add_argument("--out", default=POLICY_NAME)
    s = sub.add_parser("rls", help="print the read-only row-level security SQL for the profile's databases")
    s.add_argument("profile")
    return ap


def run(argv):
    args = parser().parse_args(argv)
    if args.cmd == "templates":
        for name, t in templates().items():
            ups = "; ".join("%s (%s, %s)" % (u["repo"], ", ".join(u.get("plugins", [])), u.get("license", "?"))
                            for u in t.get("upstream", []))
            print("%-18s %s%s" % (name, t.get("title", ""), (" - builds on " + ups) if ups else ""))
        return 0
    if args.cmd == "init":
        if os.path.exists(args.out):
            raise Problem("%s already exists - edit it, or choose another --out" % args.out)
        if args.template:
            if args.template not in templates():
                raise Problem("no template %r; there are: %s" % (args.template, ", ".join(templates())))
            # The template's own tasks and open plugins over a neutral start - nothing of the example agency.
            base = json.loads(json.dumps(NEUTRAL_PROFILE))
            base.update(company=args.company, language=args.language, template=args.template)
        else:
            base = load_json(os.path.join(DATA, "examples", "agency-10.json"), "the example profile")
            base.update(company=args.company, language=args.language, slug=None)
            base.pop("slug")
        write(os.path.abspath(args.out), dump(base))
        print("firmcall: %s written - fill in the tasks, the red folders and the budget, then: build %s"
              % (args.out, args.out))
        return 0
    if args.cmd == "build":
        kinds = [k for k, on in (("jamf", args.jamf), ("intune", args.intune)) if on] or None
        p, written = build(args.profile, args.out, kinds, args.force)
        words = lang_words(p["language"])
        print(say(words, "built", n=len(written), out=args.out))
        lines, problems = surface_lint(os.path.join(args.out, "%s-plugins" % p["slug"], "%s-ai" % p["slug"]))
        for line in lines:
            print("  " + line)
        found = export_check(args.out) + problems
        for line in found:
            print("BAD: " + line)
        print(say(words, "next", out=args.out))
        return 1 if found else 0
    if args.cmd == "export":
        p = check_profile(load_json(args.profile, "the company profile"))
        settings, policy, mcp = settings_for(p), policy_for(p), mcp_file_for(p)
        for path in export(p, settings, policy, mcp, os.path.join(args.out, "managed"), "jamf" if args.jamf else "intune"):
            print(path)
        return 0
    if args.cmd == "lint":
        found = lint_path(args.path, args.managed, args.trusted_devices, args.server)
        for level, code, text in found:
            print("%s %s: %s" % ("BAD:" if level == "error" else "note:", code, text))
        errors = sum(1 for x in found if x[0] == "error")
        print("lint: %d problem(s), %d note(s)" % (errors, len(found) - errors))
        return 1 if errors else 0
    if args.cmd == "surface":
        lines, problems = surface_lint(args.plugin)
        for line in lines:
            print(line)
        for line in problems:
            print("BAD: " + line)
        return 1 if problems else 0
    if args.cmd == "check":
        m = os.path.join(args.folder, "managed")
        policy = os.path.join(m, POLICY_NAME)
        trusted = os.path.exists(policy) and bool(load_json(policy, "the policy").get("trusted_devices"))
        found = [t for lvl, _c, t in lint_path(os.path.join(m, "managed-settings.d", SETTINGS_DROPIN), True, trusted,
                                               os.path.join(m, "server-managed-settings.json")) if lvl == "error"]
        found += export_check(args.folder)
        for folder in sorted(os.listdir(args.folder)):
            full = os.path.join(args.folder, folder)
            if folder.endswith("-plugins") and os.path.isdir(full):
                for plug in sorted(os.listdir(full)):
                    if os.path.isfile(os.path.join(full, plug, ".claude-plugin", "plugin.json")):
                        lines, problems = surface_lint(os.path.join(full, plug))
                        for line in lines:
                            print("  %s: %s" % (plug, line))
                        found += problems
        for line in found:
            print("BAD: " + line)
        print("check: %d problem(s)" % len(found))
        return 1 if found else 0
    if args.cmd == "policy":
        p = check_profile(load_json(args.profile, "the company profile"))
        write(os.path.abspath(args.out), dump(policy_for(p)))
        print(args.out)
        return 0
    if args.cmd == "rls":
        p = check_profile(load_json(args.profile, "the company profile"))
        if not p["databases"]:
            raise Problem("the profile names no database (\"databases\")")
        sys.stdout.write(rls_sql(p))
        return 0
    parser().print_help()
    return 0


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    try:
        return run(sys.argv[1:] if argv is None else argv)
    except Problem as err:
        print("firmcall: %s" % err)
        return 2


if __name__ == "__main__":
    sys.exit(main())
