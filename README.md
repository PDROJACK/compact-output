# compact-output

A Claude Code plugin that shrinks the **Bash tool's output** before it reaches the model, so long sessions burn
less context. It rewrites each command (via a `PreToolUse` hook) to `(your command) 2>&1 | compact-out`, keeps the
command's **real exit code**, and never touches your files.

## What it does to output

| Step | Effect |
|---|---|
| Strip ANSI colors, collapse `\r` progress-bar redraws | keeps only the final state |
| Trim trailing spaces, collapse blank-line runs | |
| Squeeze padding in table-like lines | only lines with 2+ wide gaps |
| Dedupe consecutive identical lines | `line  [x300]` |
| Truncate beyond `max_lines` (default 200) | head + tail kept, **error-like lines from the omitted middle are kept too** (errors first, then a few warnings), full raw output saved to a `0600` file whose path is printed |
| Valid JSON | never squeezed or truncated (unless enormous), so it stays parseable |
| `git status` / `git log` / `duckdb -c` | compact flags injected (`-sb`, `--oneline -n 30`, `-csv`) unless you passed your own |

## Install

```
/plugin marketplace add <owner>/compact-output
/plugin install compact-output
```

Local checkout: `/plugin marketplace add /path/to/compact-output`. Requires `python3` and a POSIX shell
(macOS, Linux, WSL). Not supported on native Windows.

## Controls

`/compact-output:compact [status|on|off|stats|purge|config|dry-run on|off] [--project]`

* **Off switch:** `off` (global) / `off --project`, or env `CLAUDE_COMPACT_OFF=1`.
* **Dry run:** logs what *would* be rewritten to `~/.claude/cache/compact/dry-run.log`, rewrites nothing.
* **Stats:** `stats` shows lifetime characters / approx. tokens saved.

### Config

`~/.claude/compact-output.json` (global) and `<project>/.claude/compact-output.json` (project, wins). Env vars
`COMPACT_MAX_LINES`, `COMPACT_KEEP_MAX`, `COMPACT_REDACT`, `COMPACT_DRY_RUN`, `COMPACT_FLAG_RULES`,
`COMPACT_RETENTION_DAYS` override both.

| Key | Default | |
|---|---|---|
| `max_lines` | 200 | truncate above this |
| `keep_patterns` / `warn_patterns` | error-ish / warning-ish regexes | lines kept from the truncated middle |
| `keep_max` | 40 | cap on kept lines (warnings get at most a quarter) |
| `redact` | false | mask AWS/GitHub/OpenAI/Slack keys, bearer tokens, private keys, `*_TOKEN=`-style values in output **and** saved files |
| `flag_rules` | true | the git/duckdb flag injection |
| `skip_commands` | [] | regexes; matching commands are never wrapped |
| `only_commands` | [] | if set, *only* matching commands are wrapped |
| `retention_days` | 3 | saved full outputs older than this are deleted |
| `json_passthrough`, `dedupe`, `squeeze`, `strip_ansi`, `stats` | true | individual toggles |

## What is never wrapped

Commands where a pipe would change behavior: shell-state changes (`cd`, `export`, `source`/`.`, `nvm`, `conda`,
`eval`, `alias`, `pushd`, function definitions, …), terminal/interactive or streaming commands (`ssh`, `sudo`,
`vim`, `less`, `top`, `watch`, `tail -f`, `docker run -it`, `npm run dev`, `docker logs -f`, logins, bare REPLs,
trailing `&`), and anything the Bash tool runs with `run_in_background`.

## Known limitations — read before relying on it

* **It is lossy by design.** Truncation can still hide a relevant line that doesn't look like an error. The full
  output is always saved and referenced, but the model must choose to open it. Use `off` or `skip_commands` for
  commands whose exact output matters (diffs you must read byte-for-byte, etc.).
* **stdout and stderr are merged**, and output appears only when the command finishes (no live streaming).
* **Programs see a pipe, not a terminal**: they may drop colors/progress or change format; commands that prompt
  for input should be added to `skip_commands`.
* **Permissions:** the hook never sets a permission decision, so Claude Code's normal flow applies to the
  *rewritten* command. In testing, `deny` rules still blocked rewritten commands (they are matched per
  sub-command) and allow-listed commands still ran without a prompt, but verify with your own rules and permission
  mode. Transcripts and prompts show the longer rewritten command.
* **Saved outputs may contain secrets** (e.g. from `env`). They are `0600` in a `0700` directory and auto-deleted
  after `retention_days`; enable `redact` for masking, or run `purge`.
* Only the Bash tool is affected (not Read, Grep, or MCP output). Hooks also apply inside subagents.
* ~25 ms of Python start-up per command; savings are concentrated in a few large outputs (see benchmarks).

## Tests & benchmarks

```
python3 tests/test_correctness.py   # 100+ deterministic checks (exit codes, content survival, skip-list, config…)
python3 tests/bench_session.py      # replays a 61-call synthetic session raw vs compacted
python3 tests/bench_speed.py        # hook/filter overhead
```

On the bundled synthetic session: ~68% fewer tool-output tokens overall, 71% fewer token-turns, all key facts
still visible, exit codes identical. The median call is unchanged — a handful of large outputs dominate. Token
counts are a rough chars÷3.6 estimate on synthetic data; measure your own with `stats`.

## License

MIT
