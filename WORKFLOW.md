# Agent Harness Workflow

## How You Actually Use This

### Setup (One Time)

**For Claude Code CLI:**
```bash
# Install
pip install agent-harness

# Add to your shell config or run before Claude
export CLAUDE_MCP_SERVERS='{"agent-harness": {"command": "python", "args": ["-m", "agent_harness.mcp_server"]}}'

# Or pass directly
claude --mcp agent-harness="python -m agent_harness.mcp_server"
```

**For Claude Desktop:**
Edit `~/Library/Application Support/Claude/claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "agent-harness": {
      "command": "python",
      "args": ["-m", "agent_harness.mcp_server"],
      "cwd": "/path/to/your/default/repo"
    }
  }
}
```

---

## The Workflow (What You Experience)

### 1. You Describe the Task

```
You: Add authentication with JWT to my express/react app. 
     Users should be able to register, login, and access 
     a protected dashboard.
```

### 2. Claude Analyzes and Proposes

Claude automatically calls `analyze_task` and `propose_plan`:

```
Claude: I've analyzed your codebase and this task spans 3 systems 
        (database, backend, frontend). Here's my proposed plan:

        ┌─────────────────────────────────────────────────────────┐
        │ EXECUTION PLAN                                          │
        ├─────────────────────────────────────────────────────────┤
        │                                                         │
        │  ┌──────────┐                                          │
        │  │ database │  Create User + Session tables            │
        │  └────┬─────┘                                          │
        │       │                                                 │
        │       ▼                                                 │
        │  ┌──────────┐                                          │
        │  │ backend  │  JWT auth endpoints + middleware         │
        │  └────┬─────┘                                          │
        │       │                                                 │
        │       ▼                                                 │
        │  ┌──────────┐                                          │
        │  │ frontend │  Login page + AuthContext                │
        │  └──────────┘                                          │
        │                                                         │
        └─────────────────────────────────────────────────────────┘

        Agent Details:
        
        database:
          scope: database/migrations/, prisma/
          produces: User table, Session table
          verify: npx prisma migrate dev
        
        backend:
          scope: backend/routes/, backend/middleware/
          depends: database ✓
          produces: /api/auth/* endpoints
          verify: npm test --grep auth
        
        frontend:
          scope: frontend/src/pages/, frontend/src/context/
          depends: backend ✓
          produces: Login.jsx, AuthContext.jsx
          verify: npm run test:frontend

        Does this look right? I can adjust the plan if needed.
```

### 3. You Review and Adjust

```
You: Looks good, but add rate limiting to the backend agent's scope. 
     Also I want the frontend to include a Register page.
```

Claude calls `modify_plan`:

```
Claude: Updated:
        
        backend:
          scope: backend/routes/, backend/middleware/, backend/utils/rateLimit.js
          produces: /api/auth/* endpoints, rate limiting middleware
        
        frontend:
          produces: Login.jsx, Register.jsx, AuthContext.jsx

        Ready to proceed?
```

### 4. You Approve

```
You: Yes, let's do it.
```

Claude calls `approve_plan`:

```
Claude: ✓ Plan approved
        ✓ Created branch: ai/session-20240115-143052
        
        Ready to execute. This will:
        1. Run database agent (creates migrations)
        2. Run backend agent (implements auth)
        3. Run frontend agent (builds UI)
        
        Each agent runs in isolation and creates a checkpoint commit.
        
        Execute now?
```

### 5. Execution with Progress

```
You: Go ahead.
```

Claude calls `execute_plan`:

