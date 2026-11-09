#!/usr/bin/env python3
"""Deterministic correctness tests for compact-output. No dependencies: python3 tests/test_correctness.py"""
import glob
import json
import os
import re
import shlex
import stat
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(ROOT, "scripts", "compact-bash.py")
FILT = os.path.join(ROOT, "scripts", "compact-out.py")
SH = "bash" if sys.platform.startswith("linux") else "zsh"
TMP = tempfile.mkdtemp(prefix="compact-test-")
DATA = os.path.join(TMP, "data")
HOME = os.path.join(TMP, "home")              # isolated: no user config leaks into tests
os.makedirs(os.path.join(HOME, ".claude"))
BASE_ENV = {**os.environ, "HOME": HOME, "COMPACT_DATA_DIR": DATA, "TERM": "xterm"}
for k in ("CLAUDE_COMPACT_OFF", "CLAUDE_PROJECT_DIR", "COMPACT_MAX_LINES", "COMPACT_REDACT"):
    BASE_ENV.pop(k, None)


def hook_raw(cmd, env=None, **tool_input):
    r = subprocess.run([sys.executable, HOOK], capture_output=True, text=True, cwd=TMP, env={**BASE_ENV, **(env or {})},
                       input=json.dumps({"tool_name": "Bash", "cwd": TMP, "tool_input": {"command": cmd, **tool_input}}))
    return r.stdout.strip()


def wrap(cmd, env=None, **ti):
    out = hook_raw(cmd, env, **ti)
    return json.loads(out)["hookSpecificOutput"]["updatedInput"]["command"] if out else cmd


def run(cmd, env=None):
    p = subprocess.run([SH, "-c", cmd], capture_output=True, cwd=TMP, env={**BASE_ENV, **(env or {})})
    return p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace"), p.returncode


def both(cmd, env=None):
    return run(cmd, env), run(wrap(cmd, env), env)


def filt(text, env=None):
    p = subprocess.run([sys.executable, FILT], input=text.encode(), capture_output=True, env={**BASE_ENV, **(env or {})})
    return p.stdout.decode("utf-8", "replace")


results = []


def check(name, ok, note=""):
    results.append((name, bool(ok), note))


# ---------------------------------------------------------------- content survival
cmd = "for i in $(seq 1 150); do echo \"INFO step $i ok\"; done; echo 'ERROR disk full on /dev/sda1'; for i in $(seq 1 30); do echo 'INFO tail'; done"
_, w = both(cmd); check("error among 180 lines survives (under limit)", "ERROR disk full on /dev/sda1" in w[0])
_, w = both("for i in $(seq 1 50); do echo 'retrying connection'; done"); check("dedup keeps count (x50)", "[x50]" in w[0])
_, w = both("printf 'job 1 failed\\njob 1 failed\\njob 1 failed\\njob 2 failed\\njob 2 failed\\njob 2 failed\\n'")
check("near-dupes not merged", "job 1 failed  [x3]" in w[0] and "job 2 failed  [x3]" in w[0])
js = '{"msg":"a    b     c","k":[1,2,3]}'
_, w = both(f"echo '{js}'"); check("single-line JSON unchanged", js in w[0])
open(os.path.join(TMP, "code.txt"), "w").write("def f():\n    x   = 1\n    yy  = 2\n        return x\n")
r, w = both("cat code.txt"); check("code indentation/alignment preserved", r[0] == w[0])
open(os.path.join(TMP, "tbl.txt"), "w").write("".join(f"{'user'+str(i):<12}{i*37:>8}   {'running':<10}  /usr/bin/thing{i}\n" for i in range(40)))
r, w = both("cat tbl.txt"); check("table: all tokens survive", r[0].split() == w[0].split())
_, w = both("printf '\\033[31mRED\\033[0m text\\n'"); check("ANSI stripped, text kept", w[0].strip() == "RED text", repr(w[0]))
_, w = both("printf 'dl 10%%\\rdl 50%%\\rdl 100%%\\n'"); check("progress bar keeps final state", w[0].strip() == "dl 100%", repr(w[0]))
_, w = both("echo 'héllo ✓ 日本語 🚀'"); check("unicode preserved", "héllo ✓ 日本語 🚀" in w[0])
_, w = both("true"); check("empty output ok", w[0] == "" and w[2] == 0)
_, w = both("printf '\\xff\\xfe ok\\n'"); check("invalid utf-8 doesn't crash", "ok" in w[0])
_, w = both("echo \"it's \\\"quoted\\\" $HOME\" | cat"); check("quotes/vars survive", "quoted" in w[0] and HOME in w[0], repr(w[0]))
_, w = both("cat <<'EOF'\nline  1\nline  2\nEOF"); check("heredoc works", "line  1" in w[0] and w[2] == 0)

# ---------------------------------------------------------------- exit codes & streams
for code in (0, 1, 2, 127):
    r, w = both(f"echo hi; exit {code}"); check(f"exit code {code} preserved", r[2] == w[2])
