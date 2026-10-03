"""firmcall: the company's own plugin, the rules file, the MDM exports, the lint and the surfaces."""
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import zipfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "firmcall", "scripts"))
import firmcall  # noqa: E402

EXAMPLE = os.path.join(ROOT, "data", "examples", "agency-10.json")


def example(**changes):
    with open(EXAMPLE, encoding="utf-8") as fh:
        p = json.load(fh)
    p.update(changes)
    return p


def build(tmp_path, profile=None, name="out", **kw):
    path = tmp_path / ("%s.json" % name)
    path.write_text(json.dumps(profile or example()), encoding="utf-8")
    out = tmp_path / name
    p, written = firmcall.build(str(path), str(out), **kw)
    return p, out, written


def codes(found, level="error"):
    return sorted({c for lvl, c, _t in found if lvl == level})


class TestBuild:
    def test_the_whole_folder_is_written(self, tmp_path):
        _p, out, written = build(tmp_path)
        rel = {os.path.relpath(w, out).replace(os.sep, "/") for w in written}
        for want in ("example-agency-plugins/.claude-plugin/marketplace.json",
                     "example-agency-plugins/example-agency-ai/.claude-plugin/plugin.json",
                     "example-agency-plugins/example-agency-ai/skills/brief-to-plan/SKILL.md",
                     "example-agency-plugins/example-agency-ai/tests/test_skills.py",
                     "example-agency-ai-0.1.0.zip", "managed/managed-settings.d/50-company.json",
                     "managed/server-managed-settings.json", "managed/company-ai-policy.json",
                     "managed/install.sh", "managed/install.ps1", "managed/jamf/example-agency.mobileconfig",
                     "managed/jamf/claude-files.sh", "managed/intune/Set-ExampleAgencyClaudePolicy.ps1",
                     "managed/rls.sql", "ROLLOUT.md"):
            assert want in rel, want

    def test_the_company_skills_pass_their_own_tests(self, tmp_path):
        _p, out, _w = build(tmp_path)
        plugin = out / "example-agency-plugins" / "example-agency-ai"
        done = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"], cwd=str(plugin),
                              capture_output=True, text=True)
        assert done.returncode == 0, done.stderr

    def test_a_skill_missing_a_check_turns_its_tests_red(self, tmp_path):
        _p, out, _w = build(tmp_path)
        plugin = out / "example-agency-plugins" / "example-agency-ai"
        skill = plugin / "skills" / "brief-to-plan" / "SKILL.md"
        skill.write_text(skill.read_text(encoding="utf-8").replace("names the deadline", "x"), encoding="utf-8")
        done = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"], cwd=str(plugin),
                              capture_output=True, text=True)
        assert done.returncode != 0

    @pytest.mark.skipif(not shutil.which("claude"), reason="no claude CLI here")
    def test_claude_validates_the_catalogue_and_the_plugin(self, tmp_path):
        _p, out, _w = build(tmp_path)
        for folder in ("example-agency-plugins", "example-agency-plugins/example-agency-ai"):
            done = subprocess.run(["claude", "plugin", "validate", str(out / folder)], capture_output=True, text=True,
                                  timeout=120)
            assert done.returncode == 0, done.stdout + done.stderr

    def test_the_zip_has_one_top_folder_and_the_same_bytes_twice(self, tmp_path):
        _p, out, _w = build(tmp_path, name="a")
        _p, out2, _w = build(tmp_path, name="b")
        z1 = (out / "example-agency-ai-0.1.0.zip").read_bytes()
        assert z1 == (out2 / "example-agency-ai-0.1.0.zip").read_bytes()
        names = zipfile.ZipFile(str(out / "example-agency-ai-0.1.0.zip")).namelist()
        assert {n.split("/")[0] for n in names} == {"example-agency-ai"}
        assert "example-agency-ai/.claude-plugin/plugin.json" in names

    def test_rules_file_shape(self, tmp_path):
        _p, out, _w = build(tmp_path)
        rules = json.loads((out / "managed" / "managed-settings.d" / "50-company.json").read_text(encoding="utf-8"))
        console = json.loads((out / "managed" / "server-managed-settings.json").read_text(encoding="utf-8"))
        # the red folders: denied in the console (a session there is never the red window); on the laptop the
        # device file carries no deny for them - it would shut the red window too - and gatecall's hook holds them
        assert "Read(~/Company/HR/**)" in console["permissions"]["deny"]
        assert "Edit(~/Company/HR/**)" in console["permissions"]["deny"]
        assert not any("Company/HR" in rule for rule in rules["permissions"].get("deny", []))
        assert rules["enabledPlugins"]["gatecall@poly-a1"] is True
        # a computer where the hook cannot run (no working Python 3) gets the same rules plus the plain deny
        fallback = json.loads((out / "managed" / "fallback" / "50-company.json").read_text(encoding="utf-8"))
        assert "Read(~/Company/HR/**)" in fallback["permissions"]["deny"]
        assert {k: v for k, v in fallback.items() if k != "permissions"} == \
            {k: v for k, v in rules.items() if k != "permissions"}
        install = (out / "managed" / "install.sh").read_text(encoding="utf-8")
        assert 'RULES="$HERE/fallback/50-company.json"' in install and "python_ok" in install
        assert "fallback" in (out / "managed" / "install.ps1").read_text(encoding="utf-8")
        assert rules["permissions"]["disableBypassPermissionsMode"] == "disable"
        assert rules["enabledPlugins"]["example-agency-ai@example-agency-ai"] is True
        assert rules["enabledPlugins"]["billcall@poly-a1"] is True
        assert {"source": "skills-dir"} in rules["strictKnownMarketplaces"]
        for name, entry in rules["extraKnownMarketplaces"].items():
            assert entry["source"] in rules["strictKnownMarketplaces"], name
        assert rules["managedMcpServers"]["crm"]["url"].startswith("https://")
        assert "env" not in rules

    def test_policy_file_is_the_one_the_company_plugins_read(self, tmp_path):
        _p, out, _w = build(tmp_path)
        policy = json.loads((out / "managed" / "company-ai-policy.json").read_text(encoding="utf-8"))
        gate = os.path.join(ROOT, "..", "gatecall", "data", "company-ai-policy.example.json")
        keys = set(json.load(open(gate, encoding="utf-8"))) if os.path.exists(gate) else {
            "schema", "red_paths", "max_usd_per_day", "allowed_providers", "deny_providers"}
        assert {"schema", "red_paths", "max_usd_per_day", "allowed_providers", "deny_providers"} <= keys
        for key in ("schema", "company", "red_paths", "max_usd_per_day", "max_usd_per_month", "allowed_providers"):
            assert key in policy
        assert policy["red_paths"] == ["~/Company/Clients/Contracts", "~/Company/HR"]
        assert policy["fail_closed"] is True        # with red folders the guard on the laptop is a hook

    def test_red_folders_bring_their_guard_and_leave_the_red_window_open(self):
        t = {"id": "a", "title": "A", "when": "w", "steps": ["s"]}
        p = firmcall.check_profile({"company": "X", "tasks": [t], "red_paths": ["~/Firm/Clients"]})
        assert "gatecall" in p["poly_a1_plugins"]
        device, console = firmcall.settings_for(p), firmcall.settings_for(p, console=True)
        assert "Read(~/Firm/Clients/**)" in console["permissions"]["deny"]
        assert "Read(~/Firm/Clients/**)" not in device["permissions"].get("deny", [])
        assert device["enabledPlugins"]["gatecall@poly-a1"] is True
        # the console's red rules are not "bypassable": gatecall's hook holds them on every route on the laptop
        assert codes(firmcall.lint_settings(device, server=console)) == []
        # the control: a profile with no red folder gets no rule for one and no guard it did not ask for
        bare = firmcall.check_profile({"company": "X", "tasks": [t]})
        assert bare["poly_a1_plugins"] == [] and "deny" not in firmcall.settings_for(bare, console=True)["permissions"]

    def test_a_fixed_mcp_set_writes_managed_mcp_json(self, tmp_path):
        prof = example(mcp={"mode": "fixed", "servers": {"crm": {"type": "http", "url": "https://mcp.x.com/mcp"}}})
        _p, out, _w = build(tmp_path, prof)
        mcp = json.loads((out / "managed" / "managed-mcp.json").read_text(encoding="utf-8"))
        assert mcp == {"mcpServers": {"crm": {"type": "http", "url": "https://mcp.x.com/mcp"}}}
        rules = json.loads((out / "managed" / "managed-settings.d" / "50-company.json").read_text(encoding="utf-8"))
        assert "managedMcpServers" not in rules

    def test_rollout_in_the_company_language(self, tmp_path):
        _p, out, _w = build(tmp_path, example(language="es"))
        text = (out / "ROLLOUT.md").read_text(encoding="utf-8")
        assert "minutos" in text and "managed/install.sh" in text

    def test_rls_reads_own_rows_only_and_refuses_odd_names(self, tmp_path):
        _p, out, _w = build(tmp_path)
        sql = (out / "managed" / "rls.sql").read_text(encoding="utf-8")
        assert "ENABLE ROW LEVEL SECURITY" in sql and "FOR SELECT" in sql and "GRANT SELECT" in sql
        assert "INSERT" not in sql and "UPDATE" not in sql
        bad = example(databases=[{"engine": "postgres", "tables": [{"name": "x; drop table y", "owner_column": "o"}]}])
        with pytest.raises(firmcall.Problem):
            build(tmp_path, bad, name="bad")

    def test_install_script_is_valid_sh(self, tmp_path):
        _p, out, _w = build(tmp_path)
        for script in ("managed/install.sh", "managed/jamf/claude-files.sh"):
            done = subprocess.run(["sh", "-n", str(out / script)], capture_output=True, text=True)
            assert done.returncode == 0, done.stderr

    def test_build_refuses_a_non_empty_folder_without_force(self, tmp_path):
        build(tmp_path)
        with pytest.raises(firmcall.Problem):
            build(tmp_path)
        build(tmp_path, force=True)


