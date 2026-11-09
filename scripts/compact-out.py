#!/usr/bin/env python3
"""compact-out: stdin -> compacted stdout.

Strips ANSI/progress noise, trailing spaces, blank runs; squeezes table padding; dedupes
consecutive repeats; truncates huge output while KEEPING error-like lines from the omitted
middle; leaves valid JSON alone. The complete raw output of truncated runs is saved (0600) and
its path is printed. On any internal error the raw input is passed through unchanged.
"""
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cconfig  # noqa: E402

ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[()][A-B0-2]")
SECRETS = [
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AKIA****"),
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"), "gh*_****"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{30,}"), "github_pat_****"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"), "sk-****"),
    (re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"), "xox*-****"),
    (re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]{16,}"), r"\1 ****"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S), "[PRIVATE KEY REDACTED]"),
    (re.compile(r"(?im)^(\s*(?:export\s+)?[A-Z0-9_]*(?:SECRET|TOKEN|PASSWORD|PASSWD|API_?KEY|PRIVATE_?KEY|CREDENTIAL)[A-Z0-9_]*\s*[=:]\s*)\S+"), r"\1****"),
]


def redact(text):
    for rx, rep in SECRETS:
        text = rx.sub(rep, text)
    return text


def is_json(text):
    s = text.strip()
    if not s or s[0] not in "{[" or s[-1] not in "}]":
        return False
    try:
        json.loads(s)
        return True
    except Exception:
        return False


def squeeze_line(ln):
    body = ln.lstrip(" ")
    pad = ln[: len(ln) - len(body)]
    if len(re.findall(r"\S {3,}\S", body)) >= 2:          # table-like only
        body = re.sub(r"(?<=\S) {2,}(?=\S)", "  ", body)
    return pad + body


def save_full(raw, cfg):
    d = cconfig.data_dir()
    os.makedirs(d, mode=0o700, exist_ok=True)
    try:
        os.chmod(d, 0o700)
        cutoff = time.time() - cfg["retention_days"] * 86400
        for n in os.listdir(d):
            fp = os.path.join(d, n)
            if n.endswith(".txt") and os.path.getmtime(fp) < cutoff:
                os.unlink(fp)
    except OSError:
        pass
    path = os.path.join(d, f"{int(time.time() * 1000)}-{os.getpid()}.txt")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(raw)
    return path


def process(raw, cfg):
    text = ANSI.sub("", raw) if cfg["strip_ansi"] else raw
    if cfg["redact"]:
        text = redact(text)
    limit = max(int(cfg["max_lines"]), 10)

    jsonish = cfg["json_passthrough"] and is_json(text)
    if jsonish and text.count("\n") <= limit * 10:
        return text if text.endswith("\n") else text + "\n"

    lines = []
    for ln in text.split("\n"):
        if "\r" in ln:                                    # progress bars: keep final state
            parts = [p for p in ln.split("\r") if p.strip()]
            ln = parts[-1] if parts else ""
        ln = ln.rstrip()
        if cfg["squeeze"] and not jsonish:
            ln = squeeze_line(ln)
        lines.append(ln)

    out, i = [], 0
    while i < len(lines):
        j = i
        if cfg["dedupe"] and not jsonish:
            while j + 1 < len(lines) and lines[j + 1] == lines[i]:
                j += 1
        n = j - i + 1
        if lines[i] == "":
            if out and out[-1] != "":
                out.append("")
        elif n > 2:
            out.append(f"{lines[i]}  [x{n}]")
        else:
            out.extend([lines[i]] * n)
        i = j + 1
    while out and out[-1] == "":
        out.pop()

    if len(out) > limit:
        full = redact(raw) if cfg["redact"] else raw
        path = save_full(full, cfg)
        h = t = int(limit * 0.35)
        middle = out[h: len(out) - t]
        shown, hits_total = [], 0
        try:
            strong = re.compile("|".join(f"(?:{p})" for p in cfg["keep_patterns"]), re.I) if cfg["keep_patterns"] else None
            weak = re.compile("|".join(f"(?:{p})" for p in cfg["warn_patterns"]), re.I) if cfg["warn_patterns"] else None
            errs = [(i, l) for i, l in enumerate(middle) if l and strong and strong.search(l)]
            warns = [(i, l) for i, l in enumerate(middle) if l and weak and weak.search(l) and not (strong and strong.search(l))]
            hits_total = len(errs) + len(warns)
            pick = errs[: cfg["keep_max"]]
            pick += warns[: min(max(cfg["keep_max"] - len(pick), 0), max(cfg["keep_max"] // 4, 1))]
            shown = [l for _, l in sorted(pick)]
        except re.error:
            pass
        hits = range(hits_total)
        note = f"... [{len(middle)} lines omitted; full output: {path}] ..."
        block = [note]
        if shown:
            block.append(f"[kept {len(shown)} of {len(hits)} error/warning-like lines from the omitted section]")
            block.extend(shown)
            block.append("... [end of omitted section] ...")
        out = out[:h] + block + out[len(out) - t:]
    return "\n".join(out) + ("\n" if out else "")


def main():
    raw = sys.stdin.buffer.read().decode("utf-8", "replace")
    try:
        cfg = cconfig.load()
        result = process(raw, cfg)
    except Exception:
        cfg, result = None, raw                           # never lose output
    sys.stdout.write(result)
    sys.stdout.flush()
    if cfg and cfg.get("stats"):
        try:
            d = cconfig.data_dir()
            os.makedirs(d, mode=0o700, exist_ok=True)
            with open(os.path.join(d, "stats.jsonl"), "a") as f:
                f.write(json.dumps({"t": int(time.time()), "raw": len(raw), "out": len(result)}) + "\n")
        except OSError:
            pass


if __name__ == "__main__":
    main()
