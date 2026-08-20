# 🧞 minions — Personal One-Shot, End-to-End Coding Agents

**[日本語](README.md)** | English

A personal-scale, **unattended one-shot coding agent** platform built on [goose](https://github.com/block/goose),
inspired by [Stripe's Minions blog series](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents)
([Part 2](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents-part-2)).

Give it a task and it runs **isolated in a worktree → goose implements → lint/test auto-fix → commit → push → CI (max 2 rounds) → PR creation** — no human interaction required.

## Architecture (Stripe Minions → personal edition)

| Stripe concept | This implementation |
|---|---|
| Minion (unattended one-shot agent) | `minion run "task"` |
| Fork of goose (agent core) | **goose 1.46, as-is** (`goose run --no-session`) |
| Blueprint (state machine of deterministic + agent nodes) | state machine in `lib/minions/blueprint.py` |
| Devbox (isolated, parallel dev environment) | **git worktrees** (`~/.minion/worktrees/`) |
| Agent rule files (shared with Cursor/CLAUDE.md) | `AGENTS.md` + `CLAUDE.md` symlink (`minion init`) |
| Conditional rules scoped to subdirectories | hydrate node collects subdirectory `AGENTS.md` files |
| Toolshed (central MCP, curated tools) | goose MCP config + `goose_args` in `.minion.yaml` |
| Shift-left feedback (local lint → max 2 CI rounds) | lint auto-fix ≤3 loops → tests → agent fix ≤2 → CI ≤2 rounds |

## Blueprint (state machine)

```
setup ── hydrate ──▶ implement ──▶ lint(auto-fix ≤3) ──▶ test ──┐
(det.)   (det.)      (AGENT)        (det.)              (det.)  │ fail
                                                                  ▼
done ◀─ pr ◀─ ci(≤2 rounds) ◀─ push ◀─ commit ◀── tests pass ◀── fix_tests (AGENT)
       (det.)  ▲                                      (det.)            │ fail
               │             fix_ci (AGENT) ◀────── CI failed ◀────────┘
```

- **AGENT nodes**: goose gets broad latitude (implementation, failure repair)
- **Deterministic nodes**: git ops, lint, tests, push, PR never touch an LLM
  → Stripe's lesson: "Determinable, small decisions are best made deterministically in code" —
  saving tokens and CI while shrinking the space where the agent can go wrong.

## Setup (already done on this machine)

```bash
# Requirements: goose, git, gh (optional), python3 — check with `minion doctor`
ln -sf ~/dev/minions/bin/minion ~/.local/bin/minion   # already on PATH
```

## Usage

### 1. Initialize a target repository (once)

```bash
cd ~/dev/your-repo
minion init
# → generates AGENTS.md (rule file), CLAUDE.md (symlink), .minion.yaml (auto-detected)
#   Write your conventions in AGENTS.md, then COMMIT it
#   (worktrees are created from HEAD)
```

### 2. One-shot run

```bash
minion run "add rate limiting to the login API, with tests"
# Parallelize (the Stripe way: many minions at once)
minion run -d "task A" &
minion run -d "task B" &
minion list
```

### 3. Observe & inspect

```bash
minion list                # all runs
minion log -f              # tail the latest run's transcript
minion show <run_id>       # timeline + status
minion dashboard           # → http://localhost:8765 (Web UI, 5s auto-refresh)
minion clean               # remove worktrees of finished runs
```

### 4. PR

If the remote is GitHub, `gh pr create` runs automatically (base = `pr_base` in `.minion.yaml`).
The PR body is the agent-written `summary.md`. Humans only review.

## `.minion.yaml` reference

```yaml
lint:
  fix: ["ruff check --fix .", "ruff format ."]  # auto-fixes run by the deterministic node
  check: ["ruff check ."]                        # check-only lints
test: "python3 -m pytest -q"                     # local tests
ci: "python3 -m pytest -q"                       # CI equivalent (falls back to test)
pr_base: "main"                                  # PR base branch
goose_args: ["--with-builtin", "developer"]      # extra args for goose (curate the "smaller box")
```

## Rule files (Stripe's context engineering)

- The root `AGENTS.md` is read **unconditionally** → keep it minimal
- Put detailed conventions in **subdirectory `AGENTS.md` files** (e.g. `services/api/AGENTS.md`)
  → the hydrate node collects them and marks them "READ FIRST" in the implementation prompt
- `CLAUDE.md` is a symlink, so goose / Claude Code / (if synced) Cursor all share **the same rules**

## MCP (Toolshed equivalent)

Uses goose's MCP support as-is:

```bash
goose configure   # add MCP servers (GitHub, Linear, Notion, ...)
```

`goose_args` in `.minion.yaml` can also restrict tools per run
(Stripe's lesson: "agents work best with a curated, smaller box of tools").

## Repository layout

```
~/dev/minions/
├── bin/minion              # CLI entry
├── lib/minions/
│   ├── core.py             # run state, config detection, git helpers
│   ├── blueprint.py        # state machine (deterministic/AGENT nodes)
│   ├── cli.py              # init/run/list/log/show/clean/doctor
│   └── dashboard.py        # local Web UI
├── templates/AGENTS.md     # rule file template
└── README.md
~/.minion/
├── runs/<run_id>/          # status.json, transcript.log, summary.md, changes.patch
└── worktrees/<repo>-<id>/  # isolated workspace (1 task = 1 worktree)
```

## References

- [Minions: Stripe's one-shot, end-to-end coding agents — Part 1](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents)
- [Part 2 (Blueprint, Devbox, Toolshed, the 2-CI-round policy)](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents-part-2)
- [goose (Block)](https://github.com/block/goose) — the same foundation Stripe forked
