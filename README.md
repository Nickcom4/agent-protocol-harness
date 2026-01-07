# Agent Protocol Harness

A multi-agent orchestration system that provides **true isolation and
coordination** for the Agent Protocol v3.

## Quick Start

### Option 1: Dev Container (Recommended)

Clone and open in VS Code with Dev Containers extension - everything auto-configures:

```bash
git clone https://github.com/nickcom4/agent-protocol-harness
code agent-protocol-harness
# Click "Reopen in Container" when prompted
```

### Option 2: Manual Install

```bash
# Install from git
pip install git+https://github.com/nickcom4/agent-protocol-harness.git

# Initialize in your project (creates CLAUDE.md and .mcp.json)
aph-init

# Or manually add MCP server
claude mcp add agent-protocol-harness "agent-protocol-harness-mcp"

# Then just talk to Claude:
# "Add authentication with JWT to my express/react app"
```

### Option 3: Add to Your Dev Container

Add to your `.devcontainer/devcontainer.json`:

```json
{
  "postCreateCommand": "pip install git+https://github.com/nickcom4/agent-protocol-harness.git && aph-init"
}
```

Claude will:

1. **Analyze** your task and propose a multi-agent plan
2. **Ask for approval** before executing
3. **Create a feature branch** for isolation
4. **Execute agents** with checkpoint commits
5. **Show results** and accept feedback
6. **Iterate** until you're satisfied
7. **Merge or discard** based on your decision

See [docs/WORKFLOW.md](docs/WORKFLOW.md) for the full interactive experience.

---

## The Problem

The Agent Protocol defines a contract language for multi-agent coordination:

```markdown
---AGENT:backend
SCOPE: backend/, api/
CANNOT: frontend/
DEPENDS: none
PRODUCES: /api/auth/* endpoints
VERIFY: npm test
---
```

But without enforcement, these are just promises. An agent can:

- Touch files outside its `SCOPE`
- Ignore `CANNOT` restrictions
- Claim `READY` without verification
- Share context/state with other "agents"

## The Solution

This harness provides **actual guarantees**:

| Contract Field        | Without Harness | With Harness                           |
| --------------------- | --------------- | -------------------------------------- |
| `SCOPE: backend/`     | Agent promises  | Agent can only see `backend/` files    |
| `CANNOT: frontend/`   | Self-policed    | File access denied at OS level         |
| `DEPENDS: READY:auth` | Sequential text | Execution blocks until signal received |
| `PRODUCES: endpoints` | Trust-based     | Validated before `READY` accepted      |
| `VERIFY: npm test`    | Optional        | Must pass to complete                  |

## Installation

```bash
pip install agent-harness

# With Redis support for distributed execution
pip install agent-harness[redis]

# Development
pip install agent-harness[dev]
```

## Quick Start

### 1. Define Contracts

Create `contracts.yaml`:

```yaml
agents:
  - name: backend-auth
    scope:
      - backend/routes/
      - backend/middleware/
      - backend/services/auth.js
    cannot:
      - frontend/
      - "*.md"
    depends: []
    produces:
      - /api/auth/login endpoint
      - /api/auth/register endpoint
    verify:
      - npm test -- --grep auth
      - "curl -s localhost:3000/api/auth/login | grep -q 'method'"
    goal: "Implement JWT authentication with login and register endpoints"

  - name: frontend-auth
    scope:
      - frontend/src/pages/Login.jsx
      - frontend/src/context/AuthContext.jsx
    cannot:
      - backend/
      - database/
    depends:
      - READY:backend-auth
    expects:
      - /api/auth/login endpoint
      - /api/auth/register endpoint
    produces:
      - Login page component
      - Auth context provider
    verify:
      - npm run test:frontend
    goal: "Create login page and auth context using the backend auth endpoints"
```

### 2. Run Orchestration

