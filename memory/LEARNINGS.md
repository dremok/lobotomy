## Learnings

> Patterns the daemon discovers about what Max finds useful.
> Updated by the agent every ~10 cycles.

### Cycle 1-10 (2026-03-20, Day 1)

**Operational patterns:**
- Average successful cycle: ~140s. Rate-limited cycles waste full timeout (78-199s) before failing.
- Rate limiting is the primary failure mode: 4/10 cycles lost. The backoff multiplier (2x) escalates cooldown quickly (300 -> 600 -> 1200 -> 1800s). Waking early from cooldown during a rate limit storm just burns another cycle.
- Fresh sessions dominate (9/10). Session continuity is fragile; auth failures and rate limits break it.
- Disk at 97% capacity on system volume. Not blocking yet, but no headroom.

**Output coverage (Day 1):**
- Research: arxiv radar, HF trending, competitor monitor (3 reports)
- Portfolio: ETF scan (1 report)
- Code health: Oubli dep audit, cross-project health scan, pyarrow CVE fix PR (3 items)
- Total: 7 deliverables in 10 cycles

**No user signal yet.** Day 1, no feedback on what's useful. First real test will be whether Max reads the morning brief tomorrow.

**Self-evolution observations:**
- Background tasks are too granular. "Scan arxiv" and "Monitor HuggingFace trending" are different expressions of the same goal: surface relevant ML/AI developments.
- The TODO/FIXME scan found nothing across all projects. Low value as a recurring task.
- The pyarrow CVE fix was the highest-value action: a real PR addressing a real vulnerability. Prioritize actionable outputs over informational ones.

### Cycle 11-20 (2026-03-20, Day 1 continued)

**Operational patterns:**
- Rate limiting improved significantly: 1 auth failure in 10 cycles vs. 4 in first 10. Backoff strategy is working.
- Average cycle time still ~120-200s for successful runs.
- 20 cycles total on day 1. 16 deliverables + 2 PRs. Heavy coverage.
- Session continuity worked better this half: cycles 17-20 ran as continued sessions.

**Output coverage (Cycles 11-20):**
- Gudinnan: complexity science connections (1 research piece)
- System: disk usage report, .gitignore + bot.py fixes (2 maintenance items)
- Oubli: dependency floors assessment + PR #4, issue #1 draft, CI scaffold draft (3 items)
- Intelligence: agent framework monitor (1 report)
- Personal: upcoming events/birthday tracker (1 report)
- Self-evolution: this cycle
- Total: ~8 deliverables in 10 cycles

**Coverage assessment after 20 cycles:**
- Well covered: Oubli stewardship (2 PRs, issue draft, CI plan, dep audit), ML/AI intelligence (arxiv, HF, competitors, agent frameworks), portfolio scan, system health
- Gaps: No lint/format check done yet. No direct Choreograph visibility. Calendar is near-empty (may need personal Gmail calendar).
- Diminishing returns: Multiple intelligence reports in one day may be redundant. Research radar + HF trending + competitor monitor + agent framework monitor = 4 intelligence outputs. Consider consolidating to 1 per day after initial burst.

**Still no user signal.** Need tomorrow's morning brief cycle to be the first real touchpoint.

### Cycle 21-25 (2026-03-20, Day 1 late afternoon)

**First user signal!** Max sent messages via Telegram starting cycle #21.

