# Agent-Protocol-Harness MCP Improvement Plan

**Date:** 2026-01-08
**Goal:** Make the agent-protocol-harness MCP more autonomous and proactive in dev containers

---

## Executive Summary

The agent-protocol-harness MCP enables multi-agent orchestration for Claude Code CLI. Evaluation findings show it's underutilized:
- `get_task_guidance` tool called only ~10% of the time (should be 100%)
- MCP provides value when used but isn't proactive enough
- Test failures are due to missing dependencies, not MCP issues

**Solution:** Transform the MCP from **tool-based** (requires explicit calls) to **resource-based** (always-available passive context).

---

## Background Context

### What is agent-protocol-harness?

An MCP server that provides multi-agent orchestration for complex coding tasks. Key features:
- **Contract-based isolation** - Agents work on defined scopes with enforced boundaries
- **Full-power sub-agents** - Each agent runs as a complete Claude Code session
- **Session persistence** - State survives context exhaustion
- **Error reconciliation** - Auto-detects and fixes common issues

**Location:** `/tmp/agent-protocol-harness/src/agent_harness/`

### Current Architecture

**Tool-based workflow:**
```
User asks task → Claude calls get_task_guidance → MCP responds → Claude proceeds
```

**Problem:** Claude doesn't consistently call `get_task_guidance`, so MCP value is lost.

### MCP Protocol Constraints

- ✅ **Can** provide MCP resources (auto-available, no tool call needed)
- ✅ **Can** provide rich markdown with install commands
- ✅ **Can** inject system prompts for sub-agents only (via Contract)
- ❌ **Cannot** inject system prompts into main Claude Code CLI session
- ❌ **Cannot** force Claude to call tools
- ❌ **Cannot** auto-execute without tool invocation

---

## Implementation Plan

### Goals (User-Confirmed)

1. **Primary:** Improve MCP effectiveness (make it more autonomous/proactive)
2. **Dependency handling:** MCP detects missing packages and suggests installation commands
3. **Tool adoption:** Make `get_task_guidance` passive (auto-provide via resources, no tool call needed)

### Architectural Transformation

**New resource-based workflow:**
```
User asks task → Claude auto-reads resources → Context already available → Claude proceeds
```

**Key insight:** MCP resources are listed automatically by Claude Code CLI. By providing rich, actionable resources with **attention-grabbing names**, we make guidance always-available without requiring tool calls.

---

## Implementation Details

### 1. New Files to Create

#### `/tmp/agent-protocol-harness/src/agent_harness/workspace_monitor.py` (NEW - ~400 lines)

**Purpose:** Real-time workspace analysis for proactive issue detection

**Core Functionality:**
- Scan `package.json`, `pyproject.toml`, `requirements.txt`, `go.mod` for dependencies
- Detect missing packages by checking `node_modules/`, `site-packages/`, etc.
- Generate install commands: `npm install express`, `pip install flask`
- Detect config issues: `.env.example` exists but `.env` missing
- Health score: 0-100 based on dependency status

**Key Methods:**
```python
class WorkspaceMonitor:
    def scan_dependencies(self) -> DependencyReport
    def detect_missing_packages(self) -> List[MissingPackage]
    def suggest_install_commands(self) -> List[InstallCommand]
    def format_dependency_report(self) -> str  # Markdown output
    def get_quick_status(self) -> str  # One-line summary for codebase summary
```

**Performance Optimizations:**
- Lazy loaded (only instantiated when first resource is read)
- Cached with 60s TTL
- Incremental scanning (only rescan if package files changed via mtime check)
- Parallel scanning for multiple package managers

**Dependency Detection Algorithm:**
```python
def scan_dependencies(self) -> DependencyReport:
    """
    1. Scan project files:
       - package.json (JavaScript/TypeScript)
       - pyproject.toml, requirements.txt (Python)
       - go.mod (Go), Cargo.toml (Rust), Gemfile (Ruby)

    2. For each ecosystem:
       a. Parse declared dependencies
       b. Check if installed (node_modules, site-packages, etc.)
       c. Cross-reference imports in source files
       d. Generate install commands for missing

    3. Build report with severity levels:
       - Critical: Blocks execution
       - Warning: May cause issues
       - Info: Optimizations
    """
```

