# CLAUDE.md

## Environment

You are running in a **dev container** with full autonomous permissions.
This is an isolated development environment where you can safely:
- Install packages (npm, pip, apt-get)
- Create, modify, delete files
- Run shell commands
- Make network requests
- Use git operations

## Agent Protocol Harness MCP

You have access to the **agent-protocol-harness** MCP server for smart task guidance and optional multi-agent orchestration.

### Getting Started

**Always call `get_task_guidance` first** for any coding task. It provides:
- **Complexity assessment** - simple vs complex
- **Recommended approach** - direct vs orchestrated
- **Scope suggestions** - which files to focus on
- **Verification steps** - how to test your changes
- **Potential pitfalls** - things to watch out for

For simple tasks, `get_task_guidance` returns guidance and stays dormant (minimal overhead).
For complex tasks, it recommends the orchestration workflow below.

### Quick Workflow

```
Simple task:
1. get_task_guidance  → Returns guidance, stay dormant
2. [do the work directly]
3. Verify as suggested

Complex task (when recommended):
1. get_task_guidance  → Recommends orchestration
2. check_session      → Resume existing or start fresh
3. analyze_and_plan   → Propose agents + verification
4. approve_plan       → Creates feature branch
5. execute_next_agent → Runs with full Claude powers
6. run_verification   → Automated + manual checks
7. finalize_session   → Merge, keep, or discard
```

### When Orchestration is Recommended

The MCP will suggest orchestration when the task:
- Spans multiple systems (frontend + backend + database)
- Would exceed 500 lines of changes
- Has natural boundaries (different languages, frameworks)
- Requires isolated verification per component

### Key Behaviors

**Session Persistence**: State survives context exhaustion. If you run out of context, the next session can resume exactly where you left off via `check_session`.

**Verification First**: When you call `analyze_and_plan`, verification plans are auto-generated. Present BOTH the execution plan AND verification plan to the user for approval.

**Full-Power Sub-Agents**: Sub-agents run as complete Claude Code sessions with `--dangerously-skip-permissions`. They can install packages, search the web, use MCP tools—everything you can do.

**Error Auto-Resolution**: When agents fail, use `handle_error` before asking the user. It will auto-install missing packages and fix common issues.

**Git Branching**: All work happens on `ai/session-*` branches with checkpoint commits after each agent. User decides whether to merge at the end.

### Example Interaction

```
User: Add authentication with JWT to my app

You: [call check_session]
     No existing session.

     [call analyze_and_plan with task + proposed agents]

     I've created a plan for adding JWT authentication:

     **Execution Plan**
     1. database → Create User/Session tables
     2. backend → JWT endpoints + middleware
     3. frontend → Login/Register UI

     **Verification Plan**
     - database: `npx prisma migrate status` exits 0
     - backend: `npm test --grep auth` passes
     - frontend: `npm run test:frontend` passes
     - Manual: Test login flow end-to-end

     Does this look right, or would you like to adjust?

User: Looks good, proceed

You: [call approve_plan]
     Created branch `ai/session-20240115-143052`

     [call execute_next_agent]
     Running database agent...
     ✓ Created migrations
     ✓ Verification passed
     📌 Commit: a1b2c3d

     [call execute_next_agent]
     Running backend agent...
     ...
```

### Contract Principles

When designing agent contracts:

- **SCOPE**: What files/directories the agent should focus on
- **PRODUCES**: Concrete outputs (files, endpoints, tables)
- **DEPENDS**: Which agents must complete first (signals)
- **VERIFY**: Commands that prove success

Contracts are **guidance**, not restrictions. Sub-agents have full capabilities but are told what to focus on.

## General Guidelines

### Code Style
- Follow existing patterns in the codebase
- Prefer explicit over implicit
- Write tests for new functionality
- Use TypeScript/type hints where applicable

### Git
- Don't commit directly to main during multi-agent sessions
- Agent-protocol-harness handles branching automatically
- Checkpoint commits use format: `checkpoint: {agent} complete`

### Communication
- Present plans before executing
- Show verification results clearly
- Ask for feedback after each major step
- Summarize what was accomplished at the end

## Commands Reference

Quick reference for agent-protocol-harness tools:

| Tool | Purpose |
|------|---------|
| `get_task_guidance` | **Call first for every task** - get smart guidance |
| `check_session` | Resume existing orchestration session |
| `analyze_and_plan` | Create multi-agent plan with verification |
| `modify_plan` | Adjust plan based on feedback |
| `approve_plan` | Create branch, ready to execute |
| `execute_next_agent` | Run next agent |
| `get_execution_status` | Check progress |
| `run_verification` | Run checks for an agent |
| `confirm_manual_check` | User confirms manual verification |
| `handle_error` | Analyze and auto-fix errors |
| `provide_feedback` | User feedback, trigger retry |
| `finalize_session` | Merge, keep, or discard |

## Passive Resources

The MCP also provides passive context (no tool call required):

| Resource | Content |
|----------|---------|
| `agent://context/codebase-summary` | Auto-detected project structure |
| `agent://context/task-complexity` | Complexity assessment |
| `agent://context/scope-suggestions` | File boundary suggestions |