class TestProfile:
    def test_a_profile_without_tasks_is_refused(self):
        with pytest.raises(firmcall.Problem):
            firmcall.check_profile({"company": "X", "tasks": []})

    def test_duplicate_task_ids_are_refused(self):
        t = {"id": "a", "title": "A", "when": "w", "steps": ["s"]}
        with pytest.raises(firmcall.Problem):
            firmcall.check_profile({"company": "X", "tasks": [t, t]})

    def test_a_global_model_endpoint_is_refused(self):
        t = {"id": "a", "title": "A", "when": "w", "steps": ["s"]}
        with pytest.raises(firmcall.Problem):
            firmcall.check_profile({"company": "X", "tasks": [t], "env": {"ANTHROPIC_BASE_URL": "http://x"}})
        with pytest.raises(firmcall.Problem):
            firmcall.check_profile({"company": "X", "tasks": [t], "base_url": "http://localhost:11434"})

    def test_a_remote_killing_variable_stops_the_build(self, tmp_path):
        with pytest.raises(firmcall.Problem) as err:
            build(tmp_path, example(env={"DISABLE_GROWTHBOOK": "1"}))
        assert "Remote Control" in str(err.value)

    def test_templates_carry_open_licensed_upstream_with_a_source(self):
        known = firmcall.templates()
        assert {"legal", "finance", "marketing-agency", "customer-support", "small-business"} <= set(known)
        for name, t in known.items():
            assert t["tasks"], name
            for up in t["upstream"]:
                assert up["license"] in ("Apache-2.0", "MIT"), name
                assert up["url"].startswith("https://github.com/") and re.match(r"2026-\d\d-\d\d", up["checked"])

    def test_a_template_fills_the_tasks(self, tmp_path):
        prof = {"company": "Firm", "template": "legal", "tasks": [], "red_paths": ["clients"]}
        p, out, _w = build(tmp_path, prof)
        assert {t["id"] for t in p["tasks"]} == {"contract-review", "deadline-list"}
        rules = json.loads((out / "managed" / "managed-settings.d" / "50-company.json").read_text(encoding="utf-8"))
        assert rules["enabledPlugins"]["commercial-legal@claude-for-legal"] is True

    def test_a_profile_keeps_its_own_open_plugins_and_gets_the_templates(self):
        own = {"marketplace": "my-market", "repo": "me/plugins", "plugins": ["x"], "license": "MIT",
               "url": "https://github.com/me/plugins", "checked": "2026-10-02"}
        t = {"id": "a", "title": "A", "when": "w", "steps": ["s"]}
        p = firmcall.check_profile({"company": "X", "tasks": [t], "template": "legal", "upstream": [own]})
        repos = [u["repo"] for u in p["upstream"]]
        assert repos[0] == "me/plugins"
        assert "anthropics/claude-for-legal" in repos     # the profile's own list no longer hides the template's

    def test_unknown_poly_a1_plugin_is_refused(self):
        t = {"id": "a", "title": "A", "when": "w", "steps": ["s"]}
        with pytest.raises(firmcall.Problem):
            firmcall.check_profile({"company": "X", "tasks": [t], "poly_a1_plugins": ["safecall"]})