```bash
# Run with default settings
agent-harness run contracts.yaml --repo ./myproject

# Run with Docker isolation
agent-harness run contracts.yaml --repo ./myproject --docker

# Override goals
agent-harness run contracts.yaml -g "backend-auth:add rate limiting to auth"

# Verbose output with JSON results
agent-harness run contracts.yaml -v --output results.json
```

### 3. Extract from Claude Response

If Claude generates a split plan, extract the contracts:

```bash
# Save Claude's response to a file
agent-harness extract claude_response.md --output contracts.yaml
```

## CLI Commands

### `run`

Execute agents from a contracts file:

```bash
agent-harness run CONTRACTS_FILE [OPTIONS]

Options:
  -r, --repo PATH       Repository root path [default: .]
  -g, --goal TEXT       Agent goal as 'agent:goal text' (multiple allowed)
  -m, --model TEXT      Claude model [default: claude-sonnet-4-20250514]
  -p, --protocol PATH   Path to protocol markdown file
  --docker/--no-docker  Use Docker for isolation [default: no-docker]
  -t, --timeout INT     Timeout per agent in seconds [default: 600]
  -o, --output PATH     Output JSON file for results
  -v, --verbose         Verbose output
```

### `validate`

Check contracts for errors:

```bash
agent-harness validate contracts.yaml
```

Checks:

- Syntax errors
- Overlapping scopes
- Missing dependencies
- Circular dependencies

### `plan`

Show execution plan without running:

```bash
agent-harness plan contracts.yaml
```

Output:

```
Execution Plan
========================================

Dependency Graph:
  backend-auth (entry point)
  frontend-auth ← READY:backend-auth

Parallel Groups:
  Group 1: backend-auth
  Group 2: frontend-auth

Sequential Order: backend-auth → frontend-auth

Total scope patterns: 5
Max parallel agents: 1
```

### `watch`

Monitor signals in real-time:

```bash
agent-harness watch --signal-dir /tmp/agent_signals
```

### `extract`

Extract contracts from Claude's split response:

```bash
agent-harness extract claude_response.md --output contracts.yaml
```

## Python API

```python
import asyncio
from pathlib import Path
from agent_harness import (
    Orchestrator,
    parse_contracts,
    Contract,
)

# Parse contracts from YAML or markdown
contracts = parse_contracts(Path("contracts.yaml").read_text())

# Or define programmatically
contracts = [
    Contract(
        name="backend",
        scope=["backend/", "api/"],
        cannot=["frontend/"],
        depends=[],
        produces=["API endpoints"],
        verify=["npm test"],
        goal="Implement backend API",
    ),
    Contract(
        name="frontend",
        scope=["frontend/"],
        cannot=["backend/"],
        depends=["READY:backend"],
        produces=["React components"],
        verify=["npm run test:frontend"],
        goal="Build frontend UI",
    ),
]

# Run orchestration
async def main():
    orchestrator = Orchestrator(
        repo_root=Path("./myproject"),
        model="claude-sonnet-4-20250514",
        use_docker=True,  # Full isolation
    )

    result = await orchestrator.run(contracts)

    if result.success:
        print("All agents completed!")
        for name, agent_result in result.agents.items():
            print(f"  {name}: {len(agent_result.files_created)} files created")
    else:
        print("Errors:", result.errors)

asyncio.run(main())
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Orchestrator                          │
│  - Parses contracts                                          │
│  - Builds execution plan                                     │
│  - Manages agent lifecycle                                   │
│  - Aggregates results                                        │
└─────────────────────────────────────────────────────────────┘
        │                    │                    │
        ▼                    ▼                    ▼
┌───────────────┐   ┌───────────────┐   ┌───────────────┐
│ Agent Worker  │   │ Agent Worker  │   │ Agent Worker  │
│ (Isolated)    │   │ (Isolated)    │   │ (Isolated)    │
├───────────────┤   ├───────────────┤   ├───────────────┤
│ Claude API    │   │ Claude API    │   │ Claude API    │
│ Tool Handlers │   │ Tool Handlers │   │ Tool Handlers │
│ Scope Enforcer│   │ Scope Enforcer│   │ Scope Enforcer│
└───────────────┘   └───────────────┘   └───────────────┘
        │                    │                    │
        └────────────┬───────┴───────────────────┘
                     │
                     ▼
           ┌─────────────────┐
           │  Signal Broker  │
           │  (Coordination) │
           └─────────────────┘
```

