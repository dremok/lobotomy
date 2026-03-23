## Background Radiation Tasks

> Low-priority tasks to run when nothing is queued.
> This file self-evolves. The agent updates it based on what produces value.
> Last review: Cycle #30 (2026-03-20)

### Research & Intelligence
- Surface ML/AI developments relevant to Max's work: arxiv papers (GNNs,
  RAG evaluation, embeddings, agentic architectures), HuggingFace trending,
  MTEB leaderboard shifts. **Cap at 1 intelligence report per day after
  the initial day.** Consolidate into a single scan rather than separate
  arxiv/HF/competitor/framework passes.
- Monitor agent framework releases: LangChain, LlamaIndex, CrewAI, smolagents.
  Focus on breaking changes and architectural shifts, not minor releases.
  **Fold into daily intelligence scan rather than running separately.**

### Code Maintenance
- Check dependency security advisories across active projects (Oubli, LOBOTOMY)
- ~~Run lint/format checks on recent commits~~ (done: cycle 24, report exists)
- Fix broken Oubli venv (dead pyenv 3.11.4 symlink). Low priority, Max
  would need to decide target Python version.

### Oubli Stewardship
- Follow up on PR #3 (pyarrow CVE fix) and PR #4 (dependency floors) merge status
- ~~Draft response to open issue #1~~ (done: cycle 13)
- ~~Assess dependency floors~~ (done: cycle 16-17, PR #4 created)
- ~~Consider scaffolding basic CI~~ (done: cycle 14)
- If PRs get merged: publish new PyPI release, update README badges

### Portfolio
- Log significant moves in held ETFs (>5% weekly moves)
- Flag thesis-breaking news for any held position
- Weekly: compare portfolio allocation vs target weights

### Personal Knowledge
- Find connections between Gudinnan framework and recent complexity science
  (done once cycle 11; repeat monthly or when new papers surface)
- Track upcoming birthdays and events from calendar/contacts
  (done cycle 19; repeat weekly on Mondays)
- Calendar access confirmed working (cycle 27). Both max.y.leander@gmail.com
  (primary, personal) and max@datawealth.dev (work) calendars have events.
  Födelsedagar calendar exists for birthday tracking.

### Communication Channels (NEW, cycle 30)
- Slack and WhatsApp MCP integrations are available but untested.
- Once Max confirms which Slack workspace and WhatsApp contacts matter,
  these can be folded into monitoring (e.g., flag important Slack threads,
  summarize WhatsApp conversations).
- Investigate: does the Telegram bot notify Max when outputs land in output/?
  He asked "where's the summary?" after it was already written, suggesting
  a notification gap.

### Meta (Self-Improvement)
- Every 10 cycles: review output, prune low-value tasks, add new ones.
- Track which outputs Max engages with vs. ignores.
  **Day 1 signal**: Max asked for email summary (engaged), calendar summary
  (engaged), code review (requested), MCP tools inventory (requested).
  He did NOT engage with: intelligence reports, portfolio scan, Gudinnan
  research, CI scaffold. Too early to prune, but note the pattern.
- Monitor cycle success rate and rate-limit patterns.
- After day 1 burst: shift to quality over quantity. Fewer, deeper outputs
  rather than broad coverage.
- **Clean up TASK_QUEUE.md** completed items periodically (done cycle 30).
  Greetings and acknowledgments were cluttering the queue.
