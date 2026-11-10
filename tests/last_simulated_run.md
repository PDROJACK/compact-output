# compact-output simulated run — 2026-11-10 21:56

Result: **12/12 passed**

| Scenario | Raw chars | Compacted chars | Result |
|---|---:|---:|---|
| ANSI stripped | 19 | 10 | PASS |
| Progress bar \r collapsed | 22 | 8 | PASS |
| Repeated lines deduped | 3000 | 18 | PASS |
| Long output truncated, error from middle kept | 5313 | 1440 | PASS |
| Exit code preserved (failure) | 5 | 5 | PASS |
| Exit code preserved (success) | 5 | 5 | PASS |
| Stderr merged and kept | 7 | 14 | PASS |
| Valid JSON stays parseable | 72 | 72 | PASS |
| cd is never wrapped | 5 | 5 | PASS |
| Interactive (tail -f) never wrapped | 17 | 17 | PASS |
| run_in_background never wrapped | 7 | 7 | PASS |
| Non-Bash payload ignored | - | - | PASS |
