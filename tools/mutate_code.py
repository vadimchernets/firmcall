#!/usr/bin/env python3
"""Break firmcall's own rules on purpose, in a copy, and watch the tests redden.

Each mutation copies the plugin folder to a temporary place, changes one exact text in one file of the copy
(the text must be there exactly once, or the mutation itself is reported as broken), runs the named tests in the
copy, and expects them red. The control mutation changes a comment and expects green. After every run the sha256
of every original file is compared with the one taken at the start: the plugin itself is never touched. The last
line counts the mutations that misbehaved; anything but 0 is a failure.

  python3 tools/mutate_code.py            (under a minute; needs pytest, like the tests themselves)
"""
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = "skills/firmcall/scripts/firmcall.py"
TESTS = "tests/test_firmcall.py"
SKIP = (".git", "__pycache__", ".pytest_cache", "dist")

# (what is broken, file, exact text, replacement, tests to run, expected outcome)
MUTATIONS = (
    ("control: a comment reworded", SCRIPT,
     "# one slash would anchor at the settings file; two mean the filesystem root",
     "# a single slash would anchor at the settings file; two mean the filesystem root",
     TESTS + "::TestDenyPatterns", "green"),
    ("a bin/ folder passes the surface check", SCRIPT,
     '    if has("bin"):\n        problems.append(', '    if False:\n        problems.append(',
     TESTS + "::TestSurfaces", "red"),
    ("DISABLE_GROWTHBOOK is let through (the phone remote stops unseen)", SCRIPT,
     'REMOTE_OFF_ENV = ("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "DISABLE_GROWTHBOOK")',
     'REMOTE_OFF_ENV = ("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC",)',
     TESTS + "::TestLint", "red"),
    ("no deny rule for a red folder: a GLM window reads clients/", SCRIPT,
     '    return ["Read(%s/**)" % base, "Edit(%s/**)" % base]', '    return []',
     TESTS + "::TestDenyPatterns", "red"),
    ("the Jamf profile goes out without the rules file", SCRIPT,
     '"PayloadContent": {MDM_DOMAIN: {"Forced": [{"mcx_preference_settings": settings}]}},',
     '"PayloadContent": {MDM_DOMAIN: {"Forced": [{"mcx_preference_settings": {}}]}},',
     TESTS + "::TestExports", "red"),
    ("the Intune script forgets the rules file", SCRIPT,
     '           "Put \'managed-settings.d\\\\%s\' %s" % (SETTINGS_DROPIN, ps_here(dump(settings))),\n', '',
     TESTS + "::TestExports", "red"),
    ("a global ANTHROPIC_BASE_URL goes into everyone's rules", SCRIPT,
     '    if p.get("base_url") or any(k in (p.get("env") or {}) for k in ROUTE_ENV):',
     '    if False:',
     TESTS + "::TestProfile", "red"),
    ("modelPricing is accepted in a user settings file", SCRIPT,
     '            level = "error" if key == "modelPricing" else "warn"', '            level = "warn"',
     TESTS + "::TestLint", "red"),
    ("a deny rule only in the console is not flagged", SCRIPT,
     r'            if rule in here or (guarded and re.match(r"^(Read|Edit)\(", str(rule))):', "            if True:",
     TESTS + "::TestLint", "red"),
    ("the device file denies the red folders again: the red window can never open them", SCRIPT,
     'deny = red_rules(p) if (console or GATECALL not in p["poly_a1_plugins"]) else []', "deny = red_rules(p)",
     TESTS + "::TestBuild", "red"),
    ("init --template starts from the example agency again", SCRIPT,
     "base = json.loads(json.dumps(NEUTRAL_PROFILE))",
     'base = load_json(os.path.join(DATA, "examples", "agency-10.json"), "the example profile")',
     TESTS + "::TestCli", "red"),
    ("an absolute path written with one slash", SCRIPT,
     '        base = "/" + raw            #', '        base = raw            #',
     TESTS + "::TestDenyPatterns", "red"),
    ("the company's skills lose their checks", SCRIPT,
     '        lines += ["", "## %s" % say(words, "skill_checks"), ""] + ["- [ ] %s" % c for c in checks]',
     '        pass',
     TESTS + "::TestBuild", "red"),
)


def digest(root):
    out = {}
    for folder, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP)
        for name in names:
            path = os.path.join(folder, name)
            with open(path, "rb") as handle:
                out[os.path.relpath(path, root)] = hashlib.sha256(handle.read()).hexdigest()
    return out


def run_one(tmp, n, mutation):
    """-> ("red" | "green" | "error", detail)."""
    _name, rel, old, new, tests, _expect = mutation
    copy = os.path.join(tmp, "m%02d" % n)
    shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns(*SKIP))
    target = os.path.join(copy, rel)
    with open(target, encoding="utf-8") as handle:
        text = handle.read()
    if text.count(old) != 1:
        return "error", "%r is in %s %d times, not once" % (old, rel, text.count(old))
    with open(target, "w", encoding="utf-8") as handle:
        handle.write(text.replace(old, new, 1))
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    try:
        done = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", tests],
                              cwd=copy, env=env, capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return "error", repr(exc)
    last = (done.stdout.strip().splitlines() or [""])[-1]
    if done.returncode == 0:
        return "green", last
    if done.returncode == 1:
        return "red", last
    return "error", "pytest exit %d: %s" % (done.returncode, (done.stdout + done.stderr).strip()[-300:])


def main():
    before = digest(ROOT)
    bad = 0
    tmp = tempfile.mkdtemp(prefix="firmcall-mutate-")
    try:
        for n, mutation in enumerate(MUTATIONS):
            name, expect = mutation[0], mutation[5]
            outcome, detail = run_one(tmp, n, mutation)
            if outcome == expect:
                print("ok   %s: %s as expected (%s)" % (name, expect, detail))
            else:
                print("BAD  %s: expected %s, got %s (%s)" % (name, expect, outcome, detail))
                bad += 1
            after = digest(ROOT)
            if after != before:
                print("BAD  the plugin's own files changed during '%s'" % name)
                bad += 1
                before = after
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("mutations: %d, misbehaving: %d" % (len(MUTATIONS), bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
