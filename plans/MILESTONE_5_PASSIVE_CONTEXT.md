# Milestone 5: PassiveContext Integration

**File:** `src/agent_harness/passive_context.py` (MODIFY)
**Estimated Lines:** ~80 added
**Priority:** MEDIUM

---

## Objective

Integrate WorkspaceMonitor into PassiveContextProvider to include dependency health in the codebase summary.

---

## Tier 1: Implementation Plan (Exhaustive, No Breaking Changes)

### 1.1 New Import (Add at top)

After line 6 (`from typing import Dict, List, Optional`), add:

```python
from .workspace_monitor import WorkspaceMonitor
```

### 1.2 Update __init__ (Add monitor initialization)

Modify the `__init__` method (lines 16-18). After line 18 (`self._cached_summary: Optional[str] = None`), add:

```python
        self._workspace_monitor: Optional[WorkspaceMonitor] = None
        self._cache_time: float = 0
        self._cache_ttl: float = 60.0  # seconds
```

### 1.3 Add Lazy Property for WorkspaceMonitor

Add after line 18 (after `__init__`):

```python
    @property
    def workspace_monitor(self) -> WorkspaceMonitor:
        """Lazy-load workspace monitor."""
        if self._workspace_monitor is None:
            self._workspace_monitor = WorkspaceMonitor(self.repo_root)
        return self._workspace_monitor
```

### 1.4 Update generate_codebase_summary (Add dependency health)

Modify the summary generation (around line 41-54). Replace:

```python
        summary = f"""# Codebase Summary (Auto-detected)

## Tech Stack
{tech_stack}

## Structure
{structure}

## Detected Patterns
{patterns}

## Conventions
{conventions}
"""
```

With:

```python
        # Get dependency health (quick status only - not full report)
        dep_health = self._get_dependency_health_section()

        summary = f"""# Codebase Summary (Auto-detected)

## Tech Stack
{tech_stack}

## Dependency Health
{dep_health}

## Structure
{structure}

## Detected Patterns
{patterns}

## Conventions
{conventions}
"""
```

### 1.5 Add Dependency Health Section Generator

Add as new method (after `_detect_conventions`, around line 247):

```python
    def _get_dependency_health_section(self) -> str:
        """
        Get dependency health for codebase summary.

        Uses quick status to avoid performance impact on summary generation.
        """
        try:
            quick_status = self.workspace_monitor.get_quick_status()

            # If no issues, keep it minimal
            if "✅" in quick_status or "All installed" in quick_status:
                return "✅ All dependencies installed"

            # If issues, provide brief summary with link
            return f"""{quick_status}

*Read `agent://workspace/dependency-status` for details and install commands.*"""

        except Exception:
            return "*(Could not analyze dependencies)*"
```

### 1.6 Add New Public Methods

Add after `quick_complexity_check` method (at end of file, around line 378):

```python
    def get_dependency_status(self) -> Dict:
        """
        Get current dependency status with install commands.

        Returns dict suitable for JSON serialization.
        """
        from dataclasses import asdict
        report = self.workspace_monitor.scan_dependencies()
        return asdict(report)

    def get_health_report(self) -> str:
        """
        Get workspace health report in markdown format.

        Includes dependency status, config issues, and recommendations.
        """
        return self.workspace_monitor.format_health_report()

    def invalidate_cache(self) -> None:
        """
        Invalidate all cached data.

        Call this when workspace files change significantly.
        """
        self._cached_summary = None
        self._cache_time = 0
        if self._workspace_monitor:
            self._workspace_monitor.invalidate_cache()
```

### 1.7 Add Cache Validation (Optional Enhancement)

Add method to check if cache is still valid:

```python
    def _is_cache_valid(self) -> bool:
        """Check if cached summary is still valid."""
        import time
        if self._cached_summary is None:
            return False
        if time.time() - self._cache_time > self._cache_ttl:
            return False
        # Also check if workspace monitor indicates changes
        if self._workspace_monitor and self._workspace_monitor.needs_rescan():
            return False
        return True
```

Update `generate_codebase_summary` to use cache validation:

```python
    def generate_codebase_summary(self) -> str:
        """
        Auto-detect project structure and patterns.

        Returns markdown summary that helps Claude understand the codebase.
        """
        import time

        # Check cache validity
        if self._is_cache_valid():
            return self._cached_summary

        # ... rest of existing implementation ...

        self._cached_summary = summary
        self._cache_time = time.time()
        return summary
```

---

## Tier 2: Verification Plan

### 2.1 Unit Tests

```python
# tests/test_passive_context_integration.py

def test_workspace_monitor_lazy_loaded():
    """Verify workspace monitor is not loaded until accessed."""
    provider = PassiveContextProvider(Path("/tmp/test"))
    assert provider._workspace_monitor is None
    _ = provider.workspace_monitor
    assert provider._workspace_monitor is not None

