"""Shared config loading for compact-output.

Precedence (low -> high): defaults < ~/.claude/compact-output.json
< <project>/.claude/compact-output.json (nearest ancestor of cwd) < COMPACT_* env vars.
Kill switches: CLAUDE_COMPACT_OFF=1, or a file named compact-output.off in ~/.claude or in the
nearest <project>/.claude.
"""
import json
import os

DEFAULTS = {
    "max_lines": 200,            # output longer than this is truncated (head + tail + kept lines)
    "keep_patterns": [           # lines in the omitted middle matching these are still shown
        r"\berror\b", r"\bfail(ed|ure|ing)?\b", r"\bexception\b", r"\bfatal\b", r"\bpanic\b",
        r"traceback", r"\bdenied\b", r"\bcritical\b", r"\bassert", r"\bsegfault\b",
        r"\btimed? ?out\b", r"\bunauthori[sz]ed\b", r"\bforbidden\b", r"\bdeclined\b", r"\bkilled\b",
    ],
    "warn_patterns": [r"\bwarn(ing)?\b", r"\bdeprecated\b"],   # lower priority: fill leftover space only
    "keep_max": 40,              # cap on kept middle lines (errors first, then up to keep_max//4 warnings)
    "strip_ansi": True,
    "dedupe": True,              # collapse consecutive identical lines into `line [xN]`
    "squeeze": True,             # squeeze padding in table-like lines
    "json_passthrough": True,    # valid JSON output is never squeezed/truncated (unless huge)
    "redact": False,             # mask common secret formats in output and saved files
    "flag_rules": True,          # inject compact flags for git status/log, duckdb
    "skip_commands": [],         # extra regexes: matching commands are never wrapped
    "only_commands": [],         # if non-empty: ONLY commands matching one of these are wrapped
    "retention_days": 3,         # saved full outputs older than this are deleted
    "stats": True,               # keep a tally of chars saved (compactctl stats)
    "dry_run": False,            # log what would be rewritten, rewrite nothing
}

ENV_MAP = {
    "COMPACT_MAX_LINES": ("max_lines", int),
    "COMPACT_KEEP_MAX": ("keep_max", int),
    "COMPACT_RETENTION_DAYS": ("retention_days", int),
    "COMPACT_REDACT": ("redact", lambda v: v.lower() in ("1", "true", "yes", "on")),
    "COMPACT_DRY_RUN": ("dry_run", lambda v: v.lower() in ("1", "true", "yes", "on")),
    "COMPACT_FLAG_RULES": ("flag_rules", lambda v: v.lower() in ("1", "true", "yes", "on")),
}

HOME_CLAUDE = os.path.join(os.path.expanduser("~"), ".claude")


def data_dir():
    d = os.environ.get("COMPACT_DATA_DIR") or os.path.join(HOME_CLAUDE, "cache", "compact")
    return d


def _read(path):
    try:
        with open(path) as f:
            v = json.load(f)
        return v if isinstance(v, dict) else {}
    except Exception:
        return {}


def _walk_up(start, rel):
    d = os.path.abspath(start or os.getcwd())
    while True:
        p = os.path.join(d, ".claude", rel)
        if os.path.exists(p):
            return p
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def load(cwd=None):
    cfg = dict(DEFAULTS)
    cfg.update({k: v for k, v in _read(os.path.join(HOME_CLAUDE, "compact-output.json")).items() if k in DEFAULTS})
    start = os.environ.get("CLAUDE_PROJECT_DIR") or cwd or os.getcwd()
    proj = _walk_up(start, "compact-output.json")
    if proj and os.path.dirname(os.path.dirname(proj)) != os.path.dirname(HOME_CLAUDE):
        cfg.update({k: v for k, v in _read(proj).items() if k in DEFAULTS})
    for env, (key, conv) in ENV_MAP.items():
        if os.environ.get(env):
            try:
                cfg[key] = conv(os.environ[env])
            except Exception:
                pass
    return cfg


def is_off(cwd=None):
    if os.environ.get("CLAUDE_COMPACT_OFF"):
        return True
    if os.path.exists(os.path.join(HOME_CLAUDE, "compact-output.off")):
        return True
    start = os.environ.get("CLAUDE_PROJECT_DIR") or cwd or os.getcwd()
    return _walk_up(start, "compact-output.off") is not None
