#!/usr/bin/env python3
"""PreToolUse(Bash) hook for compact-output.

1. Simple commands: inject compact-format flags (git status/log, duckdb).
2. Everything else that is safe to pipe: wrap as
       (cmd) 2>&1 | compact-out.py     with the command's real exit status preserved.
Never sets a permission decision: Claude Code's normal permission flow applies to the rewritten
command. On any error the original command is left untouched.
"""
import json
import os
import re
import shlex
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cconfig  # noqa: E402

# Commands that change shell state: running them in a pipeline subshell would silently lose the change.
STATE_CMDS = {
    "cd", "pushd", "popd", "export", "source", ".", "alias", "unalias", "unset", "set", "shopt", "setopt",
    "unsetopt", "eval", "nvm", "conda", "mamba", "pyenv", "rbenv", "fnm", "volta", "asdf", "direnv", "mise",
    "deactivate", "activate", "trap", "umask", "ulimit", "declare", "typeset", "local", "readonly", "hash",
    "exec", "read", "wait", "disown", "fg", "bg",
}
# Need a terminal, prompt for input, or stream forever: buffering would hide or break them.
INTERACTIVE_CMDS = {
    "ssh", "sudo", "su", "vim", "vi", "nvim", "nano", "emacs", "less", "more", "top", "htop", "btop", "watch",
    "man", "open", "code", "passwd", "login", "screen", "tmux", "nohup", "claude", "ping",
    "fzf", "ranger", "mc", "lazygit", "k9s",
}
REPL_CMDS = {"python", "python3", "node", "irb", "ruby", "psql", "mysql", "sqlite3", "duckdb", "lua", "ghci", "bash", "zsh", "sh", "fish"}
INTERACTIVE_RX = re.compile(
    r"(\s|^)(-it|-ti|--follow|--watch)(\s|$)"
    r"|\btail\s+(-\w*[fF]|--follow)"
    r"|\b(journalctl|kubectl\s+logs|docker\s+logs|docker\s+compose\s+logs)\b.*\s-f\b"
    r"|\b(npm|yarn|pnpm|bun)\s+(run\s+)?(dev|start|serve|watch)\b"
    r"|\b(next|vite|nuxt|webpack-dev-server|uvicorn|gunicorn|nodemon)\b"
    r"|\bflask\s+run\b|\bdocker\s+compose\s+up\b(?!.*\s-d\b)|\bdocker-compose\s+up\b(?!.*\s-d\b)"
    r"|\b(gh|gcloud|aws|az|npm|docker|firebase|vercel|netlify)\s+(auth\s+)?(login|logout)\b"
    r"|\bsso\s+login\b|\bpython3?\s+-m\s+http\.server\b|\bkubectl\s+(port-forward|exec\s+.*-it?)\b"
)
FUNC_DEF_RX = re.compile(r"(^|[;&|\n]\s*)(function\s+\w+|\w+\s*\(\s*\))\s*\{")
SEP_RX = re.compile(r"\|\||&&|[;|&\n(){}]+")


def first_word(segment):
    toks = segment.strip().split()
    while toks and re.fullmatch(r"[A-Za-z_]\w*=\S*", toks[0]):   # leading VAR=val
        toks.pop(0)
    return (toks[0] if toks else ""), toks


def should_skip(cmd, cfg):
    if re.search(r"compact-out\.py", cmd) or FUNC_DEF_RX.search(cmd) or INTERACTIVE_RX.search(cmd):
        return True
    if re.search(r"(^|[^&])&\s*$", cmd):                          # trailing background job
        return True
    for seg in SEP_RX.split(cmd):
        w, toks = first_word(seg)
        base = os.path.basename(w)
        if base in STATE_CMDS or base in INTERACTIVE_CMDS:
            return True
        if base in REPL_CMDS and len(toks) == 1:                  # bare REPL / interactive shell
            return True
    for rx in cfg["skip_commands"]:
        try:
            if re.search(rx, cmd):
                return True
        except re.error:
            pass
    if cfg["only_commands"]:
        return not any(re.search(rx, cmd) for rx in cfg["only_commands"] if _valid(rx))
    return False


def _valid(rx):
    try:
        re.compile(rx)
        return True
    except re.error:
        return False


def inject_flags(cmd):
    """Return new simple command string, or None."""
    if re.search(r"[|&;<>`$()\n]", cmd):
        return None
    try:
        t = shlex.split(cmd)
    except ValueError:
        return None
    if not t:
        return None
    has = lambda *fl: any(a in fl or any(a.startswith(f + "=") for f in fl) for a in t[1:])
    if t[0] == "git" and len(t) >= 2:
        if t[1] == "status" and not has("-s", "--short", "-sb", "--porcelain", "-b", "--long"):
            return shlex.join(t[:2] + ["-sb"] + t[2:])
        if t[1] == "log" and not has("--oneline", "--format", "--pretty", "-n", "-p", "--stat", "--graph", "--name-only",
                                     "--name-status", "--shortstat", "--numstat", "--since", "--until") \
                and not any(re.fullmatch(r"-\d+", a) or a.startswith("--max-count") for a in t):
            return shlex.join(t[:2] + ["--oneline", "-n", "30", "--no-decorate"] + t[2:])
    elif t[0] == "duckdb" and len(t) > 1:
        modes = ("-csv", "-json", "-jsonlines", "-line", "-list", "-markdown", "-box", "-table", "-column", "-ascii",
                 "-html", "-latex", "-insert", "-interactive", "-agent", "--agent", "-c-less")
        if not has(*modes):
            return shlex.join([t[0], "-csv"] + t[1:])
    return None


def wrap(cmd):
    filt = shlex.quote(os.path.join(HERE, "compact-out.py"))
    py = shlex.quote(sys.executable or "python3")
    # The user's command runs unmodified in a subshell; its real exit status travels via a temp file.
    return (
        f'__rc=$(mktemp); {{ (\n{cmd}\n); echo $? >"$__rc"; }} 2>&1 | {py} {filt}; '
        '__s=$(cat "$__rc"); rm -f "$__rc"; (exit ${__s:-1})'
    )


def log_dry(msg):
    try:
        d = cconfig.data_dir()
        os.makedirs(d, mode=0o700, exist_ok=True)
        with open(os.path.join(d, "dry-run.log"), "a") as f:
            f.write(f"{int(time.time())}\t{msg}\n")
    except OSError:
        pass


def main():
    data = json.load(sys.stdin)
    if data.get("tool_name") != "Bash":
        return
    inp = data.get("tool_input") or {}
    original = inp.get("command") or ""
    cmd = original.strip()
    cwd = data.get("cwd")
    if not cmd or cconfig.is_off(cwd) or inp.get("run_in_background"):
        return
    cfg = cconfig.load(cwd)

    new = inject_flags(cmd) if cfg["flag_rules"] else None
    final_cmd = new or cmd
    if not should_skip(final_cmd, cfg):
        final_cmd = wrap(final_cmd)
    if final_cmd == cmd:
        return
    if cfg["dry_run"]:
        log_dry(f"{cmd!r} -> {final_cmd!r}")
        return
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "updatedInput": {**inp, "command": final_cmd},
    }}))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass            # a hook failure must never block or alter a tool call
