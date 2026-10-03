#!/usr/bin/env python3
"""A live check with a real Claude Code: the rules file holds when a window talks to another model.

The case it proves (plan of the track for companies, stage 4): a person opens a window on a cheap model -
GLM, a local Ollama - by pointing ANTHROPIC_BASE_URL away from api.anthropic.com. Such a session never
fetches the claude.ai console settings, so the only rules left are the ones in a file on the computer. Here a
stand-in endpoint on 127.0.0.1 plays that model: it asks Claude Code to Read clients/secret.txt. With the deny
rules firmcall writes for the red folder `clients`, the read must be refused and the secret must never reach the
model. With --no-deny (the mutation) the same session reads it, and this script says so and exits 1.

    python3 tests/live_window.py [--no-deny] [--claude PATH]

The rules are passed with --settings, the way routecall gives every cloud window its own: the red folders' deny
rules a cloud session carries (firmcall writes the same ones into the claude.ai console file; the laptop's own file
leaves them to gatecall's hook, so that the red window - routecall's profile local-red - can open those folders).
Only the permissions block is passed, so the session does not try to register the company's catalogues over the
network.
Prints what happened; exit 0 = the rules held (or, with --no-deny, the leak was seen), 1 = not, 3 = no claude.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "skills", "firmcall", "scripts"))
import firmcall  # noqa: E402

SECRET = "SECRET-CLIENT-4242"
REQUESTS = []


def tool_results(body):
    out = []
    for m in body.get("messages", []):
        if isinstance(m.get("content"), list):
            out += [c for c in m["content"] if c.get("type") == "tool_result"]
    return out


class Handler(BaseHTTPRequestHandler):
    target = None

    def log_message(self, *a):
        pass

    def send_json(self, obj):
        data = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.send_json({"data": [], "has_more": False})

    def do_POST(self):
        n = int(self.headers.get("content-length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            body = {}
        if "/messages" not in self.path or "count_tokens" in self.path:
            return self.send_json({"input_tokens": 10})
        REQUESTS.append(body)
        names = {t.get("name") for t in body.get("tools", []) or []}
        done = {c.get("tool_use_id") for c in tool_results(body)}
        if "Read" in names and "toolu_read_1" not in done:
            blocks, stop = [{"type": "tool_use", "id": "toolu_read_1", "name": "Read",
                             "input": {"file_path": self.target}}], "tool_use"
        else:
            blocks, stop = [{"type": "text", "text": "Done."}], "end_turn"
        msg = {"id": "msg_%d" % len(REQUESTS), "type": "message", "role": "assistant",
               "model": body.get("model", "glm"), "content": [], "stop_reason": None, "stop_sequence": None,
               "usage": {"input_tokens": 10, "output_tokens": 0}}
        if not body.get("stream"):
            msg.update(content=blocks, stop_reason=stop)
            return self.send_json(msg)
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.end_headers()

        def ev(name, data):
            self.wfile.write(("event: %s\ndata: %s\n\n" % (name, json.dumps(data))).encode())

        ev("message_start", {"type": "message_start", "message": msg})
        for i, b in enumerate(blocks):
            if b["type"] == "text":
                ev("content_block_start", {"type": "content_block_start", "index": i,
                                           "content_block": {"type": "text", "text": ""}})
                ev("content_block_delta", {"type": "content_block_delta", "index": i,
                                           "delta": {"type": "text_delta", "text": b["text"]}})
            else:
                ev("content_block_start", {"type": "content_block_start", "index": i,
                                           "content_block": {"type": "tool_use", "id": b["id"], "name": b["name"],
                                                             "input": {}}})
                ev("content_block_delta", {"type": "content_block_delta", "index": i,
                                           "delta": {"type": "input_json_delta",
                                                     "partial_json": json.dumps(b["input"])}})
            ev("content_block_stop", {"type": "content_block_stop", "index": i})
        ev("message_delta", {"type": "message_delta", "delta": {"stop_reason": stop, "stop_sequence": None},
                             "usage": {"output_tokens": 5}})
        ev("message_stop", {"type": "message_stop"})
        self.wfile.flush()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-deny", action="store_true", help="the mutation: no deny rule for the red folder")
    ap.add_argument("--claude", default=shutil.which("claude"))
    args = ap.parse_args()
    if not args.claude:
        print("live_window: no claude on this computer")
        return 3
    tmp = tempfile.mkdtemp(prefix="firmcall-live-")
    home = os.path.join(tmp, "home")
    project = os.path.join(home, "project")
    os.makedirs(os.path.join(project, "clients"))
    target = os.path.join(project, "clients", "secret.txt")
    with open(target, "w") as fh:
        fh.write("contract of a client: %s\n" % SECRET)
    profile = firmcall.check_profile({"company": "Live check", "tasks": [
        {"id": "t", "title": "T", "when": "w", "steps": ["s"]}], "red_paths": [] if args.no_deny else ["clients"]})
    rules = {"permissions": firmcall.settings_for(profile, console=True).get("permissions", {})}
    rules_path = os.path.join(tmp, "rules.json")
    with open(rules_path, "w") as fh:
        json.dump(rules, fh)

    Handler.target = target
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    env = dict(os.environ)
    env.update({"ANTHROPIC_BASE_URL": "http://127.0.0.1:%d" % server.server_port,
                "ANTHROPIC_API_KEY": "sk-stand-in-for-a-cheap-model", "CLAUDE_CONFIG_DIR": os.path.join(tmp, "config"),
                "HOME": home, "USERPROFILE": home, "DISABLE_TELEMETRY": "1", "DISABLE_ERROR_REPORTING": "1",
                "DISABLE_AUTOUPDATER": "1", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"})
    env.pop("CLAUDECODE", None)
    p = subprocess.run([args.claude, "-p", "Summarise the client file.", "--output-format", "json",
                        "--settings", rules_path, "--allowedTools", "Read"],
                       cwd=project, env=env, capture_output=True, timeout=300, stdin=subprocess.DEVNULL)
    server.shutdown()
    leaked = any(SECRET in json.dumps(r) for r in REQUESTS)
    asked = any("toolu_read_1" in json.dumps(tool_results(r)) for r in REQUESTS)
    print("claude -p exit %d; %d model requests; the Read came back: %s; the secret reached the model: %s; rules: %s"
          % (p.returncode, len(REQUESTS), asked, leaked, json.dumps(rules)))
    shutil.rmtree(tmp, ignore_errors=True)
    if not asked:
        print("live_window: the stand-in never got the Read back - nothing was proven")
        print(p.stdout.decode("utf-8", "replace")[-600:], p.stderr.decode("utf-8", "replace")[-600:])
        return 1
    if args.no_deny:
        print("live_window: without the deny rule the secret %s - the check can fail" % ("leaked" if leaked else "did NOT leak"))
        return 0 if leaked else 1
    print("live_window: the rules file %s" % ("HELD" if not leaked else "DID NOT HOLD"))
    return 0 if not leaked else 1


if __name__ == "__main__":
    sys.exit(main())