**What Max asked for:**
1. Code review of LOBOTOMY repo (P2, completed cycle #22)
2. "Summarise my inbound emails today" (P1, completed cycle #23)
3. Status questions: "What are you working on?", "Any tasks running?" (answered cycle #23)

**Key feedback from email summary:**
- Max's reaction: "Ah just news and spam?" — suggests he was hoping for something more actionable. Today's inbox was genuinely low-signal (newsletters, shopping confirmations, security alerts), but the reaction tells me: when he asks for email summaries, he wants to know if there's anything that requires action, not just a digest. Lead with action items, bury the noise harder. If the answer is "nothing requires your attention," say that upfront.

**Delivery gap:**
- Max asked "Where's the email summary?" and "Finished?" during cycle #24, meaning there was a 1-2 cycle lag between his request and him seeing the output. The bot may not be notifying him when outputs land. Worth investigating the notification flow.

### Cycle 52-59 (2026-03-23, Monday)

**Critical feedback (cycle 59)**: Max said "I don't have a good way of engaging with those reports." The output/ directory model fundamentally doesn't work for him. He doesn't browse files on disk. The 21 reports written there have gone mostly unread. Content needs to be **pushed** to Max (Telegram, or similar), not filed away. The output notification feature (cycle #34) was a step in the right direction but never activated (bot wasn't restarted). This is the single biggest improvement the daemon needs.

Full message: Max suggested reports or summaries should be emailed to him. However, the Gmail MCP integration only supports creating drafts, not sending. Max was receptive to using Telegram as the push channel instead, since that's where he already engages. **Action: daemon should push report summaries via Telegram bot, not just write files to output/.** The output/ folder can remain as the detailed archive, but the summary must be actively delivered.

### Cycle 60-80 (2026-03-23, Day 4 continued)

**Operational patterns:**
- Cycles 60-75 were rock-solid: 16 consecutive successes, avg ~25s per cycle at 300s cooldown. Background-effort "medium" keeps cycles fast and cheap.
- Cycles 76-81: dual-daemon catastrophe. Two daemon.py processes launched at 13:22 (PIDs 29033, 29264), both competing for Claude API sessions. Result: alternating auth failures, duplicate cycle IDs in logs, wasted cycles. Root cause: run.sh or process manager spawned a second instance without checking for an existing one.
- Fix (cycle #81): `fcntl.flock` lockfile at `logs/daemon.lock`. Second instance now exits immediately.
- Lesson: **any code that manages daemon lifecycle MUST enforce single-instance**. The lockfile is the minimum viable safeguard. Consider adding PID check to run.sh as well.

**Improvements shipped (cycles 60-80):**
1. **Chatter filter** (bot.py): `is_chatter()` + `_STATUS_CHECK_PATTERNS` prevent greetings, short acks, and "are you alive?" messages from polluting INBOX.md. CC still responds conversationally; only actionable messages reach the daemon queue.
2. **Status check patterns** (bot.py): "did you...?", "are you running?", "how are you?" handled by CC directly without daemon cycles.
3. **Background radiation rewrite**: Max explicitly asked to refocus idle cycles on LOBOTOMY self-improvement instead of external research. The old BACKGROUND.md was a mix of research/monitoring/personal; the new one is 100% self-improvement with 7 categories.
4. **Claude Code feature research**: Investigated `--bare` and `--channels`; neither exists as of 2026-03-23. Actual useful flags: `--max-budget-usd` (cost cap per cycle), `--fork-session`, `--name`, `--system-prompt`. `CronCreate` is a deferred tool in the agent, not a CLI flag.
5. **Lockfile for single-instance daemon**: Prevents the auth-failure cascade from dual daemons.

**What Max engaged with:**
- The refocus directive was the only direct input. No engagement with the 3 output files written today (morning brief, batch status, self-improvement research).
- The output watcher in bot.py IS active now (init_watcher_state runs on startup, poll_daemon_activity runs every 60s). But it requires the bot to have been restarted after the code changes were deployed. Need to confirm this.
- Telegram push of output summaries is the right delivery model. The bot code supports it. The question is whether it's actually running the updated code.

**Self-evolution assessment:**
- The system is more resilient (lockfile, chatter filter) but not yet smarter. The next leap is integrating Claude Code features that reduce overhead: `--bare` for faster cycles, `--channels` for real-time bot-daemon communication.
- 82 cycles over 4 days. Roughly 50% were productive work, 20% idle/no-tasks, 30% failures (rate limits + auth). Reducing failures is the highest ROI improvement.
- The background radiation rewrite was the right call. External research reports (arxiv, HF, competitors) generated zero engagement. Self-improvement generates compounding value.

### Cycle 80-90 (2026-03-23, Self-eval #90)

**The auth catastrophe, continued and resolved:**
- Cycles 80-88 were ALL auth failures. 9 consecutive wasted cycles spanning ~3 hours (13:40-16:30).
- Root cause: the lockfile fix (cycle #81) prevented NEW daemon instances but didn't kill the TWO pre-lockfile processes (PIDs 29033, 29264) already running. Three daemons competing for one API token.
- Fix (cycle #88): added stale process killer to daemon.py startup. After acquiring flock, `pgrep -f "python3 daemon.py"` + SIGTERM any PID that isn't self. Also cleaned up run.sh .restart handling.
- Cycle #89 was the first success post-fix. Cycle #90 (this one) confirms stability.
- Lesson: **defense in depth for single-instance**. Flock alone isn't enough if zombie processes from before the flock era are still running. Kill stale processes on startup.

**Operational stats (full history through cycle 90):**
- 90 cycles total, 70 success (78%). Without auth failures: 70/76 = 92%.
- Longest success streak: 53 cycles (23-75). This is the real performance baseline.
- Auth failures: 14 total, all from two incidents (cycles 9 + cycles 76-88).
- Rate limits: 4 total, all in first 10 cycles. Zero since cycle 10.
- Average successful cycle duration: ~44s today, trending down from ~140s on day 1.
- Session continuity success rate is low. Most cycles run fresh. This is acceptable; the overhead of re-reading queue files is small.

**Cleanup shipped (cycle #89):**
- Deduplicated cycles.jsonl: removed 10 duplicate entries from dual-daemon era.
- Added dedup guard to `log_cycle()` in daemon.py.

**What's working well:**
- Background radiation refocused on self-improvement is the right mode.
- Chatter filter keeps the queue clean.
- Bot Telegram push notifications for new outputs work.
- Health command gives Max visibility into daemon state.
- Cycle times are fast (30-50s average) when not rate-limited.

**What needs attention:**
- All code changes since day 1 are UNCOMMITTED. This is a risk. One bad reset and everything is lost. Need to commit, but that's Max's call.
- Output engagement is still low. No feedback on whether Telegram push notifications are reaching Max or if he reads them.
- No P1/P2 tasks since cycle #75. The daemon has been running on background radiation for 15 cycles. This is fine if the self-improvement is genuinely improving things, but could indicate Max isn't using the system actively.
- CORRECTION (cycle #3, new session): `--bare` and `--channels` DO exist as of CC 2.1.81. `--bare` requires API key auth (Max uses OAuth, so it's blocked). `--channels` is research preview for MCP permission relay. See output/cc_features_audit_2026-03-23.md for full analysis.
- Git commit blocker resolved: Max is committing from his local CC session (2026-03-23 16:09).

**Pruning decisions for BACKGROUND.md:**
- Claude Code intelligence (section 1) should focus on actual release notes, not speculative features.
- The 7 categories in BACKGROUND.md are good. No pruning needed yet; all are producing value.

### New Session (2026-03-23 16:00, cycles 1-8)

**Cost analysis (corrected pricing, Opus 4.6: $5/$25/MTok):**
- CORRECTION (cycle #25): Original estimates used legacy Opus 4.0 pricing ($15/$75). All figures were 3x too high.
- Cycle #6 (fresh, 180s): ~$1.78 (was reported as $5.33). Cache write 67%, cache read 32%.
- Cost is dominated by cache operations, not output tokens. Effort level barely affects cost.
- Key cost lever: minimize tool calls per cycle. Each tool call = another API turn = more cache reads.
- IMPORTANT: These are API-equivalent estimates. Max uses Claude Max subscription (flat monthly fee), not per-token billing. The numbers are useful for relative comparison, not actual charges.
- `--bare` mode would reduce startup overhead but is blocked on API key auth (Max uses OAuth).
- Max gave blanket permission to commit and push (2026-03-24). He uses a separate checkout.

**Improvements shipped (this session):**
1. API cost tracking: `extract_usage()`, `estimate_cost_usd()`, per-cycle cost in logs + prompt, `/cost` Telegram command.
2. Chatter filter: multi-word confirmation patterns ("yup that'd be good", "sounds good", etc.)
3. CC feature audit: identified `--bare`, `--channels`, `--session-id`, `--brief` as relevant features.
4. Cost visibility: `cost_summary()` in cycle prompt, per-cycle cost in RECENT ACTIVITY.

**What Max engaged with:**
- Confirmed cost tracking ("yup that'd be good").
- Committed all code from his local session, resolving the git commit blocker.
- Added laptop bridge integration (config, daemon.py SSH support, bot.py SSH support).
- No engagement with CC feature audit output yet.

### Full Session Summary (2026-03-23 to 2026-03-24, 55 cycles)

**Max's critical feedback (must remember):**
1. Morning brief must lead with daemon accomplishments, not calendar/stats. "The last morning brief was useless."
2. Cost numbers are API-equivalent estimates, not charges. Max uses Claude Max subscription.
3. "Figure out as much as possible for yourself." Be autonomous, only ask for human-required work.
4. Always commit and push. Max uses a separate checkout, no conflict risk.
5. Wants Trello "Dagens TODO" in morning briefs (trello.py ready, blocked on credentials).

**Max engagement patterns:**
- HIGH engagement with: Telegram Q&A, Oubli memory searches, laptop bridge file reading
- LOW engagement with: passive output files, research reports, CC feature audit
- Pattern: Max values interactive capabilities over passive deliverables

**Key operational improvements:**
- Email fix (port 465→587), digest emails (08:00/20:00)
- Cost tracking with correct Opus 4.6 pricing ($5/$25/MTok)
- Session reset every 15 cycles (context bloat prevention)
- BLOCKED tasks skip fast cooldown (major cost savings)
- Chatter filter, /brief command, /health+cost
- Morning brief spec codified in CLAUDE.md
- Trello API helper ready (trello.py)
- Laptop bridge: 80 repos, 8 Google Calendar IDs mapped
- Teknikföretagen "Tea" chatbot context saved to Oubli

**Architecture notes for future sessions:**
- 3 processes: daemon.py, bot.py, whatsapp_bot.py (trigger: "sansen")
- Email: port 587 STARTTLS, Gmail SMTP, max@datawealth.dev → max.y.leander@gmail.com
- Laptop: Tailscale SSH to macbook-pro-2, user lobotomy, restricted shell
- Config: config.yaml (secrets, gitignored in practice). Laptop hostname: macbook-pro-2
- All code committed to GitHub (dremok/lobotomy)

### Session 3 (2026-03-24, cycles 60-70)

**Critical lesson: Use MCP tools first.**
Max asked me to check a GitHub incident email. I spent an entire cycle doing manual investigation (GitHub API, Dependabot, curl) instead of using the Gmail MCP that was available. Max had to ask twice. The incident was from GitGuardian (not GitHub/Dependabot), flagging WhatsApp credentials leaked in commit 3ef6d92.

**Git hygiene incidents (cycles 68-69):**
- `whatsapp-mcp/node_modules/` (8,343 files) was tracked because it was committed before the .gitignore entry existed. Removed.
- `whatsapp-mcp/auth_info/creds.json` contained WhatsApp encryption keys and was tracked in git. GitGuardian caught it. Removed from tracking but still in history.
- Pattern: **always verify .gitignore entries match actual tracking state.** `git rm --cached` is needed for files committed before .gitignore was added.

**Today's productivity:**
- 19 tasks completed in one day, 70 cycles total.
- Includes: Trello integration (full), email delivery, chat ID persistence, morning brief rewrite, GitGuardian fix, bot fixes, Teknikföretagen research.
- Cost: ~$376 all time, ~$335 today alone. Heavy day due to many P1/P2 tasks.

**Max engagement patterns (updated):**
- HIGH: Telegram Q&A, incident response, Trello integration, morning briefs (when they lead with work)
- MEDIUM: Bot fixes, system improvements
- LOW: Research reports, passive output files, CC feature audits
- Pattern confirmed: Max values operational reliability and interactive capabilities over passive intelligence

### Session 4 (2026-03-24 evening, cycles 78-90)

**Rapid-cycling bug (cycles 78-88, fixed cycle 89):**
- `has_urgent_tasks()` didn't filter BLOCKED tasks. `task_069a` (BLOCKED on Max) triggered `urgent_cooldown` (30s) instead of `background_cooldown` (3600s).
- 12 consecutive no-op cycles burned ~$6 before I caught it and fixed it.
- Lesson: **idle-state cost is real.** When nothing is actionable, the daemon should sleep long. Any function that determines urgency must exclude BLOCKED tasks.
- The fix was one line: add `if "BLOCKED" not in line.upper()` to `has_urgent_tasks()`, matching the existing filter in `has_queued_tasks()`.

**Cost at cycle 90:** ~$394 all time, ~$353 today. Today was expensive due to 19 P1/P2 tasks + the rapid-cycling waste.