class TestDenyPatterns:
    def test_forms(self):
        assert firmcall.deny_patterns("~/Company/HR") == ["Read(~/Company/HR/**)", "Edit(~/Company/HR/**)"]
        assert firmcall.deny_patterns("/srv/clients/") == ["Read(//srv/clients/**)", "Edit(//srv/clients/**)"]
        assert firmcall.deny_patterns("C:\\Firm\\HR") == ["Read(//c/Firm/HR/**)", "Edit(//c/Firm/HR/**)"]
        assert firmcall.deny_patterns("clients") == ["Read(clients/**)", "Edit(clients/**)"]
        assert firmcall.deny_patterns("") == []


class TestExports:
    def test_the_jamf_profile_carries_the_rules_whole(self, tmp_path):
        _p, out, _w = build(tmp_path)
        rules = json.loads((out / "managed" / "managed-settings.d" / "50-company.json").read_text(encoding="utf-8"))
        with open(str(out / "managed" / "jamf" / "example-agency.mobileconfig"), "rb") as fh:
            prof = plistlib.load(fh)
        payload = prof["PayloadContent"][0]
        assert payload["PayloadType"] == "com.apple.ManagedClient.preferences"
        assert payload["PayloadContent"]["com.anthropic.claudecode"]["Forced"][0]["mcx_preference_settings"] == rules
        assert prof["PayloadType"] == "Configuration" and prof["PayloadScope"] == "System"
        assert firmcall.export_check(str(out)) == []

    @pytest.mark.skipif(not shutil.which("plutil"), reason="plutil is macOS only")
    def test_plutil_accepts_the_profile(self, tmp_path):
        _p, out, _w = build(tmp_path)
        done = subprocess.run(["plutil", "-lint", str(out / "managed" / "jamf" / "example-agency.mobileconfig")],
                              capture_output=True, text=True)
        assert done.returncode == 0, done.stdout

    def test_a_profile_without_the_rules_is_red(self, tmp_path):
        _p, out, _w = build(tmp_path)
        path = out / "managed" / "jamf" / "example-agency.mobileconfig"
        with open(str(path), "rb") as fh:
            prof = plistlib.load(fh)
        prof["PayloadContent"][0]["PayloadContent"]["com.anthropic.claudecode"]["Forced"][0]["mcx_preference_settings"] = {}
        with open(str(path), "wb") as fh:
            plistlib.dump(prof, fh)
        assert firmcall.export_check(str(out))

    def test_an_intune_script_without_the_rules_is_red(self, tmp_path):
        _p, out, _w = build(tmp_path)
        script = out / "managed" / "intune" / "Set-ExampleAgencyClaudePolicy.ps1"
        text = script.read_text(encoding="utf-8")
        rule = '"disableBypassPermissionsMode": "disable"'
        assert "managed-settings.d\\50-company.json" in text and rule in text
        assert "company-ai-policy.json" in text
        assert firmcall.export_check(str(out)) == []
        script.write_text(text.replace(rule, '"x": "y"'), encoding="utf-8")
        assert firmcall.export_check(str(out))

    def test_the_jamf_script_puts_the_policy_where_the_plugins_look(self, tmp_path):
        _p, out, _w = build(tmp_path)
        text = (out / "managed" / "jamf" / "claude-files.sh").read_text(encoding="utf-8")
        assert '/Library/Application Support/ClaudeCode' in text and "company-ai-policy.json" in text