r, w = both("false | true; echo $?"); check("inner pipe status unchanged (no pipefail leak)", r[0].strip() == w[0].strip() == "0")
r, w = both("false"); check("failing cmd stays failing", w[2] == 1)
r, w = both("set -e; false; echo not-reached"); check("set -e inside cmd honoured", "not-reached" not in w[0] and w[2] == 1)
r, w = both("FOO=bar; echo $FOO; (exit 4)"); check("last-statement status preserved", w[2] == 4 and "bar" in w[0])
_, w = both("echo out; echo ERRMSG >&2"); check("stderr captured", "ERRMSG" in w[0] and "out" in w[0])

# ---------------------------------------------------------------- truncation
_, w = both("seq 1 1000"); out = w[0]
check("truncation keeps first line", out.startswith("1\n")); check("truncation keeps last line", out.rstrip().endswith("1000"))
m = re.search(r"full output: (\S+)\]", out)
check("truncation notice points to file", bool(m))
if m:
    saved = m.group(1)
    check("saved file has the omitted middle", "500" in open(saved).read().split() and "500" not in out.split())
    check("saved file is mode 0600", stat.S_IMODE(os.stat(saved).st_mode) == 0o600)
    check("data dir is mode 0700", stat.S_IMODE(os.stat(DATA).st_mode) == 0o700)
# smart truncation: error in the omitted middle stays visible
big = "\n".join("2026 INFO http: GET /x 200 %dms" % (i % 9) if i != 1777 else "2026 ERROR billing: card_declined req=f00ba7" for i in range(3000)) + "\n"
open(os.path.join(TMP, "big.log"), "w").write(big)
_, w = both("cat big.log")
check("SMART: error line in omitted middle stays visible", "card_declined req=f00ba7" in w[0])
check("SMART: output still far smaller than raw", len(w[0]) < len(big) / 10)
check("SMART: notice explains kept lines", "kept 1 of 1 error/warning-like" in w[0], w[0][:200])
# many noisy matches are capped
noisy = "\n".join(f"WARN something odd {i}" for i in range(2000)) + "\n"
open(os.path.join(TMP, "noisy.log"), "w").write(noisy)
_, w = both("cat noisy.log"); check("SMART: kept lines are capped (keep_max)", w[0].count("\n") < 200 + 60)
# regression: 400+ warnings must not crowd out the single error
mixed = "\n".join("WARN slow request %d" % i if i % 7 == 0 else ("ERROR card_declined once" if i == 1777 else "INFO ok %d" % i) for i in range(3000)) + "\n"
open(os.path.join(TMP, "mixed.log"), "w").write(mixed)
_, w = both("cat mixed.log"); check("SMART: errors outrank a flood of warnings", "ERROR card_declined once" in w[0])
# JSON never truncated at moderate size and stays parseable
pj = json.dumps([{"id": i, "name": f"n{i}"} for i in range(400)], indent=2)
open(os.path.join(TMP, "big.json"), "w").write(pj)
_, w = both("cat big.json"); check("JSON passthrough: stays valid", json.loads(w[0]) == json.loads(pj))
# env override of the limit
_, w = both("seq 1 100", {"COMPACT_MAX_LINES": "20"}); check("COMPACT_MAX_LINES honoured", "lines omitted" in w[0])

# ---------------------------------------------------------------- redaction, retention
secret = "AKIAABCDEFGHIJKLMNOP ghp_" + "a" * 36 + "\nAPI_TOKEN=supersecretvalue123\n"
open(os.path.join(TMP, "sec.txt"), "w").write(secret)
_, w = both("cat sec.txt"); check("redaction is OFF by default", "AKIAABCDEFGHIJKLMNOP" in w[0])
_, w = both("cat sec.txt", {"COMPACT_REDACT": "1"})
check("redaction masks keys/tokens when enabled", "AKIAABC" not in w[0] and "ghp_aaaa" not in w[0] and "supersecretvalue123" not in w[0], w[0])
_, w = both("seq 1 400; echo AKIAABCDEFGHIJKLMNOP", {"COMPACT_REDACT": "1", "COMPACT_MAX_LINES": "50"})
m = re.search(r"full output: (\S+)\]", w[0]); check("redaction also applies to saved file", bool(m) and "AKIAABCDEFGHIJKLMNOP" not in open(m.group(1)).read())
old = os.path.join(DATA, "old.txt"); open(old, "w").write("x"); past = time.time() - 10 * 86400; os.utime(old, (past, past))
both("seq 1 500")
check("retention: old saved outputs deleted", not os.path.exists(old))

# ---------------------------------------------------------------- what must NOT be wrapped
unwrapped = [
    "cd /tmp && pwd", "export A=1", "source ~/.zshrc", ". venv/bin/activate", "nvm use 20", "conda activate base",
    "pushd /tmp", "eval \"$(ssh-agent)\"", "alias ll='ls -l'", "foo() { echo hi; }; foo", "set -a", "umask 077",
    "ls && cd /tmp", "FOO=1 source x.sh", "tail -f x.log", "tail -F x.log", "docker run -it ubuntu bash", "ssh host",
    "sudo ls", "vim a", "python3", "node", "duckdb", "npm run dev", "npm start", "yarn dev", "docker logs -f c1",
    "kubectl logs -f pod", "docker compose up", "gh auth login", "npm login", "sleep 100 &", "python3 -m http.server",
    "watch ls", "less file", "kubectl exec -it pod -- sh",
]
for c in unwrapped:
    check(f"not wrapped: {c}", wrap(c) == c or "compact-out.py" not in wrap(c), wrap(c)[:80])