### Components

**Parser** (`parser.py`)

- Extracts contracts from markdown `---AGENT` blocks
- Parses YAML contract definitions
- Validates scope overlaps and dependencies

**Signal Broker** (`signals.py`)

- In-memory, file-based, or Redis backends
- Pub/sub for `READY`, `BLOCKED`, `FAILED` signals
- Async waiting with timeouts

**Filesystem Isolator** (`isolator.py`)

- Creates scoped workspaces per agent
- Docker containers with volume mounts
- Scope enforcement at file operation level

**Claude Client** (`claude_client.py`)

- System prompt injection with contract
- Tool definitions based on scope
- Response parsing for signals and state

**Orchestrator** (`orchestrator.py`)

- Dependency graph resolution
- Parallel group execution
- Result aggregation and sync-back

## Isolation Modes

### No Isolation (Default)

Files are copied to a workspace directory. Scope is enforced via tool handlers
that check paths before operations.

```bash
agent-harness run contracts.yaml
```

**Guarantees:**

- ✅ Scope checking on tool calls
- ❌ Agent could bypass via shell commands
- ❌ No memory isolation

### Docker Isolation

Each agent runs in a Docker container with only scoped files mounted.

```bash
agent-harness run contracts.yaml --docker
```

**Guarantees:**

- ✅ Filesystem isolation at OS level
- ✅ Cannot see files outside scope
- ✅ Process isolation
- ❌ Shared network (can be restricted)

## Signal Types

| Signal                  | Meaning                          | Triggers                        |
| ----------------------- | -------------------------------- | ------------------------------- |
| `READY:agent`           | Work complete, outputs available | Dependent agents can start      |
| `BLOCKED:agent:reason`  | Cannot proceed                   | May trigger restart or escalate |
| `FAILED:agent:reason`   | Unrecoverable failure            | Stops dependent agents          |
| `DATA:agent:path`       | Intermediate output ready        | For streaming results           |
| `ESCALATE:agent:reason` | Needs human intervention         | Pauses orchestration            |

## Contract Fields

| Field      | Required | Description                                     |
| ---------- | -------- | ----------------------------------------------- |
| `name`     | Yes      | Unique agent identifier                         |
| `scope`    | Yes      | Glob patterns for allowed paths                 |
| `cannot`   | No       | Glob patterns for forbidden paths               |
| `depends`  | No       | Signals that must exist before start            |
| `expects`  | No       | Inputs required from dependencies               |
| `produces` | No       | Outputs that must exist before `READY`          |
| `verify`   | No       | Commands that must pass before `READY`          |
| `goal`     | No       | Task description (can be overridden at runtime) |

## Protocol Integration

This harness is designed to work with the Agent Protocol v3. When Claude
generates a SPLIT response:

```
SPLIT REQUIRED

COMPLEXITY: 20 (threshold: 5.3) → DECOMPOSE

---AGENT:backend-auth
SCOPE: backend/routes/, backend/middleware/
...
---
```

You can extract and run these contracts:

```bash
# Save Claude's response
cat > claude_response.md

# Extract contracts
agent-harness extract claude_response.md -o contracts.yaml

# Review and edit if needed
vim contracts.yaml

# Run
agent-harness run contracts.yaml --repo ./myproject
```

## Development

```bash
# Clone
git clone https://github.com/yourname/agent-harness
cd agent-harness

# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Type check
mypy src/

# Lint
ruff check src/
```

## License

MIT