```
Claude: Executing plan...

        [1/3] database ━━━━━━━━━━━━━━━━━━━━ 100% 
              ✓ Created prisma/schema.prisma (User, Session models)
              ✓ Created database/migrations/20240115_auth.sql
              ✓ Verification: npx prisma migrate dev ✓
              📌 Commit: a1b2c3d "checkpoint: database complete"

        [2/3] backend  ━━━━━━━━━━━━━━━━━━━━ 100%
              ✓ Created backend/routes/auth.js
              ✓ Created backend/middleware/auth.js
              ✓ Created backend/utils/rateLimit.js
              ✓ Verification: npm test --grep auth ✓ (5 tests passed)
              📌 Commit: d4e5f6g "checkpoint: backend complete"

        [3/3] frontend ━━━━━━━━━━━━━━━━━━━━ 100%
              ✓ Created frontend/src/pages/Login.jsx
              ✓ Created frontend/src/pages/Register.jsx
              ✓ Created frontend/src/context/AuthContext.jsx
              ⚠ Verification: npm run test:frontend
                 1 test failed: "redirects unauthenticated users"
              📌 Commit: h7i8j9k "checkpoint: frontend complete"

        Execution complete. Frontend has a failing test.
        Would you like to review the results?
```

### 6. You Review and Provide Feedback

```
You: Show me the frontend test failure.
```

Claude calls `get_results`:

```
Claude: Frontend test failure:

        FAIL src/pages/Login.test.jsx
        ✗ redirects unauthenticated users to login
          Expected: redirect to /login
          Received: redirect to /auth/login
        
        The test expects /login but the component redirects to /auth/login.
        
        Options:
        1. Fix the component (change to /login)
        2. Fix the test (change expectation to /auth/login)
        3. Show me the component code
```

```
You: The /auth/login route is correct. Fix the test.
```

Claude calls `provide_feedback`:

```
Claude: Got it. I'll retry the frontend agent with this feedback.

        Retrying frontend...
        
        ✓ Updated frontend/src/pages/Login.test.jsx
        ✓ Verification: npm run test:frontend ✓ (all tests passed)
        📌 Commit: m1n2o3p "fix: update login redirect test"

        All agents complete and verified. Ready to finalize?
```

### 7. Finalize

```
You: Merge it.
```

Claude calls `finalize`:

```
Claude: ✓ Squash-merged to main
        ✓ Deleted session branch
        
        Commit: "feat: add JWT authentication with login, register, and protected dashboard"
        
        Summary of changes:
        - 3 new migrations
        - 4 new backend files  
        - 3 new frontend files
        - 6 new tests (all passing)
```

---

## Alternative Flows

### Discard Everything

```
You: Actually, let's scrap this and try a different approach.
```

```
Claude: Understood. Discarding all changes and returning to main branch.
        
        ✓ Checked out main
        ✓ Deleted ai/session-20240115-143052
        
        All changes removed. What would you like to try instead?
```

### Keep for Manual Review

```
You: Keep the branch, I want to review the code manually first.
```

```
Claude: ✓ Session branch kept: ai/session-20240115-143052
        ✓ Switched back to main
        
        You can review and merge manually:
          git checkout ai/session-20240115-143052
          git diff main...ai/session-20240115-143052
          git checkout main && git merge ai/session-20240115-143052
```

### Partial Execution

```
You: Just run the backend agent for now.
```

```
Claude: Running only backend agent...
        
        Note: backend depends on database. Running database first.
        
        [1/2] database ✓
        [2/2] backend ✓
        
        Frontend agent pending. Run when ready with "continue with frontend".
```

---

## Key Differences from Batch CLI

| Aspect | Batch CLI | MCP Interactive |
|--------|-----------|-----------------|
| Planning | Run contracts.yaml | Claude proposes, you approve |
| Feedback | None (one-shot) | Iterate until satisfied |
| Git | Manual | Auto-branches, checkpoints |
| Errors | Fail and report | Ask how to handle |
| UX | `agent-harness run ...` | Natural conversation |
| Control | All or nothing | Agent-by-agent |

---

## Commands Reference (What Claude Uses)

You don't type these—Claude calls them as tools:

| Tool | When Claude Uses It |
|------|---------------------|
| `analyze_task` | When you describe a task |
| `propose_plan` | After analysis, to show you the plan |
| `get_plan_status` | When you ask about the current plan |
| `modify_plan` | When you request changes |
| `approve_plan` | When you say "looks good" / "proceed" |
| `execute_plan` | When you confirm execution |
| `get_results` | When showing execution output |
| `provide_feedback` | When you give feedback on results |
| `finalize` | When you say "merge" / "discard" / "keep" |
| `get_session_status` | When you ask "where are we?" |
