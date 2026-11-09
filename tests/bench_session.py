#!/usr/bin/env python3
"""Replay a realistic ~60-call coding session raw vs. through the compact hook.
Reports per-phase savings, cumulative context growth, token-turns (re-read cost), and needle recall."""
import json, os, shutil, subprocess, sys, textwrap, random
import tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
H = os.path.join(ROOT, "scripts", "compact-bash.py")
os.environ["COMPACT_DATA_DIR"] = tempfile.mkdtemp(prefix="compact-bench-data-")
SB = os.path.join(tempfile.mkdtemp(prefix="compact-bench-"), "sandbox")
random.seed(7)
tok = lambda s: round(len(s) / 3.6)

# ---------------------------------------------------------------- sandbox
def sh(c, cwd=SB, env=None):
    return subprocess.run(["zsh", "-c", c], cwd=cwd, capture_output=True, stdin=subprocess.DEVNULL, timeout=30, env={**os.environ, **(env or {})})
def setup():
    shutil.rmtree(SB, ignore_errors=True); os.makedirs(SB)
    sh("git init -q -b main && git config user.email a@b.c && git config user.name t")
    mods = ["auth", "billing", "cache", "db", "events", "export", "feature_flags", "http", "jobs", "mail", "metrics", "search", "storage", "users"]
    os.makedirs(f"{SB}/src/app"); os.makedirs(f"{SB}/tests"); os.makedirs(f"{SB}/logs"); os.makedirs(f"{SB}/data"); os.makedirs(f"{SB}/node_modules/.bin")
    open(f"{SB}/src/app/__init__.py", "w").write("")
    for m in mods:
        body = "\n".join(f"def {m}_fn{i}(x):\n    # TODO: handle edge case {i}\n    import os, json  # noqa\n    return x + {i}\n" for i in range(25))
        open(f"{SB}/src/app/{m}.py", "w").write(f'"""{m} module"""\n\n{body}')
        t = "import unittest\nfrom app import %s\n\nclass T(unittest.TestCase):\n" % m + "\n".join(
            f"    def test_{m}_{i}(self):\n        self.assertEqual({m}.{m}_fn{i % 25}(1), {1 + (i % 25) + (1 if (m, i) == ('billing', 7) else 0)})\n" for i in range(12))
        open(f"{SB}/tests/test_{m}.py", "w").write(t)
    for n in range(600):  # node_modules-like clutter
        os.makedirs(f"{SB}/node_modules/pkg{n % 60}/lib", exist_ok=True); open(f"{SB}/node_modules/pkg{n % 60}/lib/f{n}.js", "w").write("module.exports={}\n")
    # server log with repetitive + one real error
    lines = []
    for i in range(3000):
        if i == 1777: lines.append("2026-11-10T09:41:07Z ERROR billing.charge: card_declined customer=cus_8812 amount=4200 request_id=req_f00ba7")
        elif i % 7 == 0: lines.append("2026-11-10T09:%02d:%02dZ WARN  http: slow request GET /api/v1/health took 1203ms" % (i // 60 % 60, i % 60))
        else: lines.append("2026-11-10T09:%02d:%02dZ INFO  http: GET /api/v1/items 200 %dms" % (i // 60 % 60, i % 60, 8 + i % 5))
    open(f"{SB}/logs/server.log", "w").write("\n".join(lines) + "\n")
    # csv for duckdb
    with open(f"{SB}/data/orders.csv", "w") as f:
        f.write("id,customer,country,amount,status\n")
        for i in range(2000): f.write(f"{i},cus_{i % 300},{random.choice(['US','DE','IN','BR','JP'])},{random.randint(5,900)},{random.choice(['paid','paid','paid','refunded','failed'])}\n")
    # fake package-manager install that spams progress + ANSI
    open(f"{SB}/fake_install.sh", "w").write(textwrap.dedent('''\
        #!/bin/zsh
        for i in $(seq 1 140); do printf "\\033[32m⠋\\033[0m fetching pkg-$i\\r"; done; echo
        for i in $(seq 1 90); do echo "npm WARN deprecated lodash.$((i%6))@4.17.$i: this package is deprecated"; done
        for i in $(seq 1 40); do echo "added pkg-$i@1.$i.0"; done
        echo "added 312 packages, and audited 313 packages in 14s"; echo "found 0 vulnerabilities"
        '''))
    open(f"{SB}/fake_build.sh", "w").write(textwrap.dedent('''\
        #!/bin/zsh
        for f in src/app/*.py; do echo "  CC   $f"; done
        for i in $(seq 1 60); do printf "[%3d%%] Building object $i\\r" $((i*100/60)); done; echo
        echo "src/app/mail.py:12: warning: unused variable 'x'"; echo "src/app/mail.py:12: warning: unused variable 'x'"; echo "src/app/mail.py:12: warning: unused variable 'x'"
        echo "build finished in 3.2s"
        '''))
    sh("chmod +x fake_install.sh fake_build.sh")
    sh("git add -A >/dev/null 2>&1; git commit -qm 'initial import'")
    for i in range(40):  # history
        m = mods[i % len(mods)]
        sh(f"echo '# change {i}' >> src/app/{m}.py && git commit -qam 'fix({m}): adjust handling for case {i} and update related validation logic'")
    sh("echo '# wip' >> src/app/auth.py; echo new > src/app/scratch.py")  # dirty tree

setup()

# ---------------------------------------------------------------- the session
# (phase, command, [needles that must stay visible])
S = [
 ("orient", "pwd", []),
 ("orient", "ls", []),
 ("orient", "ls -la", []),
 ("orient", "git status", ["auth.py", "scratch.py"]),
 ("orient", "git log", ["adjust handling for case 39"]),
 ("orient", "git branch -a", []),
 ("orient", "find . -path ./node_modules -prune -o -type f -name '*.py' -print", ["billing.py"]),
 ("orient", "find . -type f | wc -l", []),
 ("orient", "du -sh * 2>/dev/null", []),
 ("orient", "wc -l src/app/*.py", ["total"]),
 ("orient", "cat tests/test_billing.py | head -30", ["test_billing_7"]),
 ("explore", "rg 'TODO' src | head -80", []),
 ("explore", "rg -c 'TODO' src", ["billing.py"]),
 ("explore", "rg 'def billing_fn' src", ["billing_fn0"]),
 ("explore", "rg 'import' . --no-ignore", []),
 ("explore", "rg -n 'TODO' .", []),
 ("explore", "grep -rn 'noqa' src", []),
 ("explore", "ls -la node_modules | head -40", []),
 ("explore", "find node_modules -type f | head -300", []),
 ("explore", "git grep -n 'billing' ", ["billing"]),
 ("test", "PYTHONPATH=src python3 -m unittest discover -s tests -v 2>&1", ["FAIL: test_billing_7", "AssertionError"]),
 ("test", "PYTHONPATH=src python3 -m unittest tests.test_billing 2>&1", ["test_billing_7"]),
 ("test", "PYTHONPATH=src python3 -m unittest tests.test_billing.T.test_billing_7 2>&1", ["AssertionError"]),
 ("test", "sed -n '1,20p' src/app/billing.py", []),
 ("test", "git diff", []),
 ("test", "git diff --stat", []),
 ("logs", "tail -n 400 logs/server.log", ["card_declined"]),
 ("logs", "cat logs/server.log", ["card_declined"]),
 ("logs", "grep -c WARN logs/server.log", []),
 ("logs", "grep ERROR logs/server.log", ["card_declined", "req_f00ba7"]),
 ("logs", "grep -n 'slow request' logs/server.log | head -100", []),
 ("logs", "awk '{print $3}' logs/server.log | sort | uniq -c", ["INFO", "WARN", "ERROR"]),
 ("data", "duckdb -c \"select status, count(*) n, sum(amount) total from 'data/orders.csv' group by 1 order by 2 desc\"", ["paid", "refunded"]),
 ("data", "duckdb -c \"select * from 'data/orders.csv' limit 40\"", []),
 ("data", "duckdb -c \"select country, status, count(*) from 'data/orders.csv' group by all order by all\"", []),
 ("data", "duckdb -c \"describe select * from 'data/orders.csv'\"", ["amount"]),
 ("data", "head -20 data/orders.csv", []),
 ("data", "duckdb -json -c \"select * from 'data/orders.csv' limit 5\"", []),
 ("build", "./fake_install.sh", ["added 312 packages", "found 0 vulnerabilities"]),
 ("build", "./fake_build.sh", ["build finished", "unused variable"]),
 ("build", "python3 -m pip list 2>&1", []),
 ("build", "python3 --version", ["Python"]),
 ("build", "which python3 node npm", []),
 ("env", "env | sort", []),
 ("env", "ps aux | head -60", []),
 ("env", "df -h", []),
 ("env", "docker ps -a 2>&1", []),
 ("env", "kubectl get pods -A 2>&1", []),
 ("env", "lsof -i -P -n 2>/dev/null | head -60", []),
 ("git", "git add -A && git status", ["billing"]),
 ("git", "git log --stat -n 8", []),
 ("git", "git log -p -n 3 -- src/app/mail.py", []),
 ("git", "git show HEAD --stat", []),
 ("git", "git diff HEAD~10 --stat", []),
 ("git", "git shortlog -sn HEAD", []),
 ("git", "git reflog | head -50", []),
 ("small", "echo done", ["done"]),
 ("small", "mkdir -p /tmp/x && echo ok", ["ok"]),
 ("small", "cat package.json 2>&1", []),
 ("small", "head -5 src/app/auth.py", []),
 ("small", "git rev-parse --short HEAD", []),
]

def hooked(cmd):
    r = subprocess.run([sys.executable, H], input=json.dumps({"tool_name": "Bash", "cwd": SB, "tool_input": {"command": cmd}}), capture_output=True, text=True)
    return json.loads(r.stdout)["hookSpecificOutput"]["updatedInput"]["command"] if r.stdout.strip() else cmd

rows = []
for ph, cmd, needles in S:
    r = sh(cmd); w = sh(hooked(cmd))
    ro, wo = r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace"), w.stdout.decode("utf-8", "replace") + w.stderr.decode("utf-8", "replace")
    # needles may live in the saved full-output file (recoverable) or directly visible
    found_vis = [n in wo for n in needles]
    rows.append(dict(ph=ph, cmd=cmd, raw=tok(ro), new=tok(wo), rc=(r.returncode == w.returncode), needles=needles, vis=found_vis,
                     present_raw=[n in ro for n in needles], trunc="full output:" in wo))

# ---------------------------------------------------------------- report
N = len(rows)
tot_r, tot_n = sum(x["raw"] for x in rows), sum(x["new"] for x in rows)
print(f"Session replay: {N} tool calls, sandbox repo with 14 modules, 40 commits, 600 vendored files, 3k-line log, 2k-row CSV\n")
print(f"{'phase':8} {'calls':>5} {'raw tok':>9} {'compact tok':>12} {'saved':>6}")
for ph in dict.fromkeys(x["ph"] for x in rows):
    g = [x for x in rows if x["ph"] == ph]; a, b = sum(x["raw"] for x in g), sum(x["new"] for x in g)
    print(f"{ph:8} {len(g):5} {a:9} {b:12} {100*(a-b)/max(a,1):5.0f}%")
print(f"{'TOTAL':8} {N:5} {tot_r:9} {tot_n:12} {100*(tot_r-tot_n)/tot_r:5.0f}%\n")

# context growth: every output stays in context; each later turn re-reads it
def curve(key): 
    c, out = 0, []
    for x in rows: c += x[key]; out.append(c)
    return out
cr, cn = curve("raw"), curve("new")
tt_r = sum(x["raw"] * (N - i) for i, x in enumerate(rows)); tt_n = sum(x["new"] * (N - i) for i, x in enumerate(rows))
print("Context taken by tool output after call #:")
for k in (10, 20, 30, 40, 50, N):
    print(f"  #{k:<3} raw {cr[k-1]:8}  compact {cn[k-1]:7}   ({100*(cr[k-1]-cn[k-1])/max(cr[k-1],1):.0f}% smaller)")
print(f"\nToken-turns (each output re-read on every later turn): raw {tt_r:,} -> compact {tt_n:,}  ({100*(tt_r-tt_n)/tt_r:.0f}% less)")
# distribution
sv = sorted((100*(x["raw"]-x["new"])/max(x["raw"],1)) for x in rows)
big = [x for x in rows if x["raw"] >= 2000]
print(f"Calls: median saving {sv[N//2]:.0f}% | {sum(1 for s in sv if s < 1)} of {N} calls unchanged (<1%) | {len(big)} calls >=2k tokens produce {100*sum(x['raw'] for x in big)/tot_r:.0f}% of raw volume")
print(f"Window pressure: raw session would use {tot_r/200000*100:.0f}% of a 200k context in tool output alone; compacted {tot_n/200000*100:.0f}%")
print("\nTop 10 savers:")
for x in sorted(rows, key=lambda x: x["raw"] - x["new"], reverse=True)[:10]:
    print(f"  {x['raw']:7} -> {x['new']:6}  {x['cmd'][:70]}")

# correctness
nd = [(x, n, v) for x in rows for n, v, pr in zip(x["needles"], x["vis"], x["present_raw"]) if pr]
lost = [(x["cmd"], n) for x, n, v in nd if not v]
print(f"\nNeedle recall (key facts a human/agent would need): {len(nd)-len(lost)}/{len(nd)} visible in compacted output")
for c, n in lost: print(f"  LOST from view: {n!r}  in `{c[:60]}`  (recoverable via saved file: {'yes' if any(x['cmd']==c and x['trunc'] for x in rows) else 'NO'})")
bad = [x["cmd"] for x in rows if not x["rc"]]
print(f"Exit codes identical on all calls: {'yes' if not bad else 'NO -> ' + str(bad)}")
print(f"Calls truncated (full output saved to file): {sum(x['trunc'] for x in rows)}")
