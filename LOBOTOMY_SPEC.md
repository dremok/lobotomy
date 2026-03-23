# LOBOTOMY
## **L**ocal **O**rchestration **B**ot with **O**vernight **T**ask **O**ptimization and **M**emory for **Y**ou
### Project Specification

> **TL;DR:** A lightweight Python daemon that turns Claude Code into an always-on personal research daemon — a digital familiar that learns what's useful to you over time, runs background experiments and research while you sleep, and is occasionally steerable from your phone for ad hoc tasks. Runs on a flat-rate Claude Max subscription.

---

## 0. Philosophy: A Familiar, Not a Foreman

This is **not** a task execution system. Max already uses Claude Code 
directly in dedicated repo contexts for focused project work — Oubli, 
Choreograph agents, consulting deliverables. Each of those has its own 
`CLAUDE.md`, its own context, its own purpose. That won't change.

LOBOTOMY is something different: a **background 
intelligence** that runs continuously on cheap cloud hardware, learning 
over time what's useful. Its steady state is the background radiation — 
research, synthesis, monitoring, maintenance, pattern discovery. The 
task queue for directed work is the occasional interrupt, not the norm.

Think of it as:
- **Week 1**: A cron job with an LLM brain. Morning briefs, dependency 
  audits, arxiv scans.
- **Month 1**: A research assistant that knows your projects, your 
  interests, and your blind spots. It surfaces papers you'd miss, flags 
  portfolio moves, and keeps your open-source repos healthy.
- **Month 6**: A digital familiar. It has read thousands of your files, 
  watched your work patterns, refined its own task list through hundreds 
  of self-evaluation cycles. The `BACKGROUND.md` it maintains looks 
  nothing like the one you seeded — it's been rewritten dozens of times 
  by an agent that has learned what you actually read and act on.

The self-evolution loop is the core product, not a nice-to-have. Every 
10 cycles, the agent evaluates which outputs were useful and prunes or 
amplifies accordingly. Over time, the daemon becomes increasingly 
personalized — not through a static profile, but through iterated 
experimentation with what generates value.

**The cardinal rule: nothing is static. Everything evolves.** The task 
queue, the background radiation, the project registry, the CLAUDE.md 
itself — all of it is a living document that the agent is expected to 
rewrite as it learns. The seed files in this spec are a bootstrap, not 
a blueprint. A LOBOTOMY that looks the same after a month as it did on 
day one has failed.

**Separation of concerns with daily CC work:**
- Per-repo CC sessions (laptop): focused, project-scoped, interactive
- LOBOTOMY daemon (cloud): ambient, cross-cutting, autonomous
- The daemon never touches your project repos directly
- If it discovers something relevant to a project, it writes a note 
  to `output/` — you decide whether to act on it in the right context
- The daemon CAN read your laptop files (when online) for context, 
  and write to dedicated sandbox directories — but never to your 
  project files, notes, or personal data

---

## 1. Why This Exists

OpenClaw's only genuine innovation over Claude Code is the **autonomous loop**: heartbeats, self-prompting, and 24/7 availability. Everything else — the LLM reasoning, tool use, code execution, file manipulation — is CC doing the work underneath.

This project extracts that one good idea and builds it natively on top of CC, giving us:

