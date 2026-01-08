# Milestone 4: MCP Server Modifications

**File:** `src/agent_harness/mcp_server.py` (MODIFY)
**Estimated Lines:** ~100 added
**Priority:** CRITICAL

---

## Objective

Wire up the new WorkspaceMonitor and TaskAnalyzer as MCP resources, making guidance passively available without requiring tool calls.

---

## Tier 1: Implementation Plan (Exhaustive, No Breaking Changes)

### 1.1 New Imports (Add at top, after existing imports)

```python
# Add after line 37 (after existing imports)
from .workspace_monitor import WorkspaceMonitor
from .task_analyzer import TaskAnalyzer
```

### 1.2 New Lazy-Loaded Properties (Add in __init__ area)

After line 61 (`self._passive_context: Optional[PassiveContextProvider] = None`), add:

```python
        self._workspace_monitor: Optional[WorkspaceMonitor] = None
        self._task_analyzer: Optional[TaskAnalyzer] = None
```

After line 103 (after `passive_context` property), add:

```python
    @property
    def workspace_monitor(self) -> WorkspaceMonitor:
        """Lazy-load workspace monitor."""
        if self._workspace_monitor is None:
            self._workspace_monitor = WorkspaceMonitor(self.repo_root)
        return self._workspace_monitor

    @property
    def task_analyzer(self) -> TaskAnalyzer:
        """Lazy-load task analyzer."""
        if self._task_analyzer is None:
            self._task_analyzer = TaskAnalyzer(self.repo_root, self.passive_context)
        return self._task_analyzer
```

### 1.3 New Resource URIs (Add to `_setup_resources`)

In the `list_resources()` function, after line 165 (after scope-suggestions resource), add:

```python
            # NEW: Workspace health resources
            resources.append(Resource(
                uri="agent://workspace/dependency-status",
                name="🔴 Dependency Issues",
                description="READ FIRST: Missing packages that may block execution. Contains install commands.",
                mimeType="text/markdown",
            ))

            resources.append(Resource(
                uri="agent://workspace/health-check",
                name="⚠️ Workspace Health",
                description="Configuration issues and quick fixes for the development environment",
                mimeType="text/markdown",
            ))

            # NEW: Task guidance resources (passive versions)
            resources.append(Resource(
                uri="agent://guidance/task-analysis",
                name="📋 Task Analysis",
                description="Auto-detected task complexity and approach recommendations",
                mimeType="text/markdown",
            ))

            resources.append(Resource(
                uri="agent://guidance/quick-start",
                name="🚀 Quick Start Guide",
                description="Recommended first steps based on workspace and task analysis",
                mimeType="text/markdown",
            ))

            resources.append(Resource(
                uri="agent://guidance/verification-checklist",
                name="✅ Verification Checklist",
                description="Suggested verification steps for current task",
                mimeType="text/markdown",
            ))
```

### 1.4 Resource Readers (Add to `read_resource`)

After line 184 (after scope-suggestions handler), add:

```python
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
```

### 1.5 Quick Start Guide Generator (Add as new method)

Add after `_identify_pitfalls` method (around line 565):

```python
    def _generate_quick_start_guide(self) -> str:
        """
        Generate combined quick start guide.

        Combines dependency status + task analysis into actionable guide.
        """
        # Get dependency status
        dep_status = self.workspace_monitor.get_quick_status()
        has_dep_issues = "missing" in dep_status.lower() or "critical" in dep_status.lower()

        # Get task analysis
        task_analysis = self.task_analyzer.analyze_current_context()

        # Build guide
        lines = ["# Quick Start Guide 🚀"]

        # Step 1: Dependencies (only if issues)
        if has_dep_issues:
            lines.append("\n## Step 1: Resolve Dependencies ⚠️")
            lines.append(dep_status)
            lines.append("\n[Full report: `agent://workspace/dependency-status`]")
        else:
            lines.append("\n## Step 1: Dependencies ✅")
            lines.append("All dependencies are installed.")

        # Step 2: Task understanding
        lines.append("\n## Step 2: Understand Your Task 📋")
        # Extract key info from task analysis
        lines.append(task_analysis[:1500])  # Truncate if too long
        lines.append("\n[Full analysis: `agent://guidance/task-analysis`]")

        # Step 3: Begin implementation
        lines.append("\n## Step 3: Begin Implementation 💻")
        lines.append("Follow the recommended approach from task analysis.")
        lines.append("\n### Next Steps")
        if has_dep_issues:
            lines.append("1. Run the dependency install commands above")
        lines.append("2. Review affected files")
        lines.append("3. Make changes incrementally with commits")
        lines.append("4. Verify using checklist")

        # Resources cross-reference
        lines.append("\n---")
        lines.append("📚 **Resources:**")
        lines.append("- Verification checklist: `agent://guidance/verification-checklist`")
        lines.append("- Codebase patterns: `agent://context/codebase-summary`")
        lines.append("- Orchestration (if needed): Call `check_session` tool")

        return "\n".join(lines)
