#!/usr/bin/env python3
"""compactctl: control compact-output.   usage: compactctl.py [status|on|off|stats|purge|config|dry-run on|off] [--project]"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cconfig  # noqa: E402


def off_path(project):
    base = os.path.join(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd(), ".claude") if project else cconfig.HOME_CLAUDE
    return os.path.join(base, "compact-output.off")


def cfg_path(project):
    base = os.path.join(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd(), ".claude") if project else cconfig.HOME_CLAUDE
    return os.path.join(base, "compact-output.json")


def main(argv):
    project = "--project" in argv
    args = [a for a in argv if not a.startswith("--")]
    cmd = args[0] if args else "status"
    if cmd == "off":
        p = off_path(project); os.makedirs(os.path.dirname(p), exist_ok=True); open(p, "w").close()
        print(f"compact-output DISABLED ({'this project' if project else 'globally'}): {p}")
    elif cmd == "on":
        p = off_path(project)
        if os.path.exists(p): os.unlink(p)
        print(f"compact-output enabled ({'this project' if project else 'globally'})")
        if cconfig.is_off(): print("note: still off via another switch (env CLAUDE_COMPACT_OFF, or the other scope's .off file)")
    elif cmd == "dry-run":
        p = cfg_path(project); cur = cconfig._read(p); cur["dry_run"] = (args[1:2] == ["on"])
        os.makedirs(os.path.dirname(p), exist_ok=True); json.dump(cur, open(p, "w"), indent=2)
        print(f"dry_run={cur['dry_run']} written to {p}; decisions are logged to {cconfig.data_dir()}/dry-run.log")
    elif cmd == "config":
        print(json.dumps(cconfig.load(), indent=2))
    elif cmd == "purge":
        d = cconfig.data_dir(); n = 0
        if os.path.isdir(d):
            for f in os.listdir(d):
                if f.endswith(".txt") or f.endswith(".log"): os.unlink(os.path.join(d, f)); n += 1
        print(f"deleted {n} saved output/log files from {d}")
    elif cmd == "stats":
        p = os.path.join(cconfig.data_dir(), "stats.jsonl"); raw = out = n = 0; day = {"raw": 0, "out": 0}
        if os.path.exists(p):
            for line in open(p):
                try: r = json.loads(line)
                except ValueError: continue
                n += 1; raw += r["raw"]; out += r["out"]
                if r["t"] > time.time() - 86400: day["raw"] += r["raw"]; day["out"] += r["out"]
        tok = lambda c: round(c / 3.6)
        if not n: print("no data yet"); return
        print(f"commands filtered: {n}")
        print(f"all time : {raw:,} -> {out:,} chars  (~{tok(raw):,} -> ~{tok(out):,} tokens, {100*(raw-out)/max(raw,1):.0f}% saved)")
        print(f"last 24h : {day['raw']:,} -> {day['out']:,} chars  ({100*(day['raw']-day['out'])/max(day['raw'],1):.0f}% saved)")
    else:  # status
        print("state   :", "OFF" if cconfig.is_off() else "ON")
        c = cconfig.load()
        print(f"max_lines={c['max_lines']} redact={c['redact']} flag_rules={c['flag_rules']} dry_run={c['dry_run']} retention_days={c['retention_days']}")
        print("data dir:", cconfig.data_dir())


if __name__ == "__main__":
    main(sys.argv[1:])
