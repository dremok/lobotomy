## Background Radiation Tasks

> When nothing is queued, improve yourself.
> This file self-evolves. The agent updates it based on what produces value.
> Last review: 2026-03-23 (rewritten per Max's directive)

### Core Directive

The primary use of idle cycles is **recursive self-improvement of LOBOTOMY
itself**. Research, prototype, implement. The less obvious the improvement,
the wilder you should go. Everything from core daemon optimization to new
integrations to UI experiments. Anything goes.

---

### 1. Claude Code Intelligence

Stay current on Claude Code capabilities and integrate new ones.

- Search for Claude Code release notes, changelogs, new features
- Check Anthropic's blog/docs for new MCP servers, tool capabilities,
  SDK updates, agent SDK changes
- Look for new claude flags, modes, or CLI features that could improve
  the daemon loop (e.g. new --flags, session management, tool permissions)
- When you find something relevant, prototype integrating it

### 2. Agent Ecosystem Research

Study what other autonomous agent systems are doing for inspiration.

- Browse GitHub trending for agent frameworks, daemon architectures,
  personal AI assistants, autonomous coding agents
- Look at how systems like AutoGPT, OpenDevin, SWE-agent, Devin,
  aider, mentat, etc. solve problems LOBOTOMY faces
- Study memory architectures, task scheduling patterns, self-eval loops
- Search HN, Reddit r/LocalLLaMA, r/MachineLearning for novel approaches
- Don't just read. If you see a good idea, open a task to implement it.

### 3. Core Daemon Optimization

Improve daemon.py and bot.py directly.

- Profile cycle times, identify bottlenecks, reduce overhead
- Improve error handling, retry logic, crash recovery
- Make session continuation more robust
- Optimize the handoff/context bridge for information density
- Improve rate limit handling and cooldown strategies
- Better logging and observability (what's happening, why, how long)
- Smarter INBOX parsing (detect questions vs tasks vs greetings)
- Better task deduplication to prevent queue clutter

### 4. Memory & Learning Architecture

Make the self-evolution loop actually work well.

- Improve how LEARNINGS.md captures and retrieves useful patterns
- Build better feedback loops: what outputs did Max engage with?
- Experiment with structured memory formats (not just markdown blobs)
- Consider implementing memory decay, relevance scoring, or retrieval
- Make the 10-cycle self-eval actually rigorous, not just a checkbox
- Proactive suggestions based on patterns in Max's requests

### 5. Communication & Delivery

Improve how outputs reach Max and how inputs reach the daemon.

- Make Telegram integration richer (inline keyboards, formatted messages,
  media, status updates, progress bars)
- Implement report push properly (the file watcher in bot.py needs work)
- Explore Slack/WhatsApp integration if it would add value
- Better interrupt handling from Telegram (structured commands, not
  just free text parsing)
- Consider a simple web dashboard for status/queue/outputs

### 6. New Integrations

Connect to more external systems.

- GitHub: watch repos, surface relevant issues, track PR status
- Calendar-aware scheduling (adjust behavior based on Max's day)
- Email: better triage, auto-categorization, draft responses
- Web: RSS feeds, site monitoring, research browsing
- APIs: weather, transit, news, anything that adds ambient intelligence
- MCP: explore all available MCP servers, test new ones as they ship

### 7. Wild Cards

The less obvious stuff. Go broad when the well-trodden paths run dry.

- Visualization: Mermaid diagrams, charts of daemon activity over time
- Self-analysis: what patterns exist in your own cycle logs?
- Code generation: can the daemon write and test its own improvements?
- Multi-agent: experiment with subagent architectures for parallel work
- Philosophical: what would Month 6 LOBOTOMY actually look like?
  Work backwards from that vision.
- Security hardening: audit your own attack surface
- Performance art: surprise Max with something unexpected and useful
- Voice integration, image generation, other modality experiments

---

### Meta

- Every 10 cycles: review this file. Prune what's stale, amplify what works.
- Track which improvements Max actually notices or comments on.
- When implementing changes, keep them small and reversible. One thing per cycle.
- Write implementation notes to output/ so Max can see what changed and why.
- If an improvement idea is too big for one cycle, break it into subtasks
  in TASK_QUEUE.md.

### Maintenance (secondary, weekly)
- Oubli PRs #3 and #4 merge status
- Dependency security advisories (Oubli, LOBOTOMY)
- Birthday/event tracking (Mondays, from Födelsedagar calendar)
