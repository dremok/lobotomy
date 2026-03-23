# LOBOTOMY

### **L**ocal **O**rchestration **B**ot with **O**vernight **T**ask **O**ptimization and **M**emory for **Y**ou

> *LOBster + auTOnoMY = LOBOTOMY*
>
> Surgically remove the cognitive load of remembering, triaging, monitoring, and scheduling from your brain. Offload it to a daemon that never sleeps.

---

**LOBOTOMY** is a lightweight Python daemon that turns [Claude Code](https://code.claude.com) into an always-on personal research agent. It runs on a VPS, uses your flat-rate Claude Max subscription, and gets smarter about what's useful to you over time.

It is **not** a task runner. It is a *digital familiar*.

```
Week 1:   A cron job with an LLM brain.
Month 1:  A research assistant that knows your projects and blind spots.
Month 6:  A self-evolving agent that has rewritten its own task list
          dozens of times based on what you actually read and act on.
```

---

## Why

You already use Claude Code interactively, in your terminal, scoped to specific repos, for focused work. That doesn't change.

LOBOTOMY fills a different niche: **ambient, cross-cutting intelligence** that runs while you sleep, learns what matters to you, and surfaces things you'd otherwise miss. Morning briefs. Dependency audits. Paper radar. Portfolio alerts. Repo health checks. And a self-evolving "background radiation" of tasks that prunes what you ignore and amplifies what you act on.

The only genuinely novel idea in OpenClaw is the autonomous loop: heartbeats, self-prompting, 24/7 availability. Everything else is the LLM doing the work underneath. LOBOTOMY extracts that one good idea and builds it natively on Claude Code, giving you:

- **Zero marginal cost**: runs on your Max subscription, not per-token API billing
- **Full CC capability**: not limited to a skill abstraction layer
- **Security by design**: no 20-platform gateway, no supply chain risk
- **Ownership of every layer**: debuggable, extensible, yours

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│               PHONE / REMOTE                     │
│        Telegram bot → task dispatch               │
└────────────────────┬────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────┐
│           ORCHESTRATOR DAEMON (Python)            │
│                                                   │
│  while True:                                      │
│    1. Check INTERRUPT.md    → P0 (user override)  │
│    2. Build cycle prompt with current time         │
│    3. Launch CC agent: claude -p "<prompt>"        │
│    4. Wait for exit                               │
│    5. Parse result (auth? rate limit? success?)    │
│    6. Log cycle, adaptive cooldown, repeat        │
│                                                   │
│  Rate limit aware · Auth failure detection        │
│  Laptop bridge (read-only) · Health checks        │
└────────────────────┬────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────┐
│              CC AGENT (one session)               │
│                                                   │
│  Identity: SOUL.md (immutable)                    │
│  Instructions: CLAUDE.md (self-evolving)          │
│                                                   │
│  Reads: queue files, handoff, background          │
│  Does: one unit of work per cycle                 │
│  Writes: deliverables to output/, HANDOFF.md      │
│  Evolves: CLAUDE.md, BACKGROUND.md, LEARNINGS.md  │
│  Then: exits                                      │
└─────────────────────────────────────────────────┘
```

---

## Identity Architecture

The agent's behavior is governed by three layers, each with different
rates of change:

| Layer | File | Changes | Purpose |
|-------|------|---------|---------|
| **Soul** | `SOUL.md` | Never | Core identity, values, personality, communication style. Who the agent *is*. |
| **Instructions** | `CLAUDE.md` | Slowly | Cycle protocol, rules, project list. How the agent *works*. The agent may refine this over time. |
| **Radiation** | `queue/BACKGROUND.md` | Constantly | What the agent does when idle. Self-evolves every ~10 cycles based on what produces value. |

SOUL.md is the one file the agent never modifies. It is the fixed point
that all evolution orbits around. CLAUDE.md and BACKGROUND.md are living
documents the agent rewrites as it learns. HANDOFF.md and LEARNINGS.md
accumulate context across cycles.

---

## The Backronym, Explained

| Letter | Word | What it does |
|--------|------|-------------|
| **L** | **Local** | Runs on your own infrastructure. Your data never touches third-party agent platforms. |
| **O** | **Orchestration** | The daemon loop: dispatches work, manages priority, handles auth failures, adaptive cooldown. |
| **B** | **Bot** | An autonomous agent, not a chat interface. It acts on its own, checks in with you, and learns over time. |
| **O** | **Overnight** | Designed for ambient, always-on operation. Does its best work while you sleep. |
| **T** | **Task** | Priority queue from P0 (user interrupt) to P4 (background radiation). The agent picks what matters most each cycle. |
| **O** | **Optimization** | Self-evolution loop: every 10 cycles, evaluates which outputs you read, prunes the useless, amplifies the valuable. |
| **M** | **Memory** | HANDOFF.md bridges cycles. LEARNINGS.md accumulates patterns. BACKGROUND.md self-evolves. Context persists. |
| **Y** | for **You** | Becomes *yours* over time through iterated experimentation with what generates value. |

---

## Features

### Self-Evolving Background Radiation
The core product. A `BACKGROUND.md` file seeded with useful tasks: arxiv scans, dependency audits, portfolio monitoring, repo health checks. Every 10 cycles, the agent evaluates which outputs were read and acted on. Tasks that produce value get amplified. Tasks you ignore get pruned. Over time, the file rewrites itself into something uniquely tuned to you.

### Priority-Based Task Queue
Five priority levels from P0 (phone interrupt) to P4 (background radiation). Time-sensitive tasks auto-promote. The agent reads all sources each cycle and picks the highest-value work.

### Phone Steering via Telegram
Dispatch tasks from your phone. Check status. Read outputs. Pause or redirect the daemon. The bot writes to files that the daemon picks up.

### Laptop Bridge (Read-Only)
The daemon can SSH into your laptop over Tailscale when it's online. Read project files, scan repos, check git status, run tests in a sandboxed copy. A dedicated `lobster` OS user with filesystem-level write protection ensures it can never modify your files.

### Scheduled Deliverables
Cron-like triggers for recurring outputs: morning briefs, weekly digests, portfolio reports, research radars, kid activity planners. All written to `output/` and optionally pushed to Telegram.

### Auth Resilience
CC's OAuth tokens expire. The daemon detects auth failures, pauses gracefully, alerts you via Telegram, and auto-resumes when you re-authenticate. Adaptive backoff prevents rate limit issues.

---

## Requirements

- **Claude Max subscription** ($100-200/month)
- **Claude Code CLI** with auto-updates
- **VPS**: Hetzner CX22 recommended (2 vCPU, 4GB RAM, 40GB NVMe). Any Linux box works.
- **Tailscale**: private networking between VPS, laptop, and phone
- **Python 3.10+** with `pyyaml`
- **Telegram bot token** (optional but recommended)

---

## Quick Start

```bash
# 1. Clone
git clone https://github.com/maxleander/lobotomy.git
cd lobotomy

# 2. Configure
cp config.example.yaml config.yaml
# Edit: set your Telegram token, laptop hostname, etc.

# 3. Seed your tasks
# Edit queue/BACKGROUND.md with your interests
# Add initial tasks to queue/TASK_QUEUE.md

# 4. Test locally (single cycle)
python3 daemon.py --once

# 5. Deploy to VPS
scp -r . max@<vps-tailscale-ip>:~/lobotomy
ssh max@<vps-tailscale-ip>
sudo cp lobotomy.service /etc/systemd/system/
sudo systemctl enable --now lobotomy

# 6. Watch it think
journalctl -u lobotomy -f
```

---

## Project Structure

```
lobotomy/
├── daemon.py                 # Orchestrator loop (the only moving part)
├── bot.py                    # Telegram bot (runs separately)
├── config.example.yaml       # Configuration template
├── lobotomy.service          # systemd unit file
│
├── SOUL.md                   # Agent identity (IMMUTABLE)
├── CLAUDE.md                 # Agent instructions (self-evolving)
│
├── queue/
│   ├── TASK_QUEUE.md         # Priority-ordered backlog
│   ├── INTERRUPT.md          # Phone-dispatched P0 tasks (ephemeral)
│   ├── HANDOFF.md            # Context bridge between cycles
│   └── BACKGROUND.md         # Self-evolving radiation tasks
│
├── output/                   # Deliverables (briefs, reports, research)
├── workspaces/               # Scratch space for complex tasks
├── logs/                     # Cycle logs, health checks
│
├── memory/
│   ├── LEARNINGS.md          # Patterns about what's useful
│   └── PROJECT_REGISTRY.md   # Active projects and status
│
└── LOBOTOMY_SPEC.md          # Full specification
```

---

## Philosophy

> *A lobotomy historically severed the prefrontal cortex, the part of
> the brain responsible for planning, prioritizing, worrying, and
> executive oversight. LOBOTOMY does the same to your workflow. The
> anxiety of "am I forgetting something?" gets surgically excised and
> offloaded to a daemon that never sleeps.*

This project exists at the intersection of two ideas:

1. **The only good idea in OpenClaw** is the autonomous loop. Everything else (reasoning, tool use, code execution) is the underlying LLM. LOBOTOMY extracts the loop and builds it on Claude Code, which is better at all of those things.

2. **The most valuable AI agent isn't the one that executes fastest**; it's the one that learns what's useful to *you* over time. LOBOTOMY's self-evolution loop is the core product. The task runner is a side effect. Nothing in LOBOTOMY is static. Everything evolves. The task queue, the background radiation, the project list, even the agent's own instructions. A LOBOTOMY that looks the same after a month as it did on day one has failed.

Except SOUL.md. That stays.

---

## Status

**Pre-alpha.** The daemon runs. The spec is done. Self-evolution has not been tested at scale.

---

## License

MIT

---

<sub>Named after the surgical procedure, the crustacean, and the autonomy. Not necessarily in that order.</sub>