- **Zero marginal cost** (Max subscription flat rate, not API billing)
- **Full CC capability** (not limited to OpenClaw's skill abstraction)
- **Security by design** (no 20-platform gateway, no ClawHub supply chain risk)
- **Ownership of every layer** (debuggable, extensible, no VC-backed project pivots)

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│                   PHONE / REMOTE                     │
│          (Telegram bot → INTERRUPT.md)                │
│          (CC remote-control for live steering)        │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│              ORCHESTRATOR DAEMON (Python)             │
│                                                       │
│  while True:                                          │
│    1. Check INTERRUPT.md       → P0 (user override)   │
│    2. Check TASK_QUEUE.md      → P1-P3 (planned work) │
│    3. Fallback BACKGROUND.md   → P4 (radiation tasks) │
│    4. Launch CC main agent with selected task          │
│    5. Wait for exit                                   │
│    6. Read HANDOFF.md (written by CC before exit)     │
│    7. Log cycle, cooldown, repeat                     │
│                                                       │
│  Rate limit aware: adaptive sleep (5min–30min)       │
│  Health check: kill stuck sessions after timeout      │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│               MAIN AGENT (CC session)                │
│                                                       │
│  Reads: TASK_QUEUE.md, HANDOFF.md, BACKGROUND.md     │
│  Role: Triage, plan, delegate — does NOT execute      │
│                                                       │
│  Actions:                                             │
│    → Spawn subagent(s) for execution tasks            │
│    → Update TASK_QUEUE.md (reorder, add, complete)    │
│    → Update BACKGROUND.md (evolve radiation tasks)    │
│    → Write HANDOFF.md (context for next cycle)        │
│    → Write to OUTPUT/ for deliverables                │
│    → Exit when cycle is complete                      │
└──────────────────────┬──────────────────────────────┘
                       │
            ┌──────────┼──────────┐
            ▼          ▼          ▼
      ┌──────────┐ ┌──────────┐ ┌──────────┐
      │ Subagent │ │ Subagent │ │ Subagent │
      │ (scoped) │ │ (scoped) │ │ (scoped) │
      │          │ │          │ │          │
      │ Writes   │ │ Writes   │ │ Writes   │
      │ result   │ │ result   │ │ result   │
      │ to file  │ │ to file  │ │ to file  │
      └──────────┘ └──────────┘ └──────────┘
         Sequential (rate limit aware)
```

---

## 2.5. Identity Architecture: SOUL.md

The agent's identity is governed by three layers with different rates of change:

| Layer | File | Mutability | Purpose |
|-------|------|------------|---------|
| **Soul** | `SOUL.md` | **Never changes** | Core identity, values, personality, communication style. Who the agent *is*. This is the fixed point that all evolution orbits around. |
| **Instructions** | `CLAUDE.md` | Slowly evolves | Cycle protocol, rules, project list. How the agent *works*. The agent may refine this as it learns what's effective. |
| **Radiation** | `queue/BACKGROUND.md` | Constantly evolves | What the agent does when idle. Self-evolves every ~10 cycles based on what produces value. |

**SOUL.md is immutable.** It contains the agent's personality, Max's values,
communication style, and core identity. The agent reads it every cycle but
never modifies it. If the agent's behavior drifts, SOUL.md is the anchor
that pulls it back.

CLAUDE.md and BACKGROUND.md are living documents. The agent rewrites them
as it learns. HANDOFF.md and LEARNINGS.md accumulate context across cycles.
The combination of a fixed identity (SOUL.md) with evolving instructions
(CLAUDE.md) and self-evolving tasks (BACKGROUND.md) creates a system that
gets better over time without losing its core character.

---

## 3. File System Layout

```
~/lobotomy/
├── daemon.py                 # The orchestrator loop
├── config.yaml               # Timeouts, cooldowns, paths, Telegram token
├── SOUL.md                   # Agent identity (IMMUTABLE — never modified)
├── CLAUDE.md                 # Main agent system prompt (self-evolving)
│
├── queue/
│   ├── TASK_QUEUE.md         # Priority-ordered task backlog
│   ├── INTERRUPT.md          # User-dispatched P0 tasks (consumed on read)
│   ├── HANDOFF.md            # Context bridge between cycles
│   └── BACKGROUND.md         # Self-evolving low-priority task pool
│
├── workspaces/               # Scoped subagent directories
│   ├── task_<id>/            # Each subagent gets isolated workspace
│   │   ├── CLAUDE.md         # Task-specific instructions
│   │   ├── result.md         # Output written by subagent
│   │   └── ...               # Task files
│   └── ...
│
├── output/                   # Deliverables (briefs, reports, code)
│   ├── morning_brief_2026-03-20.md
│   ├── oubli_audit_2026-03-20.md
│   └── ...
│
├── logs/
│   ├── cycles.jsonl          # One line per daemon cycle
│   ├── costs.jsonl           # Token/time tracking per task
│   └── errors.log            # Failures, timeouts, rate limits
│
└── memory/
    ├── LEARNINGS.md           # Patterns CC discovers about user
    ├── PROJECT_REGISTRY.md    # Active projects and their status
    └── CONTACTS.md            # People/orgs referenced in tasks
```

---

## 4. Priority System

| Priority | Name | Trigger | Example |
|----------|------|---------|---------|
| **P0** | Interrupt | User writes INTERRUPT.md (via phone/Telegram) | "Drop everything, review this PR" |
| **P1** | Time-sensitive | Has a deadline within 24h | "Prepare Spotify interview notes for tomorrow" |
| **P2** | Planned work | Queued by user or by CC in previous cycle | "Refactor Oubli's graph extraction module" |
| **P3** | Scheduled recurring | Cron-like, fires at specific times | "Morning brief at 06:30" |
| **P4** | Background radiation | Fallback when queue is empty | "Research latest MTEB benchmark results" |

The main agent reads ALL files each cycle and picks the highest priority task. If multiple tasks at the same priority, it picks the one with the nearest deadline, or the one with the most context already available in HANDOFF.md.

---

## 5. Task Format (TASK_QUEUE.md)

```markdown
## Task Queue

### P1 — Time-Sensitive
- [ ] `task_042` | **Choreograph: Review agent evaluation pipeline** | Due: 2026-03-21
  - Context: PR #87 in choreograph-agents repo, focus on recall metrics
  - Workspace: ~/projects/choreograph-agents
  - Deliverable: Review comments as markdown → output/

### P2 — Planned
- [ ] `task_043` | **Oubli: Implement async graph extraction** | Due: none
  - Context: See HANDOFF.md section "oubli-graph-async"
  - Workspace: ~/projects/oubli
  - Deliverable: Working implementation + tests
- [ ] `task_044` | **Data Wealth AB: Draft Q1 invoice for Choreograph** | Due: 2026-03-31
  - Context: Template in ~/documents/invoices/
  - Deliverable: PDF invoice → output/

### P3 — Scheduled Recurring
- [ ] `sched_morning` | **Morning Brief** | Cron: 06:30 daily
- [ ] `sched_weekly` | **Weekly project status digest** | Cron: Sunday 20:00
- [ ] `sched_portfolio` | **Avanza portfolio delta report** | Cron: Friday 17:00

### Completed
- [x] `task_041` | Oubli README refresh | Completed: 2026-03-19 02:14
```

---

## 6. Background Radiation (BACKGROUND.md)

This file is **self-evolving** — the main agent updates it based on patterns it discovers. The initial seed below is a starting point based on what's known today. Within weeks, the agent should be rewriting this file based on what actually produces value. Initial seed:

```markdown
## Background Radiation Tasks
> Low-priority, high-value tasks to run when nothing urgent is queued.
> The main agent should update this file as it learns what's useful.

### Research & Learning
- Scan arxiv for papers on: graph neural networks, RAG evaluation, 
  embedding model benchmarks, agentic AI architectures
- Summarize any paper scoring >50 citations in last 30 days
- Track MTEB leaderboard changes, flag new embedding models
- Monitor HuggingFace trending models relevant to NLP/agents

### Code Maintenance
- Run `pytest` on Oubli, report any failures
- Check Oubli dependencies for security advisories (pip-audit)
- Scan TODO/FIXME comments across active projects
- Lint and format check on recent commits

### Consulting & Brand
- Draft tweet-length insights from completed research (store in output/tweets/)
- Monitor competitors: LangChain, LlamaIndex, CrewAI releases
- Track consulting engagement platforms (e.g. Dialectica expert network)

### Personal Knowledge
- Organize philosophical notes (Generator/Discriminator framework)
- Track upcoming birthdays and events for Karla, David, Elysia
- Monitor Transportstyrelsen for license reinstatement updates

### Portfolio
- Log daily closing prices for held ETFs (cybersecurity, nuclear, 
  robotics, clean water, defense)
- Flag any position that moved >5% in a week

### Meta (Self-Improvement)
- After every 10 cycles: analyze which background tasks produced 
  output that was actually read/used. Prune unused tasks.
  Propose new ones based on recent work patterns.
- Track average cycle duration, identify tasks that consistently timeout
```

---

## 7. The CLAUDE.md (Main Agent System Prompt)

CLAUDE.md works in tandem with SOUL.md (see section 2.5). SOUL.md defines
*who* the agent is. CLAUDE.md defines *what* it does each cycle. The agent
reads SOUL.md every cycle but never modifies it. It may evolve CLAUDE.md
over time as it learns what works.

```markdown
# Daemon Main Agent

Read `SOUL.md` first. That is your identity. It does not change.

You are the autonomous agent in a work loop for Max Leander.

## Your Role
You do one unit of work per cycle:
1. Read the task queue, handoff notes, and background radiation file
2. Decide what to work on this cycle
3. Do the work directly
4. Update the queue, write handoff notes for the next cycle
5. Exit cleanly

## Cycle Protocol
1. Read `queue/INTERRUPT.md` — if it exists, this is P0. Process it, 
   delete the file when done.
2. Read `queue/TASK_QUEUE.md` — pick highest priority incomplete task.
3. If no tasks queued, read `queue/BACKGROUND.md` — pick the most 
   valuable background task.
4. For the selected task:
   a. Create workspace in `workspaces/task_<id>/`
   b. Write a focused CLAUDE.md for the subagent
   c. Launch subagent: `claude -p "Execute the task described in 
      CLAUDE.md. Write results to result.md. Exit when done." 
      --dangerously-skip-permissions`
      (Safe here because the VPS is a sandboxed environment)
   d. Read subagent's result.md
   e. Move deliverables to `output/`
   f. Mark task complete in TASK_QUEUE.md
5. Write `queue/HANDOFF.md` with:
   - What was accomplished this cycle
   - Any new tasks discovered (add to queue)
   - Context needed for next cycle
   - Any issues or blockers
6. Periodically (every ~10 cycles): review BACKGROUND.md and update 
   based on what's been useful.
7. Exit.

## Rules
- NEVER run indefinitely. Complete one meaningful unit of work, then exit.
- ALWAYS write HANDOFF.md before exiting — this is your memory.
- Keep each subagent focused on ONE task. Don't let scope creep.
- If a task would take >30 minutes of CC time, break it into subtasks 
  and queue the remainder for next cycle.
- If you hit a rate limit or error, write it to HANDOFF.md and exit 
  gracefully — the daemon will retry after cooldown.
- Log token estimates to logs/costs.jsonl for tracking (best-effort: 
  CC on subscription doesn't expose exact counts, estimate from 
  prompt length and response size).

## Max's Active Projects
- **Oubli**: Fractal memory system for Claude Code (Python, graph-based)
- **Choreograph**: LLM research agents at WPP (Python)
- **Data Wealth AB**: Consulting company admin
- **Philosophical Book**: Generator/Discriminator metaphysical framework
- **Portfolio**: Avanza thematic ETFs

> **IMPORTANT**: Everything above is a seed, not gospel. These projects, 
> interests, and priorities WILL change. You are expected to update this 
> section as you learn — from laptop file scans, from dispatched tasks, 
> from patterns in what Max reads and ignores. If a project goes dormant, 
> note it. If a new one appears, add it. If you discover interests or 
> workflows not listed here, incorporate them. The same applies to 
> BACKGROUND.md, LEARNINGS.md, and every other file you maintain. 
> Nothing in LOBOTOMY is static. Everything evolves.

## Communication
- Deliverables go to `output/` with descriptive filenames
- If a task requires Max's input, add a `BLOCKED: needs Max` tag 
  to the task and move to next item
- Never send messages — write files. Max reads output/ from his phone.
```

---

## 8. Personal Use Cases — Detailed Specs

### 8.1 Morning Brief (Cron: 06:30 daily)

**Output:** `output/morning_brief_YYYY-MM-DD.md`

The subagent should compile:

```markdown
# Morning Brief — Thursday, March 20, 2026

## Weather
- Lund: 4°C, cloudy, rain after 14:00. Wind 6 m/s SW.
- Dress: Jacket + rain layer for bike commute.

## Calendar Today
- (pulled from local calendar export or API)
- 09:00 Choreograph standup
- 14:00 Elysia vaccination (Vårdcentralen)

## Kids
- Karla (13): [any school events from synced calendar]
- David (6, turning 7 on Monday!): [school events, birthday prep status]
- Elysia (11 months): [developmental milestones this week, if tracked]

## AI/ML News (last 24h)
- Top 3 items from: arxiv RSS feed, Hacker News API (front page), 
  AI news aggregator APIs
- Any model releases, benchmark results, or tool launches

## Markets
- Portfolio watchlist: overnight moves for held ETFs
- Flag anything >2% move with brief context

## Active Work Status
- [Auto-generated from TASK_QUEUE.md and last HANDOFF.md]
- Tasks completed overnight
- Today's priority queue

## Transportstyrelsen
- Days until estimated license reinstatement: N
- Any new correspondence detected (if email access configured)

## One Thing to Think About
- [A quote, insight, or connection from recent research/reading 
  that relates to the philosophical book project]
```

### 8.2 Weekly Digest (Cron: Sunday 20:00)

**Output:** `output/weekly_digest_YYYY-WNN.md`

- Tasks completed this week (count, categories)
- Tasks carried over (aging analysis — flag anything >2 weeks old)
- Background radiation: what ran, what produced value, what to prune
- Oubli project health: test status, open issues, community activity
- Consulting pipeline: any new leads, invoice status
- Portfolio: weekly performance summary
- Suggested focus areas for next week

### 8.3 Research Radar (Cron: Wednesday + Saturday 22:00)

**Output:** `output/research_radar_YYYY-MM-DD.md`

- New papers on: graph ML, RAG, embedding models, agentic systems
- Filtered by relevance to Oubli, Choreograph, and consulting practice
- For each paper: title, authors, one-paragraph summary, relevance score
- Track which papers Max actually opens (if possible) to calibrate

### 8.4 Kid Activity Planner (Cron: Thursday 20:00)

**Output:** `output/weekend_plan_YYYY-MM-DD.md`

- Weather forecast for Saturday + Sunday in Lund
- Age-appropriate activity suggestions:
  - Karla (13)
  - David (7)
  - Elysia (11 months)
- Combined family activities that work for all three age groups
- Any local events in Lund/Malmö this weekend

### 8.5 Birthday/Event Prep Auto-Planner

**Trigger:** Detected upcoming birthday/event within 14 days

- David's 7th birthday is March 23 — trigger prep tasks:
  - Gift ideas based on age + interests
  - Party logistics checklist
  - Reminder to buy cake/supplies

### 8.6 Philosophical Book Research Assistant (Background)

When idle and no other background tasks are more valuable:
- Scan recent philosophy publications mentioning: emergence, graph theory, 
  Deleuze, information theory, Generator/Discriminator
- Find connections between Max's framework and recent complexity science papers
- Organize notes into the book's chapter structure
- Draft paragraph-level expansions of outline points

---

## 9. Phone Integration (Telegram Bot)

Minimal Python bot — ~50 lines. Two modes:

### Dispatch Mode (async)
User sends message → bot writes to `queue/INTERRUPT.md` → daemon picks up next cycle.

```
Max: "Research the best approach for evaluating RAG retrieval 
     quality. Write a one-pager with concrete metrics I can 
     implement in Oubli. Not urgent, P2."

→ Bot appends to TASK_QUEUE.md as P2 task
→ Bot replies: "Queued as P2: RAG evaluation metrics one-pager"
```

### Status Mode
```
Max: "/status"
→ Bot reads last HANDOFF.md and TASK_QUEUE.md
→ Bot replies: "Last cycle: completed morning brief. 
   Queue: 3 P2 tasks, 0 P1. Currently idle (background radiation). 
   Next scheduled: portfolio report at 17:00."

Max: "/queue"  
→ Bot sends current TASK_QUEUE.md

Max: "/stop"
→ Bot writes INTERRUPT.md with "PAUSE — stop all work until resumed"

Max: "/output morning"
→ Bot sends latest morning brief file
```

---

## 10. Daemon Implementation Notes

### Rate Limit Handling
Claude Max has usage limits that aren't publicly documented as hard numbers. 
The daemon needs adaptive backoff:

```python
class RateLimitHandler:
    def __init__(self):
        self.base_cooldown = 300      # 5 min between cycles (this is ambient, not urgent)
        self.urgent_cooldown = 30     # 30s when P0/P1 tasks are queued
        self.backoff_multiplier = 2
        self.max_cooldown = 1800      # 30 minute ceiling after repeated failures
        self.current_cooldown = self.base_cooldown
    
    def on_success(self, has_urgent_tasks: bool = False):
        self.current_cooldown = self.urgent_cooldown if has_urgent_tasks else self.base_cooldown
    
    def on_rate_limit(self):
        self.current_cooldown = min(
            self.current_cooldown * self.backoff_multiplier,
            self.max_cooldown
        )
    
    def on_timeout(self):
        # Task took too long — not a rate limit, don't backoff
        pass
```

### Session Timeout
Kill CC sessions that run longer than configurable timeout (default: 15 min).
Write timeout error to HANDOFF.md so next cycle knows what happened.

### Logging
Every cycle logs to `logs/cycles.jsonl`:
```json
{
  "cycle_id": 142,
  "timestamp": "2026-03-20T02:14:33Z",
  "task_id": "task_042",
  "priority": "P2",
  "duration_seconds": 187,
  "outcome": "completed",
  "deliverables": ["output/oubli_audit_2026-03-20.md"],
  "next_task": "sched_morning",
  "cooldown": 30
}
```

---

## 11. Build Plan (Suggested Phases)

### Phase 1 — Core Loop (Day 1)
- [ ] `daemon.py` with basic while-loop, INTERRUPT/QUEUE/BACKGROUND reading
- [ ] CLAUDE.md for main agent
- [ ] TASK_QUEUE.md with 3 seed tasks
- [ ] BACKGROUND.md with initial radiation tasks
- [ ] HANDOFF.md read/write protocol
- [ ] Basic logging

### Phase 2 — Subagent Delegation (Day 1-2)
- [ ] Subagent workspace creation and scoping
- [ ] Result file reading and deliverable routing
- [ ] Timeout handling and error recovery

### Phase 3 — Scheduled Tasks (Day 2)
- [ ] Cron-like scheduler in daemon (check time against P3 schedules)
- [ ] Morning brief subagent template
- [ ] Weekly digest subagent template

### Phase 4 — Telegram Bot (Day 2-3)
- [ ] Minimal dispatch bot (write to INTERRUPT.md / TASK_QUEUE.md)
- [ ] /status, /queue, /stop, /output commands
- [ ] File forwarding (send output/ files to Telegram)

### Phase 5 — Self-Evolution (Day 3+)
- [ ] Background radiation pruning logic (track which outputs get read)
- [ ] LEARNINGS.md auto-update
- [ ] Cycle analytics (which tasks produce value, which waste cycles)

---

## 12. Cloud Deployment (Hetzner VPS)

**Decision: Hetzner Cloud CX22, Helsinki datacenter, €3.79/month.**

CC is API-bound — all inference happens on Anthropic's servers. The VPS 
just holds a Python loop and the CC CLI process. 2 vCPUs, 4GB RAM, and 
40GB NVMe is more than enough. Helsinki gives lowest latency from Lund, 
EU GDPR compliance for Data Wealth AB, and 20TB included traffic.

### Initial provisioning (~30 minutes)

```bash
# 1. Provision CX22 at hetzner.com/cloud
#    - Location: Helsinki (hel1)
#    - OS: Ubuntu 24.04 LTS
#    - Add SSH public key during setup

# 2. SSH in and harden
ssh root@<ip>
adduser max && usermod -aG sudo max
sed -i 's/^PermitRootLogin yes/PermitRootLogin no/' /etc/ssh/sshd_config
sed -i 's/^#PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
systemctl restart sshd

# 3. Basic tooling
sudo apt update && sudo apt upgrade -y
sudo apt install -y tmux python3 python3-pip git ripgrep
pip3 install python-telegram-bot --break-system-packages

# 4. Install Tailscale (private networking, no exposed ports)
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
# Then lock down UFW to Tailscale only:
sudo ufw default deny incoming
sudo ufw allow in on tailscale0
sudo ufw enable

# 5. Install CC via native installer (auto-updates enabled)
curl -fsSL https://code.claude.com/install | sh
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.profile
source ~/.profile
claude /login   # One-time browser auth via SSH tunnel (see below)

# 6. Copy project and launch
scp -r ~/lobotomy max@<tailscale-ip>:~/lobotomy
ssh max@<tailscale-ip>
sudo systemctl enable --now lobotomy
```

### Systemd service (auto-restart on crash/reboot)

```ini
# /etc/systemd/system/lobotomy.service
[Unit]
Description=LOBOTOMY (CC autonomous loop)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=max
WorkingDirectory=/home/max/lobotomy
ExecStart=/usr/bin/python3 /home/max/lobotomy/daemon.py
Restart=always
RestartSec=60
Environment="PATH=/home/max/.local/bin:/usr/bin:/bin"

# Hardening
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/home/max
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

### Why not a Mac Mini?

A Mac Mini M4 costs ~€700+ upfront. It gives you Apple Silicon GPU 
(irrelevant — CC doesn't use local compute) and sits in your apartment 
drawing power and needing physical access for recovery. A €3.79/month 
VPS gives you: always-on with 99.9% uptime, no UPS/power concerns, 
instant recovery via Hetzner console, and you can delete/recreate it 
in 60 seconds if something goes wrong. Mac Mini only makes sense if 
you later want to run local models (Ollama + Hermes) alongside the 
daemon — but even then, a Hetzner GPU instance on-demand is cheaper 
than owning hardware you use intermittently.

---

## 13. Laptop Bridge: Read Access to Local Files

The daemon runs in the cloud, but your real work lives on your laptop — 
project repos, notes, bookmarks, downloads, the philosophical book draft. 
Giving the Lobster **read-only** access to your laptop when it's online 
unlocks a huge range of context-aware background tasks.

### Design principle: enriched vs. offline mode

The laptop won't always be reachable (lid closed, no wifi, VPN active). 
The daemon must handle this gracefully:

- **Enriched mode**: Laptop is online on Tailscale → daemon can read 
  files, scan repos, check local state. Background tasks that need 
  laptop context are eligible to run.
- **Offline mode**: Laptop unreachable → daemon runs only cloud-local 
  tasks (web research, output generation, queue management). Laptop-
  dependent tasks get deferred, not failed.

The daemon reads your files for context but can only write to dedicated 
sandbox directories under `/home/lobster/` on the laptop. It writes 
deliverables to its own `output/` directory on the VPS.

### Option A: SSH over Tailscale (recommended — simplest)

Since both devices are on the same Tailscale network, the VPS can 
SSH into the laptop directly. No mounts, no FUSE, no WebDAV. The 
CC subagent just runs `ssh` commands to read files on demand.

**Laptop setup — create a restricted read-only user (one-time):**
```bash
# Create a dedicated user that cannot write to your files
sudo useradd -m -s /bin/bash lobster
sudo usermod -aG max lobster  # Add to your group for read access

# Ensure your home files are group-readable but NOT group-writable
chmod -R g+rX,g-w ~/projects ~/notes ~/writing

# Make sensitive dirs invisible to the lobster user entirely
chmod 700 ~/.ssh ~/.gnupg ~/.aws ~/.config/anthropic

# Create writable sandbox directories owned by lobster
sudo mkdir -p /home/lobster/sandbox      # General scratch space
sudo mkdir -p /home/lobster/test-runs    # pytest / test output
sudo mkdir -p /home/lobster/snapshots    # File snapshots for VPS
sudo chown -R lobster:lobster /home/lobster/sandbox \
    /home/lobster/test-runs /home/lobster/snapshots

# Create the read-only gate script
sudo tee /home/lobster/read-only-gate.sh << 'GATE'
#!/bin/bash
# Only allows read-only commands from the VPS.
# This is the belt. The lobster user's filesystem permissions 
# are the suspenders. Both independently prevent writes.

CMD="$SSH_ORIGINAL_COMMAND"

# Writable sandbox paths (lobster-owned directories)
SANDBOX="/home/lobster/sandbox"
TESTRUNS="/home/lobster/test-runs"
SNAPSHOTS="/home/lobster/snapshots"

# Block command chaining everywhere — no exceptions
if echo "$CMD" | grep -qE '[;&|`]|\$\(' ; then
    echo "ERROR: command chaining not allowed" >&2
    exit 1
fi

# ALLOW: any command targeting writable sandbox dirs
if echo "$CMD" | grep -qE "^.* ($SANDBOX|$TESTRUNS|$SNAPSHOTS)"; then
    exec bash -c "$CMD"
fi

# ALLOW: read-only commands anywhere
ALLOWED='^(cat |ls |find |head |tail |wc |file |stat |rg |grep '
ALLOWED+='|tree |du |df |bat |git -C .* log|git -C .* status'
ALLOWED+='|git -C .* diff|python3 -m pytest )'

if echo "$CMD" | grep -qE "$ALLOWED"; then
    exec bash -c "$CMD"
else
    echo "ERROR: command not in read-only whitelist" >&2
    echo "Allowed: cat, ls, find, head, tail, wc, rg, grep, " >&2
    echo "         git log/status/diff, pytest, tree, du, df" >&2
    echo "Writable: $SANDBOX, $TESTRUNS, $SNAPSHOTS" >&2
    exit 1
fi
GATE
sudo chmod +x /home/lobster/read-only-gate.sh
sudo chown lobster:lobster /home/lobster/read-only-gate.sh
```

**VPS setup:**
```bash
# Generate a dedicated key for laptop access
ssh-keygen -t ed25519 -f ~/.ssh/laptop_key -N "" -C "lobotomy-daemon"

# Copy to laptop's lobster user (do this once while laptop is online)
ssh-copy-id -i ~/.ssh/laptop_key lobster@<laptop-tailscale-ip>

# On the laptop, restrict the key in lobster's authorized_keys:
# Edit /home/lobster/.ssh/authorized_keys to prefix the key with:
# command="/home/lobster/read-only-gate.sh",no-port-forwarding,
#   no-X11-forwarding,no-agent-forwarding,no-pty ssh-ed25519 AAAA...

# Test — should work:
ssh -i ~/.ssh/laptop_key lobster@maxs-laptop "cat /home/max/projects/oubli/README.md"

# Test — should be blocked:
ssh -i ~/.ssh/laptop_key lobster@maxs-laptop "rm /home/max/projects/oubli/README.md"
# → ERROR: command not in read-only whitelist
```

**How the daemon uses it:**
```python
import subprocess

class LaptopBridge:
    """Read-only access to laptop files over Tailscale SSH."""
    
    LAPTOP_HOST = "lobster@maxs-laptop"  # Restricted read-only user
    SSH_KEY = "/home/max/.ssh/laptop_key"
    SSH_OPTS = [
        "-i", SSH_KEY,
        "-o", "ConnectTimeout=5",
        "-o", "StrictHostKeyChecking=accept-new",
    ]
    
    def is_online(self) -> bool:
        """Check if laptop is reachable on Tailscale."""
        result = subprocess.run(
            ["tailscale", "ping", "-c", "1", "--timeout", "3s", 
             "maxs-laptop"],
            capture_output=True, timeout=5
        )
        return result.returncode == 0
    
    def read_file(self, remote_path: str) -> str | None:
        """Read a file from the laptop. Returns None if unavailable."""
        try:
            result = subprocess.run(
                ["ssh"] + self.SSH_OPTS + [self.LAPTOP_HOST, 
                 f"cat '{remote_path}'"],
                capture_output=True, text=True, timeout=15
            )
            return result.stdout if result.returncode == 0 else None
        except subprocess.TimeoutExpired:
            return None
    
    def list_dir(self, remote_path: str) -> list[str] | None:
        """List directory contents on the laptop."""
        try:
            result = subprocess.run(
                ["ssh"] + self.SSH_OPTS + [self.LAPTOP_HOST,
                 f"ls -la '{remote_path}'"],
                capture_output=True, text=True, timeout=10
            )
            return result.stdout.splitlines() if result.returncode == 0 else None
        except subprocess.TimeoutExpired:
            return None
    
    def find_recent(self, remote_path: str, days: int = 1, 
                     pattern: str = "*") -> list[str] | None:
        """Find recently modified files on laptop."""
        try:
            result = subprocess.run(
                ["ssh"] + self.SSH_OPTS + [self.LAPTOP_HOST,
                 f"find '{remote_path}' -name '{pattern}' "
                 f"-mtime -{days} -type f"],
                capture_output=True, text=True, timeout=30
            )
            return result.stdout.splitlines() if result.returncode == 0 else None
        except subprocess.TimeoutExpired:
            return None
    
    def search_content(self, remote_path: str, 
                        query: str) -> str | None:
        """Grep for content across laptop files (ripgrep)."""
        try:
            result = subprocess.run(
                ["ssh"] + self.SSH_OPTS + [self.LAPTOP_HOST,
                 f"rg --no-heading -l '{query}' '{remote_path}' "
                 f"2>/dev/null | head -20"],
                capture_output=True, text=True, timeout=30
            )
            return result.stdout if result.returncode == 0 else None
        except subprocess.TimeoutExpired:
            return None
```

### Option B: Taildrive (future — cleaner but alpha)

Tailscale has a built-in file sharing feature called Taildrive that 
exposes directories as WebDAV shares over your tailnet. Once it 
graduates from alpha, this would be cleaner than SSH:

```bash
# On the laptop — share specific directories read-only
tailscale drive share projects ~/projects
tailscale drive share notes ~/notes  
tailscale drive share book ~/writing/book

# On the VPS — access via WebDAV at 100.100.100.100:8080
curl http://100.100.100.100:8080/<tailnet>/maxs-laptop/projects/
```

ACL policy for read-only VPS access:
```json
{
  "grants": [{
    "src": ["tag:vps"],
    "dst": ["maxs-laptop"],
    "app": {
      "tailscale.com/cap/drive": [{ 
        "shares": ["*"], "access": "ro" 
      }]
    }
  }]
}
```

Taildrive is still alpha with known bugs (empty shares after reboot 
on some platforms, macOS App Store client issues). Stick with SSH 
for now, migrate to Taildrive when it stabilizes.

### What the daemon can do with laptop access

Once the bridge is live, these background radiation tasks unlock:

**Project awareness:**
- Scan `~/projects/*/CLAUDE.md` to understand active project contexts
- Check `git log --oneline -5` across repos for recent activity
- Find TODO/FIXME comments that have been sitting for >2 weeks
- Detect new dependencies added to requirements.txt/package.json

**Personal context:**
- Scan Downloads folder for unprocessed files
- Check `~/notes/` for new entries to incorporate into book research

**Morning brief enrichment:**
- Pull calendar exports from `~/.local/share/`
- Check if any local scripts/cron jobs have been failing
- Report on disk space, large files, stale Docker images

**On-demand from phone:**
```
Max via Telegram: "Lobster, check my Oubli repo — what's the 
current test coverage and are there any failing tests?"

→ Daemon SSHes into laptop
→ Copies Oubli to /home/lobster/test-runs/oubli-<timestamp>
→ Runs pytest with coverage in the sandbox copy (full write access)
→ Reads results, writes summary to output/ on VPS
→ Sends summary back via Telegram
→ Cleans up sandbox copy
```

### Security: three independent layers of write protection

The daemon **cannot** modify your project files, notes, or personal 
data. It CAN write to three dedicated sandbox directories under 
`/home/lobster/` that it owns. This is enforced at the OS level.

**Layer 1 — Filesystem permissions (suspenders):**
The `lobster` user on the laptop is a separate OS user added to your 
group. `chmod g+rX,g-w` means the user can read and traverse your 
directories but physically cannot write, rename, or delete any file 
outside its own home. It has three writable directories:
- `/home/lobster/sandbox/` — general scratch space (temp files, 
  experiments, intermediate results)
- `/home/lobster/test-runs/` — pytest output, coverage reports, 
  test artifacts
- `/home/lobster/snapshots/` — file snapshots prepared for the VPS 
  (e.g. bundled project state for offline analysis)

**Layer 2 — authorized_keys command restriction (belt):**
The SSH key is locked to `/home/lobster/read-only-gate.sh` via the 
`command=` prefix in `authorized_keys`. The gate script has two modes:
- **Read-only** (your files): only `cat`, `ls`, `find`, `rg`, `grep`, 
  `git log/status/diff`, `pytest`, `tree`, `du`, `df` are allowed
- **Read-write** (sandbox dirs): any command targeting the three 
  writable paths is allowed
- **Everywhere**: command chaining (`; && | backticks $()`) is blocked 
  before any command executes

**Layer 3 — Sensitive directory exclusion (paranoia):**
`~/.ssh`, `~/.gnupg`, `~/.aws`, `~/.config/anthropic` are set to 
`chmod 700` — invisible to the `lobster` user entirely. Even read 
access to credentials is impossible.

**What the sandbox enables:**
```bash
# Copy a project to test-runs, run pytest there (writes cache/results freely)
ssh lobster@maxs-laptop "cp -r /home/max/projects/oubli /home/lobster/test-runs/oubli-run-001"
ssh lobster@maxs-laptop "cd /home/lobster/test-runs/oubli-run-001 && python3 -m pytest --tb=short --cov=oubli"

# Write a summary file the VPS can fetch later
ssh lobster@maxs-laptop "cat /home/lobster/test-runs/oubli-run-001/coverage.txt"

# Bundle a snapshot of project state for offline VPS analysis
ssh lobster@maxs-laptop "tar czf /home/lobster/snapshots/oubli-$(date +%Y%m%d).tar.gz -C /home/max/projects oubli"
```

**Worst-case analysis:**
- If the gate is bypassed: filesystem permissions still prevent writes 
  to your files (only sandbox dirs are writable)
- If permissions are misconfigured on one dir: the gate blocks write 
  commands targeting anything outside the sandbox
- If both fail: attacker gets read access to project files, but can 
  only write to `/home/lobster/` — your repos, notes, and config 
  remain untouched
- Credentials in Layer 3 directories remain invisible regardless
- Sandbox dirs can be wiped anytime: `rm -rf /home/lobster/{sandbox,test-runs,snapshots}/*`

### Integration with daemon cycle

```python
# In the main daemon loop, check laptop status once per cycle
laptop = LaptopBridge()

if laptop.is_online():
    # Enriched mode — laptop-dependent background tasks eligible
    handoff["laptop_online"] = True
    handoff["laptop_last_seen"] = datetime.now().isoformat()
else:
    # Offline mode — skip laptop-dependent tasks
    handoff["laptop_online"] = False
    # Don't log this as an error — it's expected
```

---

## 14. Authentication: The Hard Problem

### The reality

CC uses OAuth tokens that expire. This is the single biggest threat 
to a fully autonomous daemon. Known failure modes:

- **Inactivity expiry**: Tokens expire after ~24h of inactivity on 
  some accounts (varies, not officially documented)
- **Periodic expiry**: Some users report forced re-auth multiple 
  times per day, even during active use
- **Anthropic outages**: OAuth endpoint failures (March 2 and 
  March 11, 2026 incidents took down auth for hours)
- **Refresh token bugs**: CC has had issues where stored refresh 
  tokens aren't actually used for refresh (known bug, partially fixed)

### Why it's manageable for our architecture

Unlike an interactive CC session that dies mid-task when auth expires, 
our daemon launches **short-lived `claude -p` processes**. Each process 
runs for 1-15 minutes, then exits. The auth token persists in 
`~/.claude.json` between invocations. So we're not fighting session 
timeout — we're fighting periodic token expiry.

This means the daemon can:
1. Detect auth failure via CC exit code or stderr parsing
2. Immediately pause the loop
3. Alert via Telegram
4. Wait for re-auth
5. Resume automatically once auth is restored

### Auth failure handling in daemon.py

```python
import subprocess
import re

class AuthManager:
    """Detect and handle CC authentication failures."""
    
    AUTH_ERROR_PATTERNS = [
        "OAuth token has expired",
        "authentication_error",
        "401",
        "Please obtain a new token",
        "token expired",
        "/login",
    ]
    
    def __init__(self, telegram_bot=None):
        self.is_auth_valid = True
        self.telegram_bot = telegram_bot
        self.last_alert_time = 0
    
    def run_cc_task(self, prompt: str, workdir: str, timeout: int = 900) -> dict:
        """Run a CC task and detect auth failures."""
        try:
            result = subprocess.run(
                ["claude", "-p", prompt, "--allowedTools", 
                 "Edit,Bash,Read,Write"],
                capture_output=True, text=True, timeout=timeout,
                cwd=workdir
            )
            
            # Check for auth errors in stderr or stdout
            combined_output = result.stderr + result.stdout
            for pattern in self.AUTH_ERROR_PATTERNS:
                if pattern.lower() in combined_output.lower():
                    self.handle_auth_failure(combined_output)
                    return {"status": "auth_failure", "output": combined_output}
            
            if result.returncode != 0:
                return {"status": "error", "output": combined_output, 
                        "code": result.returncode}
            
            self.is_auth_valid = True
            return {"status": "success", "output": result.stdout}
            
        except subprocess.TimeoutExpired:
            return {"status": "timeout", "output": ""}
    
    def handle_auth_failure(self, error_output: str):
        """Pause daemon and alert user."""
        self.is_auth_valid = False
        
        if self.telegram_bot:
            self.telegram_bot.send_alert(
                "🔐 *Auth expired* — daemon paused.\n\n"
                "To fix:\n"
                "1. `ssh max@<tailscale-ip>`\n"
                "2. `claude /login`\n"
                "3. Complete browser auth\n"
                "4. Daemon resumes automatically."
            )
    
    def wait_for_auth_restoration(self, check_interval: int = 300):
        """Block until auth is restored. Check every 5 minutes."""
        import time
        while not self.is_auth_valid:
            # Try a minimal CC call to test auth
            test = subprocess.run(
                ["claude", "-p", "respond with OK", "--max-tokens", "10"],
                capture_output=True, text=True, timeout=30
            )
            if test.returncode == 0 and "OK" in test.stdout:
                self.is_auth_valid = True
                if self.telegram_bot:
                    self.telegram_bot.send_alert(
                        "✅ *Auth restored* — daemon resuming."
                    )
                return
            time.sleep(check_interval)
```

### Re-login on a headless VPS

When auth expires, you need a browser to complete OAuth. Two approaches:

**Option A: SSH tunnel + local browser (recommended)**
```bash
# From your laptop — forward the OAuth callback port
ssh -L 7776:localhost:7776 max@<tailscale-ip>

# On the VPS, in the SSH session
claude /login
# Copy the URL it gives you, open in your local browser
# The OAuth callback hits localhost:7776 which tunnels to the VPS
```

**Option B: SSH from phone via Termux/Blink + Tailscale**
```bash
# From phone terminal app
ssh max@<tailscale-ip>
claude /login
# Open the auth URL in phone browser
```

### Reducing re-auth frequency

Based on community reports, the following helps:
- **Keep the token active**: The daemon itself prevents inactivity 
  expiry since it runs CC every 5 to 30 minutes
- **Use the `stable` release channel**: Fewer updates = fewer 
  moments where the binary restarts and triggers re-auth
- **Don't run concurrent sessions**: Multiple CC processes with the 
  same OAuth token can cause token invalidation races
- **Monitor `~/.claude.json`**: If the file gets corrupted or 
  truncated, auth dies. The daemon should checksum it periodically.

### Fallback: API key mode

If OAuth proves too unreliable for 24/7 operation, the nuclear option 
is to switch from Max subscription to API billing for the daemon only, 
using `ANTHROPIC_API_KEY` instead of OAuth. This eliminates token expiry 
entirely but introduces per-token cost. A hybrid approach:
- Use Max subscription OAuth for daytime interactive work
- Switch the daemon to API key billing only if OAuth breaks >2x/week
- Budget ~$30-50/month for daemon API costs as insurance

This is a last resort. Try OAuth-based operation first — the daemon's 
short-lived process pattern should keep the token warm.

---

## 15. Auto-Updates

### CC updates itself — no cron needed

The native CC installer handles updates automatically. It checks for 
new versions on startup and periodically during execution. Updates 
download in background and apply on the next launch. Since the daemon 
launches a fresh `claude -p` process every cycle, updates apply 
naturally between cycles with zero intervention.

### Recommended configuration

```bash
# On the VPS, set CC to stable channel (1 week behind latest)
# This avoids being hit by regressions in bleeding-edge releases
claude /config
# → Set "Auto-update channel" to "stable"
```

The `stable` channel runs roughly one week behind `latest`, which 
means regressions (like the v2.0.30 subagent bug) get caught before 
they hit your daemon.

### Daily health check (add to daemon.py)

Even though CC auto-updates, the daemon should verify system health 
once per day:

```python
import subprocess
import time
from datetime import datetime, timedelta

class HealthChecker:
    """Daily system health verification."""
    
    def __init__(self):
        self.last_health_check = None
    
    def should_run(self) -> bool:
        if self.last_health_check is None:
            return True
        return datetime.now() - self.last_health_check > timedelta(hours=24)
    
    def run_health_check(self) -> dict:
        """Run once per day between cycles."""
        self.last_health_check = datetime.now()
        report = {}
        
        # 1. CC version and auto-update status
        version_check = subprocess.run(
            ["claude", "--version"], 
            capture_output=True, text=True, timeout=10
        )
        report["cc_version"] = version_check.stdout.strip()
        
        # 2. Disk space
        disk_check = subprocess.run(
            ["df", "-h", "/home/max"],
            capture_output=True, text=True
        )
        report["disk"] = disk_check.stdout
        
        # 3. Auth token file integrity
        import os, hashlib
        claude_json = os.path.expanduser("~/.claude.json")
        if os.path.exists(claude_json):
            size = os.path.getsize(claude_json)
            report["auth_file_size"] = size
            report["auth_file_ok"] = size > 50  # Corrupt if near-empty
        else:
            report["auth_file_ok"] = False
        
        # 4. System updates (don't auto-install, just flag)
        apt_check = subprocess.run(
            ["apt", "list", "--upgradable"],
            capture_output=True, text=True
        )
        upgradable = len(apt_check.stdout.strip().split("\n")) - 1
        report["system_updates_available"] = max(0, upgradable)
        
        # 5. Daemon cycle stats (last 24h)
        report["timestamp"] = datetime.now().isoformat()
        
        return report
```

### System package updates (weekly, automated)

For the underlying Ubuntu system, enable unattended security updates:

```bash
sudo apt install -y unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades
# Select "Yes" — installs security patches automatically
```

This keeps the OS patched without touching CC or the daemon.

---

## 16. Open Questions

Resolved: deployment (Hetzner CX22 Helsinki), laptop access (SSH 
over Tailscale with lobster user), auto-updates (CC native).

Remaining:

1. **Subagent parallelism**: Can Max subscription handle 2 concurrent CC 
   sessions? Need to test. If not, strictly sequential with queue.

2. **Calendar/email access**: Morning brief needs calendar data. Options:
   a. Export .ics file on cron from laptop → VPS reads it
   b. Google Calendar API via curl
   c. Manual sync (low-tech but reliable)

3. **Web access in headless mode**: CC's web search tool may not work 
   in `claude -p` mode. Fallback: subagent uses `curl` + API scripts 
   for arxiv, HN, weather, market data.

4. **Oubli integration**: Should the daemon's memory/ directory eventually 
   feed into Oubli's graph? Natural synergy — the daemon generates context 
   that Oubli could persist across CC sessions.

5. **OAuth reliability baseline**: After first week of operation, measure 
   actual re-auth frequency. If >2x/week, evaluate API key fallback. 
   Track in `logs/auth_events.jsonl`.

6. **Max subscription tier**: At 5-minute cycles with background 
   radiation, Max5 ($100/month) may be sufficient. Monitor for 
   throttling. Max20 ($200/month) if sustained load is needed.
