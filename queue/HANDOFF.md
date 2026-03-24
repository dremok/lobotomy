# Handoff — Cycle #113

**Time**: 2026-03-24 19:11 (Tuesday)
**Task**: Add background_timeout for non-urgent cycles
**Status**: Completed

## What I Did

Added a `background_timeout` config option (600s / 10 min) that applies
to non-urgent cycles. Urgent cycles (P0/P1) still use `session_timeout`
(900s). Most successful background cycles complete in 100-270s, so 600s
gives plenty of headroom while reducing wasted time when cycles get stuck.

Changes:
- daemon.py: select timeout based on `has_urgent_tasks()`
- config.yaml: added `background_timeout: 600`

## Queue State

- P2: Trello integration (BLOCKED on credentials).
- P3: morning brief Wednesday 06:30 (~11h away).
- Background cooldown active.

## What's Next

- Morning brief Wednesday 06:30.
- Trello integration when Max provides credentials.

## Blockers

- Trello: needs API key + token from Max.
- Oubli PRs #3 and #4: BLOCKED, needs Max.
