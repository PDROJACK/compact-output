#!/usr/bin/env python3
"""End-to-end simulated run of compact-output. Usage: python3 tests/test_simulated_run.py

For each scenario: send a PreToolUse(Bash) payload to the hook, execute the (possibly rewritten) command in a
shell, and compare against the raw command. Isolated HOME/data dir. Writes a report to
tests/last_simulated_run.md (kept in the repo) and exits non-zero on any failure.
"""
import datetime
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(ROOT, "scripts", "compact-bash.py")
REPORT = os.path.join(ROOT, "tests", "last_simulated_run.md")
SH = "bash" if sys.platform.startswith("linux") else "zsh"
TMP = tempfile.mkdtemp(prefix="compact-sim-")
HOME = os.path.join(TMP, "home")
os.makedirs(os.path.join(HOME, ".claude"))
ENV = {**os.environ, "HOME": HOME, "COMPACT_DATA_DIR": os.path.join(TMP, "data"), "TERM": "xterm"}
for k in ("CLAUDE_COMPACT_OFF", "CLAUDE_PROJECT_DIR", "COMPACT_MAX_LINES", "COMPACT_REDACT"):
    ENV.pop(k, None)


def hook(cmd, **ti):
    r = subprocess.run([sys.executable, HOOK], capture_output=True, text=True, cwd=TMP, env=ENV,
                       input=json.dumps({"tool_name": "Bash", "cwd": TMP, "tool_input": {"command": cmd, **ti}}))
    out = r.stdout.strip()
    return json.loads(out)["hookSpecificOutput"]["updatedInput"]["command"] if out else cmd


def sh(cmd):
    p = subprocess.run([SH, "-c", cmd], capture_output=True, cwd=TMP, env=ENV)
    return p.stdout.decode("utf-8", "replace"), p.returncode


# (name, command, check(raw_out, raw_rc, new_out, new_rc, wrapped) -> error string or None, hook kwargs)
def rc_same(_ro, rrc, _no, nrc, _w):
    return None if rrc == nrc else f"exit code {rrc} -> {nrc}"


SCENARIOS = [
    ("ANSI stripped",
     r"printf '\033[31mred\033[0m plain\n'",
     lambda ro, rrc, no, nrc, w: "ANSI left in output" if "\x1b[" in no else ("text lost" if "red plain" not in no else None), {}),
    ("Progress bar \\r collapsed",
     r"printf 'dl 10%%\rdl 50%%\rdl 100%%\n'",
     lambda ro, rrc, no, nrc, w: None if "dl 100%" in no and "dl 10%" not in no else "\\r redraws not collapsed", {}),
    ("Repeated lines deduped",
     "for i in $(seq 300); do echo same line; done",
     lambda ro, rrc, no, nrc, w: None if "[x300]" in no and no.count("same line") == 1 else "dedupe missing", {}),
    ("Long output truncated, error from middle kept",
     "for i in $(seq 1 600); do echo line-$i; [ $i = 300 ] && echo 'FATAL: disk exploded'; done",
     lambda ro, rrc, no, nrc, w: ("error line lost" if "FATAL: disk exploded" not in no else
                                  "not truncated" if len(no) >= len(ro) else
                                  "head/tail lost" if "line-1\n" not in no or "line-600" not in no else None), {}),
    ("Exit code preserved (failure)",
     "echo oops; exit 7",
     lambda ro, rrc, no, nrc, w: f"exit {nrc}, expected 7" if nrc != 7 else None, {}),
    ("Exit code preserved (success)",
     "echo fine",
     rc_same, {}),
    ("Stderr merged and kept",
     "echo to-err 1>&2; echo to-out",
     lambda ro, rrc, no, nrc, w: None if "to-err" in no and "to-out" in no else "stderr lost", {}),
    ("Valid JSON stays parseable",
     "python3 -c \"import json;print(json.dumps({'a':[1,2,3],'b':{'c':'  x   y  '}}, indent=2))\"",
     lambda ro, rrc, no, nrc, w: None if json.loads(no) == json.loads(ro) else "JSON altered", {}),
    ("cd is never wrapped",
     "cd /tmp && pwd",
     lambda ro, rrc, no, nrc, w: "state command was wrapped" if w != "cd /tmp && pwd" else None, {}),
    ("Interactive (tail -f) never wrapped",
     "tail -f /dev/null",
     None, {}),   # checked wrapping only, never executed
    ("run_in_background never wrapped",
     "echo bg",
     None, {"run_in_background": True}),
    ("Non-Bash payload ignored",
     None, None, {}),
]


def main():
    rows, failures = [], 0
    for name, cmd, check, kw in SCENARIOS:
        if name == "Non-Bash payload ignored":
            r = subprocess.run([sys.executable, HOOK], capture_output=True, text=True, env=ENV,
                               input=json.dumps({"tool_name": "Read", "tool_input": {"file_path": "/x"}}))
            err = None if r.stdout.strip() == "" else "hook rewrote a non-Bash tool call"
            rows.append((name, "(Read tool payload)", err, "-", "-"))
        elif check is None:
            w = hook(cmd, **kw)
            err = "was wrapped" if w != cmd else None
            rows.append((name, cmd, err, len(cmd), len(w)))
        else:
            w = hook(cmd, **kw)
            ro, rrc = sh(cmd)
            no, nrc = sh(w)
            err = rc_same(ro, rrc, no, nrc, w) or check(ro, rrc, no, nrc, w)
            rows.append((name, cmd, err, len(ro), len(no)))
        failures += bool(rows[-1][2])

    lines = [f"# compact-output simulated run — {datetime.datetime.now():%Y-%m-%d %H:%M}", "",
             f"Result: **{len(rows) - failures}/{len(rows)} passed**", "",
             "| Scenario | Raw chars | Compacted chars | Result |", "|---|---:|---:|---|"]
    for name, _cmd, err, a, b in rows:
        lines.append(f"| {name} | {a} | {b} | {'FAIL: ' + err if err else 'PASS'} |")
    report = "\n".join(lines) + "\n"
    with open(REPORT, "w") as f:
        f.write(report)
    print(report)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
