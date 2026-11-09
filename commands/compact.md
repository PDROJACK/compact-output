---
description: Control compact-output (status | on | off | stats | purge | config | dry-run on|off; add --project for this project only)
allowed-tools: Bash(python3:*)
argument-hint: "[status|on|off|stats|purge|config|dry-run on|off] [--project]"
---

Run this command and show its output to the user verbatim, with no extra commentary:

!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/compactctl.py" $ARGUMENTS`
