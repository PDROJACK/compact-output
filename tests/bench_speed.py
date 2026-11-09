import json, os, subprocess, time, statistics as st
import sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
H = os.path.join(ROOT, "scripts", "compact-bash.py"); F = os.path.join(ROOT, "scripts", "compact-out.py")
PY = sys.executable
def t(fn, n=15):
    xs = []
    for _ in range(n):
        a = time.perf_counter(); fn(); xs.append((time.perf_counter() - a) * 1000)
    return st.median(xs)
hook = lambda c: subprocess.run([PY, H], input=json.dumps({"tool_name":"Bash","tool_input":{"command":c}}), capture_output=True, text=True)
def wrap(c):
    r = hook(c); return json.loads(r.stdout)["hookSpecificOutput"]["updatedInput"]["command"]
sh = lambda c: subprocess.run(["zsh","-c",c], capture_output=True)
print(f"python3 bare startup        {t(lambda: subprocess.run(['python3','-c','pass'])):7.1f} ms")
print(f"hook (rewrite decision)     {t(lambda: hook('git status')):7.1f} ms   <- paid once per Bash call")
for n in (10, 1000, 20000, 200000):
    data = "".join(f"line {i}  value  {i*3}\n" for i in range(n)).encode()
    print(f"filter, {n:>6} lines       {t(lambda: subprocess.run([PY, F], input=data, capture_output=True), 7):7.1f} ms")
print("\nend-to-end wall time (median), raw vs wrapped:")
for name, c in [("true (no-op)", "true"), ("ls -la /usr/bin", "ls -la /usr/bin"), ("ps aux", "ps aux"),
                ("seq 1 20000", "seq 1 20000"), ("sleep 0.5", "sleep 0.5"), ("find /usr/share (large)", "find /usr/share | head -20000")]:
    w = wrap(c); a = t(lambda: sh(c), 7); b = t(lambda: sh(w), 7)
    print(f"{name:20} raw {a:8.1f} ms   wrapped {b:8.1f} ms   overhead {b-a:+7.1f} ms")
