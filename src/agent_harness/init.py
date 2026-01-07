"""
Initialize agent-protocol-harness in a project.

Usage:
  aph-init              # Initialize in current directory
  aph-init /path/to/project
"""

import shutil
from pathlib import Path

# Bundled CLAUDE.md content
CLAUDE_MD_CONTENT = '''# CLAUDE.md

## Environment

You are running in a **dev container** with full autonomous permissions.
This is an isolated development environment where you can safely:
- Install packages (npm, pip, apt-get)
- Create, modify, delete files
- Run shell commands
- Make network requests
- Use git operations

## Agent Protocol Harness MCP

You have access to the **agent-protocol-harness** MCP server for multi-agent orchestration.

### When to Use Multi-Agent

Use agent-protocol-harness when the task:
- Spans multiple systems (frontend + backend + database)
- Would exceed 500 lines of changes
- Has natural boundaries (different languages, frameworks, or concerns)
- Benefits from parallel work streams
- Requires isolated verification per component

Do NOT use agent-protocol-harness for:
- Simple single-file changes
- Tasks contained within one system
- Quick fixes or small features
- Questions or explanations

### Workflow

**Always start with `check_session`** to see if there's an interrupted session to resume.

```
1. check_session          → Resume existing or start fresh
2. analyze_and_plan       → Propose agents + auto-generate verification
3. [user reviews]         → Modify if needed
4. approve_plan           → Creates feature branch
5. execute_next_agent     → Runs with full Claude Code powers
6. run_verification       → Automated + manual checks
7. [iterate on feedback]  → Retry/adjust as needed
8. finalize_session       → Merge, keep branch, or discard
```

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
- Don\'t commit directly to main during multi-agent sessions
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
| `check_session` | **Call first** - resume or start fresh |
| `analyze_and_plan` | Create plan with verification |
| `modify_plan` | Adjust based on feedback |
| `approve_plan` | Create branch, ready to execute |
| `execute_next_agent` | Run next agent |
| `get_execution_status` | Check progress |
| `run_verification` | Run checks for an agent |
| `confirm_manual_check` | User confirms manual verification |
| `handle_error` | Analyze and auto-fix errors |
| `provide_feedback` | User feedback, trigger retry |
| `finalize_session` | Merge, keep, or discard |
'''

MCP_JSON_CONTENT = '''{
  "mcpServers": {
    "agent-protocol-harness": {
      "command": "agent-protocol-harness-mcp",
      "args": []
    }
  }
}
'''


def init_project(target_dir: Path) -> dict:
    """
    Initialize agent-protocol-harness in a project.

    Creates:
    - CLAUDE.md with agent-protocol-harness instructions
    - .mcp.json for Claude Code auto-discovery

    Returns dict with created files and any warnings.
    """
    target_dir = Path(target_dir).resolve()
    results = {"created": [], "skipped": [], "warnings": []}

    # Create CLAUDE.md
    claude_md = target_dir / "CLAUDE.md"
    if claude_md.exists():
        results["skipped"].append(str(claude_md))
        results["warnings"].append(f"CLAUDE.md already exists at {claude_md}")
    else:
        claude_md.write_text(CLAUDE_MD_CONTENT)
        results["created"].append(str(claude_md))

    # Create .mcp.json
    mcp_json = target_dir / ".mcp.json"
    if mcp_json.exists():
        results["skipped"].append(str(mcp_json))
        results["warnings"].append(f".mcp.json already exists at {mcp_json}")
    else:
        mcp_json.write_text(MCP_JSON_CONTENT)
        results["created"].append(str(mcp_json))

    # Add .agent-harness to .gitignore if it exists
    gitignore = target_dir / ".gitignore"
    if gitignore.exists():
        content = gitignore.read_text()
        if ".agent-harness" not in content:
            with open(gitignore, "a") as f:
                f.write("\n# Agent Protocol Harness session data\n.agent-harness/\n")
            results["created"].append(f"{gitignore} (appended)")

    return results


def main():
    """CLI entry point for aph-init."""
    import sys

    if len(sys.argv) > 1:
        target = Path(sys.argv[1])
    else:
        target = Path.cwd()

    if not target.exists():
        print(f"Error: Directory does not exist: {target}")
        sys.exit(1)

    if not target.is_dir():
        print(f"Error: Not a directory: {target}")
        sys.exit(1)

    print(f"Initializing agent-protocol-harness in {target}")
    print()

    results = init_project(target)

    if results["created"]:
        print("Created:")
        for f in results["created"]:
            print(f"  ✓ {f}")

    if results["skipped"]:
        print("\nSkipped (already exist):")
        for f in results["skipped"]:
            print(f"  - {f}")

    if results["warnings"]:
        print("\nWarnings:")
        for w in results["warnings"]:
            print(f"  ⚠ {w}")

    print()
    print("Next steps:")
    print("  1. Add MCP server to Claude Code:")
    print('     claude mcp add agent-protocol-harness "agent-protocol-harness-mcp"')
    print("  2. Or restart Claude Code to auto-discover from .mcp.json")
    print()


if __name__ == "__main__":
    main()
