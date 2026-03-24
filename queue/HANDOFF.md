# Handoff — Cycle #69

**Time**: 2026-03-24 19:08 (Tuesday)
**Task**: GitGuardian incident: WhatsApp credentials leaked in git (P1)
**Status**: Fixed (files removed from tracking), but history still contains the secret

## What I Did

Read the actual Gmail notification via Gmail MCP. It was from **GitGuardian** (not Dependabot), flagging a "Generic High Entropy Secret" in commit `3ef6d92`. The secret was `whatsapp-mcp/auth_info/creds.json` containing WhatsApp encryption keys, identity keys, and auth secrets.

Removed from git tracking (files still exist locally, already in .gitignore):
- `whatsapp-mcp/auth_info/creds.json` (THE leaked secret)
- `whatsapp-mcp/data/whatsapp.db*` (database files)
- `.mcp.json` (MCP server config)
- `whatsapp-mcp/mcp-logs.txt`

Previous cycle #68 had already removed `whatsapp-mcp/node_modules/` (8,343 files).

## Important: Credentials still in git history

The WhatsApp creds are removed from HEAD but still exist in git history (commit `3ef6d92`). Options:
1. **If repo stays public**: Need `git filter-branch` or BFG Repo Cleaner to purge history, then force-push. This is destructive.
2. **Make repo private**: Simpler mitigation. Limits exposure.
3. **Re-authenticate WhatsApp**: If the keys are considered burned, re-pair the WhatsApp connection.

This needs Max's decision. Tagged as BLOCKED.

## Also noted

`.claude/settings.local.json` and `.claude/CLAUDE.md` are still tracked despite `.claude/` being in .gitignore. These contain hook configs and project instructions, not secrets, but it's inconsistent. Left them for now since CLAUDE.md is explicitly referenced as "checked into the codebase" in the project instructions.

## Queue State

- P1: BLOCKED on Max for git history cleanup decision
- No other P1/P2 tasks
- P3: morning brief Wed 06:30, research radar Wed 22:00, kid activity planner Thu 20:00