---

#### `/tmp/agent-protocol-harness/src/agent_harness/task_analyzer.py` (NEW - ~300 lines)

**Purpose:** Lightweight task analysis without requiring tool calls

**Core Functionality:**
- Parse task from conversation context (use heuristics since MCP can't see conversation directly)
- Extract complexity signals (multi-system keywords, scope indicators)
- Suggest approach (direct vs checkpointed vs orchestrated)
- Generate verification checklist

**Context Extraction Heuristics:**

Since MCP cannot directly see Claude's conversation, use:
1. Git branch name (if on feature branch: `feature/add-auth` → task is "add auth")
2. Recent commit messages
3. Modified files (infer scope from what's being changed)
4. Resource URI parameters (if Claude includes `?task=...` in resource request)

**Key Methods:**
```python
class TaskAnalyzer:
    def analyze_current_context(self) -> str  # Markdown analysis
    def extract_complexity_signals(self, task: str) -> ComplexitySignals
    def suggest_approach(self, complexity: int) -> Approach
    def generate_verification_checklist(self) -> List[str]
```

**Approach Recommendation Logic:**
```python
def recommend_approach(complexity_score: int, system_count: int) -> str:
    """
    Complexity scoring:
    - Multi-system keywords (frontend, backend, database): +2 each
    - Large scope (refactor, migrate, architecture): +3
    - Auth/payments: +2

    Thresholds:
    - < 3: Direct execution (simple, single-system)
    - 3-4: Checkpointed (moderate complexity)
    - >= 5: Orchestrated (complex, multi-system)
    """
    if complexity_score < 3 and system_count == 1:
        return "direct"
    elif complexity_score < 5 or system_count <= 2:
        return "checkpointed"
    else:
        return "orchestrated"
```

---

### 2. Files to Modify

#### `/tmp/agent-protocol-harness/src/agent_harness/mcp_server.py` (MODIFY)

**Changes Required:**

**A. Add lazy-loaded components (lines 60-65):**
```python
# In __init__()
self._workspace_monitor: Optional[WorkspaceMonitor] = None
self._task_analyzer: Optional[TaskAnalyzer] = None

@property
def workspace_monitor(self) -> WorkspaceMonitor:
    if self._workspace_monitor is None:
        self._workspace_monitor = WorkspaceMonitor(self.repo_root)
    return self._workspace_monitor

@property
def task_analyzer(self) -> TaskAnalyzer:
    if self._task_analyzer is None:
        self._task_analyzer = TaskAnalyzer(self.repo_root, self.passive_context)
    return self._task_analyzer
```

**B. Add new resource URIs to `list_resources()` (lines 145-166):**

Add these 5 new resources:
```python
# Workspace health resources
resources.append(Resource(
    uri="agent://workspace/dependency-status",
    name="🔴 Dependency Issues Detected",
    description="READ ME FIRST: Missing packages will block execution. Contains install commands.",
    mimeType="text/markdown",
))

resources.append(Resource(
    uri="agent://workspace/health-check",
    name="⚠️ Workspace Health Check",
    description="Common configuration issues and quick fixes",
    mimeType="text/markdown",
))

# Task guidance resources
resources.append(Resource(
    uri="agent://guidance/task-analysis",
    name="📋 Task Analysis & Recommendations",
    description="Auto-detected task complexity, approach recommendations, and scope suggestions",
    mimeType="text/markdown",
))

resources.append(Resource(
    uri="agent://guidance/quick-start",
    name="🚀 Quick Start Guide",
    description="Recommended first steps based on workspace analysis",
    mimeType="text/markdown",
))

resources.append(Resource(
    uri="agent://guidance/verification-checklist",
    name="✅ Verification Checklist",
    description="Suggested verification steps for current task",
    mimeType="text/markdown",
))
```

**Critical:** Use **emoji and action-oriented descriptions** to grab Claude's attention.

**C. Implement resource readers in `read_resource()` (lines 170-185):**
```python
@self.server.read_resource()
async def read_resource(uri: str):
    # ... existing resources ...

    elif uri == "agent://workspace/dependency-status":
        return self.workspace_monitor.format_dependency_report()

    elif uri == "agent://workspace/health-check":
        return self.workspace_monitor.format_health_report()

    elif uri == "agent://guidance/task-analysis":
        return self.task_analyzer.analyze_current_context()

    elif uri == "agent://guidance/quick-start":
        return self._generate_quick_start_guide()

    elif uri == "agent://guidance/verification-checklist":
        return self.task_analyzer.generate_verification_checklist()

    return "Unknown resource"

def _generate_quick_start_guide(self) -> str:
    """Combines dependency status + task analysis into actionable guide."""
    dep_status = self.workspace_monitor.get_quick_status()
    task_analysis = self.task_analyzer.analyze_current_context()

    return f"""# Quick Start Guide

## Step 1: Resolve Dependencies
{dep_status}

## Step 2: Understand Task
{task_analysis}

## Step 3: Begin Implementation
Follow the recommended approach above.
"""
```

**D. Update `get_task_guidance` tool description (lines 194-209):**
```python
Tool(
    name="get_task_guidance",
    description="""
    ⚠️ DEPRECATED: Task guidance is now auto-available via resources.

    Read these resources instead of calling this tool:
    - agent://guidance/task-analysis (recommended approach)
    - agent://workspace/dependency-status (missing packages)
    - agent://guidance/quick-start (actionable guide)

    This tool remains for backwards compatibility but will be removed in v2.0.
    """,
    ...
)
```

---

#### `/tmp/agent-protocol-harness/src/agent_harness/passive_context.py` (MODIFY)

**Changes Required:**

**A. Import WorkspaceMonitor (line 8):**
```python
from .workspace_monitor import WorkspaceMonitor
```

**B. Initialize monitor in `__init__` (lines 15-20):**
```python
def __init__(self, repo_root: Path):
    self.repo_root = repo_root
    self._cached_summary: Optional[str] = None
    self._workspace_monitor = WorkspaceMonitor(repo_root)
```

**C. Enhance `generate_codebase_summary()` with dependency info (lines 41-55):**
```python
summary = f"""# Codebase Summary (Auto-detected)

## Tech Stack
{tech_stack}

## Dependency Health
{self._workspace_monitor.get_quick_status()}

## Structure
{structure}

## Detected Patterns
{patterns}

## Conventions
{conventions}
"""
```

**D. Add new methods at end of file:**
```python
def get_dependency_status(self) -> Dict:
    """Get current dependency status with install commands."""
    return self._workspace_monitor.scan_dependencies()

def get_health_report(self) -> str:
    """Get workspace health report in markdown."""
    return self._workspace_monitor.format_health_report()
```

---

#### `/tmp/agent-protocol-harness/src/agent_harness/models.py` (ADD)

**Add to end of file (~100 lines):**

```python
from dataclasses import dataclass
from typing import List, Optional

@dataclass
class DependencyReport:
    """Comprehensive dependency analysis report."""
    missing: List['MissingPackage']
    outdated: List['OutdatedPackage']
    unused: List[str]
    conflicts: List['Conflict']
    health_score: int  # 0-100

@dataclass
class MissingPackage:
    """A dependency that's declared but not installed."""
    name: str
    ecosystem: str  # "npm", "pip", "gem", etc.
    install_command: str  # Ready-to-run command
    detected_from: str  # Where we found the reference (e.g., "src/api.py:1")
    severity: str  # "critical", "warning", "info"

@dataclass
class OutdatedPackage:
    """A dependency with available updates."""
    name: str
    current_version: str
    latest_version: str
    update_command: str

@dataclass
class Conflict:
    """Version conflict between dependencies."""
    package: str
    required_by: List[str]
    conflicting_versions: List[str]

@dataclass
class TaskAnalysis:
    """Analysis of the current coding task."""
    task_description: str
    task_type: str  # "feature", "bugfix", "refactor", "test", etc.
    complexity_score: int  # 0-10
    affected_systems: List[str]  # ["frontend", "backend", "database"]
    recommended_approach: str  # "direct", "checkpointed", "orchestrated"
    verification_steps: List[str]
    potential_pitfalls: List[str]
```

---

### 3. Resource Format Examples

These are the **actual outputs** Claude will see when reading resources.

#### Dependency Status Resource (`agent://workspace/dependency-status`)

```markdown
# Dependency Status ⚠️

## Missing Packages (2)

### Critical
- **flask** (pip) - Required by `src/api.py:1`
  ```bash
  pip install flask
  ```

- **pyjwt** (pip) - Required by `backend/routes/auth.py:5`
  ```bash
  pip install pyjwt
  ```

### Recommended
- **pytest** (pip) - Required for tests in `tests/test_api.py`
  ```bash
  pip install pytest
  ```

## Quick Fix
Run all install commands at once:
```bash
pip install flask pyjwt pytest
```

## Health Score: 65/100
⚠️ **Impact:** Missing critical dependencies will prevent code execution.

---

💡 **TIP:** Read `agent://guidance/task-analysis` for approach recommendations.
```

#### Task Analysis Resource (`agent://guidance/task-analysis`)

```markdown
# Task Analysis

**Detected Task:** "Create Flask API for managing items"
**Inferred from:** Git branch `feature/api-crud`, recent commits

## Complexity Assessment
- **Complexity Score:** 4/10 (Medium)
- **Task Type:** Feature implementation
- **Affected Systems:** Backend (1 system)
- **Expected Files:** 3-5 files

## Recommended Approach
✅ **Direct execution** - Task is contained within single system

**Why direct?**
- Single codebase area (backend only)
- No cross-system dependencies
- Straightforward verification

## Suggested Implementation Steps
1. **Resolve dependencies:** Run `pip install flask pytest`
2. **Create data models:** `src/models.py` with Item dataclass
3. **Implement API:** `src/api.py` with CRUD routes
4. **Add tests:** `tests/test_api.py` with endpoint tests
5. **Verify:** Run tests and manual API checks

## Verification Checklist
- [ ] Flask imports successfully: `python -c 'from src.api import app'`
- [ ] Routes defined with `@app.route` decorator
- [ ] Data models use `@dataclass` or similar
- [ ] Tests exist and pass: `pytest tests/test_api.py`
- [ ] Manual testing: Start server and test endpoints

## Potential Pitfalls
- **Missing dependencies:** Install Flask before running code
- **Port conflicts:** Default port 5000 may be in use
- **Import errors:** Ensure PYTHONPATH includes project root

---

💡 **TIP:** If complexity increases (e.g., adding auth + frontend), consider orchestration. Read `agent://guidance/quick-start` for next steps.
```

#### Quick Start Guide (`agent://guidance/quick-start`)

```markdown
# Quick Start Guide 🚀

## Step 1: Resolve Dependencies ⚠️
You have **2 critical** and **1 recommended** packages missing.

**Quick fix:**
```bash
pip install flask pyjwt pytest
```

[Read full report: `agent://workspace/dependency-status`]

## Step 2: Understand Your Task 📋
**Task:** Create Flask API for items
**Complexity:** Medium (4/10)
**Approach:** ✅ Direct execution

**Why this approach?**
Task is contained to backend, single system, straightforward verification.

[Read full analysis: `agent://guidance/task-analysis`]

## Step 3: Begin Implementation 💻

### Recommended file structure:
```
src/
  ├── api.py          ← Flask routes (GET, POST, PUT, DELETE)
  ├── models.py       ← Item dataclass
  └── __init__.py
tests/
  └── test_api.py     ← Endpoint tests
```

### Next steps:
1. Run dependency install command above
2. Create `src/models.py` with Item dataclass
3. Create `src/api.py` with Flask app and routes
4. Create `tests/test_api.py` with tests
5. Verify: `pytest tests/`

---

📚 **Resources:**
- Verification checklist: `agent://guidance/verification-checklist`
- Codebase patterns: `agent://context/codebase-summary`
- If stuck: Call `check_session` tool for orchestration
```

---

## Critical Files Summary

| File | Type | Priority | Size | Purpose |
|------|------|----------|------|---------|
| `workspace_monitor.py` | NEW | HIGH | ~400 lines | Dependency detection, health checks |
| `task_analyzer.py` | NEW | HIGH | ~300 lines | Task analysis, approach recommendation |
| `mcp_server.py` | MODIFY | CRITICAL | ~100 lines added | Resource wiring, lazy loading |
| `passive_context.py` | MODIFY | MEDIUM | ~80 lines added | Monitor integration |
| `models.py` | ADD | MEDIUM | ~100 lines added | Data structures |

---

## Performance Considerations

### Lazy Loading Strategy
```python
@property
def workspace_monitor(self) -> WorkspaceMonitor:
    """Only instantiate when first needed."""
    if self._workspace_monitor is None:
        self._workspace_monitor = WorkspaceMonitor(self.repo_root)
    return self._workspace_monitor
```

### Caching Strategy
- **Codebase summary:** 60s TTL, invalidate on file add/remove
- **Dependency status:** 60s TTL, invalidate on `package.json` / `pyproject.toml` mtime change
- **Task analysis:** No cache (always fresh, cheap to generate)

### Scan Optimization
```python
def needs_rescan(self) -> bool:
    """Check if dependency files changed."""
    check_files = ["package.json", "pyproject.toml", "requirements.txt"]
    for f in check_files:
        if self._file_mtime_changed(f):
            return True
    return False
```

**Target Performance:**
- First dependency scan: <500ms
- Cached resource reads: <10ms
- Total resource read: <100ms

---

## Verification Plan

### End-to-End Test

**Objective:** Verify passive resources work and provide actionable guidance

**Steps:**

1. **Setup test project with missing dependencies:**
   ```bash
   mkdir test-project && cd test-project
   git init
   echo '{"dependencies": {"express": "^4.0.0"}}' > package.json
   # Don't run npm install - leave dependencies missing
   echo "const express = require('express');" > index.js
   ```

2. **Start Claude Code CLI with agent-protocol-harness MCP:**
   ```bash
   claude --mcp agent-protocol-harness
   ```

3. **List MCP resources:**
   ```bash
   # Claude should see new resources:
   # - agent://workspace/dependency-status
   # - agent://workspace/health-check
   # - agent://guidance/task-analysis
   # - agent://guidance/quick-start
   # - agent://guidance/verification-checklist
   ```

4. **Read dependency-status resource:**
   ```bash
   # Should return markdown showing:
   # - "express" as missing package
   # - Install command: npm install express
   # - Health score < 100
   ```

5. **Read task-analysis resource:**
   ```bash
   # Should return analysis without requiring tool call
   # - Detect task from git branch or infer from workspace
   # - Provide complexity assessment
   # - Recommend approach
   ```

6. **Verify performance:**
   ```bash
   # Time first read: should be <500ms
   # Time second read (cached): should be <10ms
   ```

**Expected Results:**
- ✅ Resources appear in MCP resource list
- ✅ Dependency-status shows missing "express" with install command
- ✅ Task-analysis provides guidance without tool call
- ✅ Performance meets targets (<500ms first, <10ms cached)

### Unit Tests to Add

```python
# tests/test_workspace_monitor.py
def test_detect_missing_npm_packages():
    """Verify npm package detection."""
    # Given: package.json with express, no node_modules
    # When: scan_dependencies()
    # Then: returns MissingPackage(name="express", ecosystem="npm")

def test_detect_missing_python_packages():
    """Verify pip package detection."""
    # Given: requirements.txt with flask, no site-packages
    # When: scan_dependencies()
    # Then: returns MissingPackage(name="flask", ecosystem="pip")

def test_generate_install_commands():
    """Verify install commands are correct."""
    # Given: missing packages detected
    # When: suggest_install_commands()
    # Then: returns ["npm install express", "pip install flask"]

def test_health_score_calculation():
    """Verify health score formula."""
    # Given: 2 critical missing, 1 warning
    # When: calculate health score
    # Then: score reduced appropriately (< 100)

# tests/test_task_analyzer.py
def test_extract_complexity_from_task():
    """Verify complexity scoring."""
    # Given: task "add authentication to frontend and backend"
    # When: extract_complexity_signals()
    # Then: score >= 5 (multi-system)

def test_recommend_approach_simple():
    """Verify simple task approach."""
    # Given: complexity_score=2, system_count=1
    # When: recommend_approach()
    # Then: returns "direct"

def test_recommend_approach_complex():
    """Verify complex task approach."""
    # Given: complexity_score=6, system_count=3
    # When: recommend_approach()
    # Then: returns "orchestrated"

def test_generate_verification_steps():
    """Verify checklist generation."""
    # Given: task "create Flask API"
    # When: generate_verification_checklist()
    # Then: includes "pytest tests/", "import check", "manual testing"
```

---

## Migration & Rollout

### Phase 1: Add New Components (Backwards Compatible)
- Create `workspace_monitor.py` and `task_analyzer.py`
- Add data models to `models.py`
- **No breaking changes** - existing tools still work

### Phase 2: Integrate Resources
- Wire up new resources in `mcp_server.py`
- Update `passive_context.py` to use monitor
- **Still backwards compatible** - resources alongside tools

### Phase 3: Deprecate Tool (Gradual)
- Mark `get_task_guidance` as deprecated in description
- Update CLAUDE.md to recommend resources first
- Monitor usage metrics

### Phase 4: Remove Tool (v2.0)
- Remove deprecated `get_task_guidance` tool
- Clean up unused code
- Update documentation

**Rollback Plan:** If issues arise, simply don't update `mcp_server.py` resource descriptions. New code exists but isn't exposed, so MCP behaves as before.

---

## Success Metrics

After implementation, measure:

1. **Resource read rate:** % of Claude sessions that read new resources
2. **Tool call reduction:** % decrease in `get_task_guidance` calls (expect to approach 0%)
3. **Dependency install proactivity:** % of sessions where Claude installs deps without explicit prompt
4. **Task completion rate:** % of tasks completed without user intervention
5. **Performance:** Average resource read latency (target: <100ms)

---

## Additional Notes

### Why This Approach Works

**Problem:** Claude doesn't consistently call `get_task_guidance` tool
**Root cause:** Tools are optional - Claude decides when to use them
**Solution:** Make guidance **always available** via resources with attention-grabbing names

**Key psychological triggers:**
- 🔴 Emoji in resource names (visual attention)
- "READ ME FIRST" in descriptions (urgency)
- Action-oriented names ("Dependency Issues Detected" not "Dependency Info")
- Cross-linking between resources (guides user through full context)

### Alternative Considered: System Prompt Injection

**Why not inject into system prompt?**
- MCP protocol doesn't support system prompt injection for main Claude session
- Only works for sub-agents (via `Contract.to_system_prompt_section()`)
- Resources are the closest alternative within protocol constraints

### Future Enhancements

1. **Auto-fix common issues:** Not just detect deps, but auto-install if user confirms
2. **Learning from feedback:** Track which suggestions Claude follows, improve heuristics
3. **Project memory:** Remember project patterns across sessions
4. **Proactive notifications:** When resource changes, notify Claude (if protocol supports)

---

## Contact & Resources

- **MCP Codebase:** `/tmp/agent-protocol-harness/`
- **Evaluation Results:** `/workspaces/MCP-Eval/results/eval-2026-01-08-141829.json`
- **Investigation Report:** `/workspaces/MCP-Eval/INVESTIGATION_REPORT.md`
- **Re-evaluation Report:** `/workspaces/MCP-Eval/REEVALUATION_REPORT.md`