class TestLint:
    def test_remote_killers_are_red(self):
        for var in ("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "DISABLE_GROWTHBOOK"):
            assert "remote-off" in codes(firmcall.lint_settings({"env": {var: "1"}}))

    def test_telemetry_off_is_red_only_with_trusted_devices(self):
        for var in ("DISABLE_TELEMETRY", "DO_NOT_TRACK"):
            assert codes(firmcall.lint_settings({"env": {var: "1"}})) == []
            assert "trusted-devices-off" in codes(firmcall.lint_settings({"env": {var: "1"}}, trusted_devices=True))

    def test_a_global_base_url_is_red(self):
        assert "global-base-url" in codes(firmcall.lint_settings({"env": {"ANTHROPIC_BASE_URL": "http://x"}}))

    def test_model_pricing_outside_managed_is_red(self):
        doc = {"modelPricing": {"multiplier": 0.8}}
        assert "managed-only-key" in codes(firmcall.lint_settings(doc, managed=False))
        assert codes(firmcall.lint_settings(doc, managed=True)) == []

    def test_other_managed_only_keys_outside_managed_are_noted(self):
        found = firmcall.lint_settings({"strictKnownMarketplaces": [{"source": "skills-dir"}]}, managed=False)
        assert "managed-only-key" in codes(found, "warn")

    def test_one_slash_where_an_absolute_path_was_meant_is_red(self):
        assert "single-slash-path" in codes(firmcall.lint_settings({"permissions": {"deny": ["Read(/Users/ana/x/**)"]}}))
        assert codes(firmcall.lint_settings({"permissions": {"deny": ["Read(//Users/ana/x/**)", "Edit(/src/**)"]}})) == []

    def test_a_rule_only_in_the_console_is_red(self):
        server = {"permissions": {"deny": ["Read(~/HR/**)"]}}
        assert "bypassable-rule" in codes(firmcall.lint_settings({}, server=server))
        assert codes(firmcall.lint_settings({"permissions": {"deny": ["Read(~/HR/**)"]}}, server=server)) == []
        # gatecall's hook on the device holds a file rule; it does not hold a web rule
        guarded = {"enabledPlugins": {"gatecall@poly-a1": True}}
        assert codes(firmcall.lint_settings(guarded, server=server)) == []
        web = {"permissions": {"deny": ["WebFetch(domain:example.com)"]}}
        assert "bypassable-rule" in codes(firmcall.lint_settings(guarded, server=web))

    def test_allowlist_notes(self):
        assert "skills-dir-stops" in codes(firmcall.lint_settings({"strictKnownMarketplaces": [{"source": "github",
                                                                                                "repo": "a/b"}]}), "warn")
        assert "all-marketplaces-locked" in codes(firmcall.lint_settings({"strictKnownMarketplaces": []}), "warn")

    def test_unreadable_file_is_red(self, tmp_path):
        path = tmp_path / "managed-settings.json"
        path.write_text("{not json", encoding="utf-8")
        assert "unreadable" in codes(firmcall.lint_path(str(path)))

    def test_the_built_rules_lint_clean(self, tmp_path):
        _p, out, _w = build(tmp_path)
        assert codes(firmcall.lint_path(str(out / "managed"), trusted_devices=True)) == []


class TestSurfaces:
    def test_skills_only_works_everywhere(self, tmp_path):
        _p, out, _w = build(tmp_path)
        lines, problems = firmcall.surface_lint(str(out / "example-agency-plugins" / "example-agency-ai"))
        assert problems == [] and all(" ok " in line for line in lines)

    def test_bin_folder_is_red(self, tmp_path):
        _p, out, _w = build(tmp_path)
        plugin = out / "example-agency-plugins" / "example-agency-ai"
        (plugin / "bin").mkdir()
        lines, problems = firmcall.surface_lint(str(plugin))
        assert any("bin/" in p for p in problems)
        assert lines[1].startswith("Cowork NO")

    def test_hooks_and_local_mcp_are_named_as_skipped_in_chat(self, tmp_path):
        _p, out, _w = build(tmp_path)
        plugin = out / "example-agency-plugins" / "example-agency-ai"
        (plugin / "hooks").mkdir()
        (plugin / "hooks" / "hooks.json").write_text('{"hooks": {}}', encoding="utf-8")
        (plugin / ".mcp.json").write_text('{"mcpServers": {"x": {"command": "x"}}}', encoding="utf-8")
        lines, _problems = firmcall.surface_lint(str(plugin))
        assert "hooks" in lines[2] and "local MCP" in lines[2]

    def test_this_plugin_itself_has_no_bin_and_works_everywhere(self):
        _lines, problems = firmcall.surface_lint(ROOT)
        assert problems == []


class TestCli:
    def run(self, *args, cwd=None):
        return subprocess.run([sys.executable, os.path.join(ROOT, "skills", "firmcall", "scripts", "firmcall.py")]
                              + list(args), capture_output=True, text=True, cwd=cwd)

    def test_build_then_check_is_green(self, tmp_path):
        out = tmp_path / "company-AI"
        done = self.run("build", EXAMPLE, "--out", str(out))
        assert done.returncode == 0, done.stdout + done.stderr
        done = self.run("check", str(out))
        assert done.returncode == 0 and "check: 0 problem(s)" in done.stdout, done.stdout

    def test_init_then_build_with_a_template(self, tmp_path):
        done = self.run("init", "--template", "small-business", "--company", "Painter Ana", "--language", "pt",
                        "--out", "p.json", cwd=str(tmp_path))
        assert done.returncode == 0, done.stdout
        done = self.run("build", "p.json", "--out", "c", cwd=str(tmp_path))
        assert done.returncode == 0, done.stdout
        assert (tmp_path / "c" / "painter-ana-plugins" / "painter-ana-ai" / "skills" / "quote-from-request" / "SKILL.md").exists()

    def test_init_with_a_template_carries_nothing_of_the_example_agency(self, tmp_path):
        done = self.run("init", "--template", "legal", "--company", "Law Firm", "--out", "p.json", cwd=str(tmp_path))
        assert done.returncode == 0, done.stdout
        prof = json.loads((tmp_path / "p.json").read_text(encoding="utf-8"))
        text = json.dumps(prof)
        for agency in ("example-agency", "crm", "agency_ai_readonly", "Company/HR", "marketing"):
            assert agency not in text, agency
        p = firmcall.check_profile(prof)
        assert [u["repo"] for u in p["upstream"]] == [u["repo"] for u in firmcall.templates()["legal"]["upstream"]]
        done = self.run("build", "p.json", "--out", "c", cwd=str(tmp_path))
        assert done.returncode == 0, done.stdout
        assert not (tmp_path / "c" / "managed" / "rls.sql").exists()
        assert not (tmp_path / "c" / "managed" / "managed-mcp.json").exists()
        rules = json.loads((tmp_path / "c" / "managed" / "managed-settings.d" / "50-company.json").read_text(
            encoding="utf-8"))
        assert rules["enabledPlugins"]["commercial-legal@claude-for-legal"] is True
        assert "marketing@knowledge-work-plugins" not in rules["enabledPlugins"]

    def test_lint_exit_codes(self, tmp_path):
        bad = tmp_path / "managed-settings.json"
        bad.write_text(json.dumps({"env": {"DISABLE_GROWTHBOOK": "1"}}), encoding="utf-8")
        assert self.run("lint", str(bad)).returncode == 1
        good = tmp_path / "settings.json"
        good.write_text(json.dumps({"permissions": {"deny": ["Read(~/HR/**)"]}}), encoding="utf-8")
        assert self.run("lint", str(good)).returncode == 0

    def test_a_problem_is_one_line_and_exit_2(self, tmp_path):
        done = self.run("build", str(tmp_path / "missing.json"))
        assert done.returncode == 2 and done.stdout.startswith("firmcall: ")

    def test_templates_command_lists_them(self):
        done = self.run("templates")
        assert done.returncode == 0 and "legal" in done.stdout and "Apache-2.0" in done.stdout


class TestWords:
    def test_every_language_has_every_word(self):
        en = json.load(open(os.path.join(ROOT, "lang", "en.json"), encoding="utf-8"))
        for code in firmcall.LANGS:
            d = json.load(open(os.path.join(ROOT, "lang", "%s.json" % code), encoding="utf-8"))
            assert {k for k in en if not k.startswith("_")} == {k for k in d if not k.startswith("_")}, code
            for key, text in d.items():
                if isinstance(text, str):
                    assert set(re.findall(r"\{(\w+)\}", text)) == set(re.findall(r"\{(\w+)\}", en[key])), (code, key)


class TestNoNetwork:
    def test_no_network_module_in_the_code(self):
        for folder, _dirs, files in os.walk(os.path.join(ROOT, "skills")):
            for f in files:
                if f.endswith(".py"):
                    text = open(os.path.join(folder, f), encoding="utf-8").read()
                    assert not re.search(r"^\s*(import|from)\s+(urllib|http|socket|requests|httpx|ftplib|smtplib)\b",
                                         text, re.M), f


@pytest.mark.skipif(os.environ.get("FIRMCALL_LIVE") != "1" or not shutil.which("claude"),
                    reason="live check with a real Claude Code: FIRMCALL_LIVE=1")
class TestLive:
    def test_the_rules_hold_in_a_window_on_another_model(self):
        live = os.path.join(ROOT, "tests", "live_window.py")
        done = subprocess.run([sys.executable, live], capture_output=True, text=True, timeout=400)
        assert done.returncode == 0 and "HELD" in done.stdout, done.stdout
        done = subprocess.run([sys.executable, live, "--no-deny"], capture_output=True, text=True, timeout=400)
        assert done.returncode == 0 and "leaked" in done.stdout, done.stdout