wrapped = ["ls -la", "git diff", "rg foo .", "npm test", "pytest -q", "docker ps", "kubectl get pods", "cat file | head", "echo a; echo b",
           "docker compose up -d", "python3 script.py", "node app.js", "duckdb -c 'select 1'", "git status && git log"]
for c in wrapped:
    check(f"wrapped: {c}", "compact-out.py" in wrap(c))
check("run_in_background not wrapped", wrap("ls -la", run_in_background=True) == "ls -la")
check("never wraps non-Bash tools", subprocess.run([sys.executable, HOOK], input=json.dumps({"tool_name": "Read", "tool_input": {"file_path": "x"}}), capture_output=True, text=True).stdout == "")

# ---------------------------------------------------------------- permissions & safety
out = json.loads(hook_raw("ls -la"))["hookSpecificOutput"]
check("hook sets NO permissionDecision (normal permission flow)", "permissionDecision" not in out and out["hookEventName"] == "PreToolUse")
check("hook is silent on garbage stdin", subprocess.run([sys.executable, HOOK], input="not json", capture_output=True, text=True).returncode == 0)
cfgp = os.path.join(HOME, ".claude", "compact-output.json")
json.dump({"max_lines": "not-a-number"}, open(cfgp, "w"))      # makes process() raise
check("filter passes raw input through on internal error", filt("hello\n" + "x\n" * 300) == "hello\n" + "x\n" * 300)
os.unlink(cfgp)
# mutation sanity: with keep_patterns emptied, the smart-truncation guarantee must NOT hold (proves the test can fail)
json.dump({"keep_patterns": ["zzz_never"]}, open(cfgp, "w"))
_, wm = both("cat big.log"); check("sanity: test detects missing keep-lines", "card_declined" not in wm[0])
os.unlink(cfgp)

# ---------------------------------------------------------------- config, switches
check("CLAUDE_COMPACT_OFF disables", wrap("ls -la", {"CLAUDE_COMPACT_OFF": "1"}) == "ls -la")
proj = os.path.join(TMP, "proj"); os.makedirs(os.path.join(proj, ".claude"))
open(os.path.join(proj, ".claude", "compact-output.off"), "w").close()
check(".off file in project disables", wrap("ls -la", {"CLAUDE_PROJECT_DIR": proj}) == "ls -la")
os.unlink(os.path.join(proj, ".claude", "compact-output.off"))
json.dump({"skip_commands": ["^make\\b"]}, open(os.path.join(proj, ".claude", "compact-output.json"), "w"))
check("project config skip_commands honoured", wrap("make build", {"CLAUDE_PROJECT_DIR": proj}) == "make build" and "compact-out.py" in wrap("ls", {"CLAUDE_PROJECT_DIR": proj}))
json.dump({"only_commands": ["^rg\\b"]}, open(os.path.join(proj, ".claude", "compact-output.json"), "w"))
check("only_commands restricts wrapping", "compact-out.py" in wrap("rg x", {"CLAUDE_PROJECT_DIR": proj}) and wrap("ls", {"CLAUDE_PROJECT_DIR": proj}) == "ls")
os.unlink(os.path.join(proj, ".claude", "compact-output.json"))
check("dry_run rewrites nothing and logs", wrap("ls -la", {"COMPACT_DRY_RUN": "1"}) == "ls -la" and os.path.exists(os.path.join(DATA, "dry-run.log")))
check("flag_rules can be disabled", "-sb" not in wrap("git status", {"COMPACT_FLAG_RULES": "0"}))

# ---------------------------------------------------------------- flag injection
check("git status -> -sb", "git status -sb" in wrap("git status"))
check("user's git log -5 untouched", "--oneline" not in wrap("git log -5"))
check("git log --stat untouched", "--oneline" not in wrap("git log --stat"))
check("duckdb user -json not overridden", "-csv" not in wrap("duckdb -json -c 'select 1'"))
check("duckdb gets -csv", "duckdb -csv" in wrap("duckdb -c 'select 1'"))

# ---------------------------------------------------------------- compactctl
ctl = lambda *a, env=None: subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "compactctl.py"), *a], capture_output=True, text=True, env={**BASE_ENV, **(env or {})}, cwd=TMP).stdout
ctl("off"); check("compactctl off disables", wrap("ls -la") == "ls -la")
ctl("on"); check("compactctl on re-enables", "compact-out.py" in wrap("ls -la"))
check("compactctl stats reports", "commands filtered" in ctl("stats"), ctl("stats")[:80])

bad = [r for r in results if not r[1]]
for n, ok, note in results:
    print(("PASS " if ok else "FAIL ") + n + (f"   [{note}]" if note and not ok else ""))
print(f"\n{len(results)-len(bad)}/{len(results)} passed")
sys.exit(1 if bad else 0)