def test_codebase_summary_includes_dependencies():
    """Verify codebase summary has Dependency Health section."""
    provider = PassiveContextProvider(Path("/tmp/test"))
    summary = provider.generate_codebase_summary()
    assert "## Dependency Health" in summary

def test_get_dependency_status_returns_dict():
    """Verify get_dependency_status returns serializable dict."""
    import json
    provider = PassiveContextProvider(Path("/tmp/test"))
    status = provider.get_dependency_status()
    # Should not raise
    json.dumps(status)

def test_get_health_report_returns_markdown():
    """Verify get_health_report returns markdown string."""
    provider = PassiveContextProvider(Path("/tmp/test"))
    report = provider.get_health_report()
    assert isinstance(report, str)
    assert "#" in report  # Has markdown headers

def test_cache_invalidation():
    """Verify cache invalidation clears all caches."""
    provider = PassiveContextProvider(Path("/tmp/test"))
    # Generate summary to populate cache
    provider.generate_codebase_summary()
    assert provider._cached_summary is not None

    # Invalidate
    provider.invalidate_cache()
    assert provider._cached_summary is None

def test_cache_ttl_expiry():
    """Verify cache expires after TTL."""
    import time
    provider = PassiveContextProvider(Path("/tmp/test"))
    provider._cache_ttl = 0.1  # 100ms for testing

    provider.generate_codebase_summary()
    assert provider._is_cache_valid() is True

    time.sleep(0.15)
    assert provider._is_cache_valid() is False
```

### 2.2 Integration Tests

```python
def test_integration_with_mcp_server():
    """Verify PassiveContextProvider works with AgentHarnessMCP."""
    from agent_harness.mcp_server import AgentHarnessMCP
    server = AgentHarnessMCP(Path("/tmp/test"))
    summary = server.passive_context.generate_codebase_summary()
    assert "Dependency Health" in summary

def test_dependency_health_graceful_failure():
    """Verify dependency health doesn't break summary on error."""
    # Create provider with invalid path
    provider = PassiveContextProvider(Path("/nonexistent"))
    summary = provider.generate_codebase_summary()
    # Should still return summary, just with error message
    assert "Codebase Summary" in summary
```

### 2.3 Performance Tests

```python
def test_summary_generation_performance():
    """Summary generation should be <500ms including dependency check."""

def test_cached_summary_performance():
    """Cached summary should be <10ms."""

def test_lazy_loading_no_impact_on_init():
    """PassiveContextProvider init should be <10ms."""
```

### 2.4 Rollback Criteria

- **ROLLBACK IF:** generate_codebase_summary fails
- **ROLLBACK IF:** Circular import with workspace_monitor
- **ROLLBACK IF:** Performance degrades significantly
- **ROLLBACK IF:** Existing functionality breaks

---

## Tier 3: Validation Checklist

### 3.1 Code Quality

- [ ] Import added in correct location
- [ ] Lazy property follows existing pattern
- [ ] New methods have docstrings
- [ ] Type hints on all new methods
- [ ] Exception handling in _get_dependency_health_section

### 3.2 Functionality

- [ ] Codebase summary includes dependency health
- [ ] Dependency health section is concise
- [ ] get_dependency_status returns valid dict
- [ ] get_health_report returns valid markdown
- [ ] Cache invalidation works

### 3.3 Integration

- [ ] Works with existing mcp_server.py
- [ ] WorkspaceMonitor lazy loading works
- [ ] No circular imports
- [ ] JSON serialization works

### 3.4 Backwards Compatibility

- [ ] Existing generate_codebase_summary still works
- [ ] assess_task_complexity unchanged
- [ ] suggest_scopes unchanged
- [ ] quick_complexity_check unchanged

---

## Implementation Notes

### Change Locations

1. **Import** (line ~7) - 1 line
2. **__init__ variables** (line ~18) - 3 lines
3. **workspace_monitor property** (after __init__) - 6 lines
4. **generate_codebase_summary** (line ~41) - modify existing
5. **_get_dependency_health_section** (new method) - 15 lines
6. **New public methods** (end of file) - 30 lines
7. **_is_cache_valid** (new method) - 10 lines

### Existing Code Impact

- Summary format changes (adds Dependency Health section)
- All existing public methods unchanged
- All existing functionality preserved

### File Location

```
src/agent_harness/
├── passive_context.py  <-- MODIFY
├── workspace_monitor.py
├── task_analyzer.py
├── mcp_server.py
└── models.py
```

### Order Dependencies

- Requires Milestone 1 (workspace_monitor.py) to be complete
- Can run in parallel with Milestone 4 (mcp_server.py)