```

### 1.6 Update get_task_guidance Tool Description (DEPRECATION)

Modify the tool description (around line 196-224). Replace:

```python
                Tool(
                    name="get_task_guidance",
                    description="""
                    Get smart guidance for any coding task.

                    Call this FIRST before starting work on any task.
                    Returns:
                    - Recommended approach (direct vs orchestrated)
                    - Scope suggestions (which files to focus on)
                    - Verification steps (how to test)
                    - Potential pitfalls

                    This is a lightweight helper - use it for EVERY task, not just complex ones.
                    For simple tasks, it returns guidance and stays dormant (minimal overhead).
                    For complex tasks, it recommends orchestration tools.
                    """,
```

With:

```python
                Tool(
                    name="get_task_guidance",
                    description="""
                    Get smart guidance for any coding task.

                    💡 **TIP:** Task guidance is now also available via passive resources:
                    - agent://guidance/task-analysis (approach recommendations)
                    - agent://workspace/dependency-status (missing packages)
                    - agent://guidance/quick-start (actionable guide)

                    Use this tool when you need to provide a specific task description
                    for more accurate analysis. The resources above provide context
                    based on git state and workspace analysis.

                    Returns:
                    - Recommended approach (direct vs orchestrated)
                    - Scope suggestions (which files to focus on)
                    - Verification steps (how to test)
                    - Potential pitfalls
                    """,
```

---

## Tier 2: Verification Plan

### 2.1 Unit Tests

```python
# tests/test_mcp_server_resources.py

def test_new_resources_listed():
    """Verify all new resources appear in list_resources."""
    server = AgentHarnessMCP(repo_root=Path("/tmp/test"))
    # Mock the list_resources call
    resources = asyncio.run(server.server.list_resources())

    resource_uris = [r.uri for r in resources]

    assert "agent://workspace/dependency-status" in resource_uris
    assert "agent://workspace/health-check" in resource_uris
    assert "agent://guidance/task-analysis" in resource_uris
    assert "agent://guidance/quick-start" in resource_uris
    assert "agent://guidance/verification-checklist" in resource_uris

def test_dependency_status_resource_readable():
    """Verify dependency-status resource returns markdown."""
    server = AgentHarnessMCP(repo_root=Path("/tmp/test"))
    content = asyncio.run(server.server.read_resource("agent://workspace/dependency-status"))
    assert "# Dependency Status" in content or "Health Score" in content

def test_task_analysis_resource_readable():
    """Verify task-analysis resource returns markdown."""
    server = AgentHarnessMCP(repo_root=Path("/tmp/test"))
    content = asyncio.run(server.server.read_resource("agent://guidance/task-analysis"))
    assert "# Task Analysis" in content

def test_quick_start_guide_structure():
    """Verify quick start guide has expected sections."""
    server = AgentHarnessMCP(repo_root=Path("/tmp/test"))
    content = asyncio.run(server.server.read_resource("agent://guidance/quick-start"))
    assert "Step 1" in content
    assert "Step 2" in content
    assert "Step 3" in content

def test_lazy_loading_workspace_monitor():
    """Verify workspace monitor is not loaded until needed."""
    server = AgentHarnessMCP(repo_root=Path("/tmp/test"))
    assert server._workspace_monitor is None
    _ = server.workspace_monitor  # Access property
    assert server._workspace_monitor is not None

def test_lazy_loading_task_analyzer():
    """Verify task analyzer is not loaded until needed."""
    server = AgentHarnessMCP(repo_root=Path("/tmp/test"))
    assert server._task_analyzer is None
    _ = server.task_analyzer  # Access property
    assert server._task_analyzer is not None
```

### 2.2 Integration Tests

```python
def test_end_to_end_resource_flow():
    """
    Full flow test:
    1. Create test project
    2. Start MCP server
    3. List resources
    4. Read each new resource
    5. Verify content is useful
    """

def test_resource_caching():
    """Verify resources use caching appropriately."""
    # Read twice, verify second is faster

def test_existing_resources_unchanged():
    """Verify existing resources still work."""
    # session/status, session/resume, context/* should all still work
```

### 2.3 Performance Tests

```python
def test_first_resource_read_performance():
    """First read should be <500ms."""

def test_cached_resource_read_performance():
    """Cached read should be <10ms."""

def test_server_startup_not_impacted():
    """Server init should still be <100ms (lazy loading)."""
```

### 2.4 Rollback Criteria

- **ROLLBACK IF:** Existing resources stop working
- **ROLLBACK IF:** MCP server fails to start
- **ROLLBACK IF:** get_task_guidance tool breaks
- **ROLLBACK IF:** Server startup time increases significantly

---

## Tier 3: Validation Checklist

### 3.1 Code Quality

- [ ] Imports added in correct location
- [ ] Lazy properties follow existing pattern
- [ ] Resource URIs use consistent naming
- [ ] All new methods have docstrings
- [ ] No hardcoded values

### 3.2 Functionality

- [ ] All 5 new resources are listed
- [ ] All 5 new resources are readable
- [ ] Dependency status shows correct info
- [ ] Task analysis uses git context
- [ ] Quick start guide is coherent

### 3.3 Integration

- [ ] WorkspaceMonitor integrates correctly
- [ ] TaskAnalyzer integrates correctly
- [ ] Lazy loading prevents startup slowdown
- [ ] Existing tools still work
- [ ] Existing resources still work

### 3.4 Backwards Compatibility

- [ ] get_task_guidance tool still works
- [ ] check_session tool still works
- [ ] All orchestration tools still work
- [ ] Session persistence still works

---

## Implementation Notes

### Change Locations

1. **Imports** (top of file) - 2 lines
2. **Init variables** (lines ~61) - 2 lines
3. **Lazy properties** (after line ~103) - 14 lines
4. **list_resources** (after line ~165) - 35 lines
5. **read_resource** (after line ~184) - 12 lines
6. **_generate_quick_start_guide** (new method) - 50 lines
7. **get_task_guidance description** (lines ~196-224) - modify existing

### Existing Code Impact

- No deletions
- No structural changes
- Only additions and one description modification
- All existing functionality preserved

### File Location

```
src/agent_harness/
├── mcp_server.py  <-- MODIFY
├── workspace_monitor.py
├── task_analyzer.py
├── passive_context.py
└── models.py
```
