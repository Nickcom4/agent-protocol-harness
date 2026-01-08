# Milestone 2: TaskAnalyzer Implementation

**File:** `src/agent_harness/task_analyzer.py` (NEW)
**Estimated Lines:** ~300
**Priority:** HIGH

---

## Objective

Create a lightweight task analysis system that infers task context from git state and workspace signals, providing actionable guidance without requiring explicit tool calls.

---

## Tier 1: Implementation Plan (Exhaustive, No Breaking Changes)

### 1.1 Core Classes

```python
from dataclasses import dataclass
from typing import List, Optional, Dict
from pathlib import Path

@dataclass
class ComplexitySignals:
    """Signals extracted from task analysis."""
    multi_system_count: int
    scope_keywords: List[str]
    affected_files_estimate: int
    has_auth: bool
    has_payments: bool
    total_score: int

@dataclass
class ApproachRecommendation:
    """Recommended approach for task execution."""
    approach: str  # "direct", "checkpointed", "orchestrated"
    reason: str
    steps: List[str]
    warnings: List[str]
```

### 1.2 TaskAnalyzer Class Structure

```python
class TaskAnalyzer:
    """
    Lightweight task analysis without requiring tool calls.

    Uses heuristics to infer task context from:
    1. Git branch name
    2. Recent commit messages
    3. Modified files
    4. Resource URI parameters
    """

    def __init__(self, repo_root: Path, passive_context: 'PassiveContextProvider'):
        self.repo_root = repo_root
        self.passive_context = passive_context
        self._git_info: Optional[Dict] = None

    # Primary analysis methods
    def analyze_current_context(self) -> str  # Returns markdown
    def extract_complexity_signals(self, task: str = "") -> ComplexitySignals
    def suggest_approach(self, signals: ComplexitySignals) -> ApproachRecommendation
    def generate_verification_checklist(self) -> str  # Markdown

    # Context extraction
    def _extract_from_git(self) -> Dict
    def _extract_from_branch_name(self) -> Optional[str]
    def _extract_from_recent_commits(self) -> List[str]
    def _extract_from_modified_files(self) -> List[str]

    # Inference
    def _infer_task_type(self, task: str) -> str
    def _infer_affected_systems(self, task: str) -> List[str]
```

### 1.3 Git Context Extraction

```python
def _extract_from_git(self) -> Dict:
    """Extract all relevant git context."""
    if self._git_info is not None:
        return self._git_info

    info = {
        "branch": "",
        "recent_commits": [],
        "modified_files": [],
        "untracked_files": [],
        "task_hint": None,
    }

    try:
        # Current branch
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            timeout=5
        )
        info["branch"] = result.stdout.strip()

        # Recent commits (last 5)
        result = subprocess.run(
            ["git", "log", "--oneline", "-5"],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            timeout=5
        )
        info["recent_commits"] = result.stdout.strip().split("\n")

        # Modified files (staged + unstaged)
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            timeout=5
        )
        for line in result.stdout.strip().split("\n"):
            if line:
                status = line[:2]
                filepath = line[3:].strip()
                if status.strip():
                    info["modified_files"].append(filepath)
                else:
                    info["untracked_files"].append(filepath)

    except subprocess.TimeoutExpired:
        pass
    except Exception:
        pass

    self._git_info = info
    return info
```

### 1.4 Branch Name Parsing

```python
def _extract_from_branch_name(self) -> Optional[str]:
    """
    Parse task hint from branch name.

    Common patterns:
    - feature/add-auth → "add auth"
    - fix/login-bug → "fix login bug"
    - refactor/api-cleanup → "refactor api cleanup"
    """
    git_info = self._extract_from_git()
    branch = git_info.get("branch", "")

    if not branch or branch in ["main", "master", "develop", "dev"]:
        return None

    # Remove common prefixes
    prefixes = ["feature/", "fix/", "bugfix/", "hotfix/", "refactor/", "chore/", "docs/"]
    for prefix in prefixes:
        if branch.startswith(prefix):
            branch = branch[len(prefix):]
            break

    # Convert kebab-case/snake_case to words
    task_hint = branch.replace("-", " ").replace("_", " ")

    return task_hint if task_hint else None
```

### 1.5 Complexity Signal Extraction

```python
def extract_complexity_signals(self, task: str = "") -> ComplexitySignals:
    """
    Extract complexity signals from task and git context.

    Scoring:
    - Multi-system keywords (frontend, backend, database): +2 each
    - Large scope (refactor, migrate, architecture): +3
    - Auth/payments: +2
    - Modified files > 10: +2
    - AI session branch: +1 (implies complex work in progress)
    """
    # Combine task with git context
    git_info = self._extract_from_git()
    branch_hint = self._extract_from_branch_name() or ""

    all_context = f"{task} {branch_hint} {' '.join(git_info.get('recent_commits', []))}".lower()

    # Count multi-system keywords
    multi_system_keywords = ["frontend", "backend", "database", "api", "server", "client", "ui", "db"]
    systems_mentioned = [w for w in multi_system_keywords if w in all_context]
    multi_system_count = len(set(systems_mentioned))

    # Check scope keywords
    scope_keywords = []
    large_scope_words = ["refactor", "migrate", "restructure", "architecture", "redesign", "overhaul"]
    for word in large_scope_words:
        if word in all_context:
            scope_keywords.append(word)

    # Auth/payments detection
    has_auth = any(w in all_context for w in ["auth", "login", "password", "session", "jwt", "oauth"])
    has_payments = any(w in all_context for w in ["payment", "billing", "stripe", "checkout", "subscription"])

    # Estimate affected files
    modified = len(git_info.get("modified_files", []))
    affected_files_estimate = max(modified, self._estimate_files_from_task(task))

    # Calculate total score
    score = 0
    score += multi_system_count * 2
    score += len(scope_keywords) * 3
    score += 2 if has_auth else 0
    score += 2 if has_payments else 0
    score += 2 if affected_files_estimate > 10 else 0
    score += 1 if git_info.get("branch", "").startswith("ai/") else 0

    return ComplexitySignals(
        multi_system_count=multi_system_count,
        scope_keywords=scope_keywords,
        affected_files_estimate=affected_files_estimate,
        has_auth=has_auth,
        has_payments=has_payments,
        total_score=score
    )

def _estimate_files_from_task(self, task: str) -> int:
    """Estimate file count from task description."""
    task_lower = task.lower()

    # Direct mentions
    if "file" in task_lower:
        # Try to extract number
        import re
        match = re.search(r'(\d+)\s*files?', task_lower)
        if match:
            return int(match.group(1))

    # Heuristics
    if any(w in task_lower for w in ["entire", "all", "whole", "complete"]):
        return 20

    if any(w in task_lower for w in ["refactor", "migrate", "restructure"]):
        return 15

    if any(w in task_lower for w in ["component", "module", "service"]):
        return 5

    return 3  # Default small
```

### 1.6 Approach Recommendation

```python
def suggest_approach(self, signals: ComplexitySignals) -> ApproachRecommendation:
    """
    Recommend execution approach based on complexity signals.

    Thresholds:
    - < 3: Direct execution (simple, single-system)
    - 3-4: Checkpointed (moderate complexity)
    - >= 5: Orchestrated (complex, multi-system)
    """
    score = signals.total_score
    systems = signals.multi_system_count

    if score < 3 and systems <= 1:
        return ApproachRecommendation(
            approach="direct",
            reason="Simple task - single system, low complexity",
            steps=[
                "Make changes directly",
                "Run tests",
                "Commit when verified"
            ],
            warnings=[]
        )

    elif score < 5 or systems <= 2:
        warnings = []
        if signals.has_auth:
            warnings.append("Auth changes require careful testing")
        if signals.has_payments:
            warnings.append("Payment code requires extra verification")

        return ApproachRecommendation(
            approach="checkpointed",
            reason="Moderate complexity - consider creating checkpoints",
            steps=[
                "Break work into logical steps",
                "Commit after each step",
                "Run tests incrementally",
                "Consider feature flag if risky"
            ],
            warnings=warnings
        )

    else:
        return ApproachRecommendation(
            approach="orchestrated",
            reason=f"Complex task - {systems} systems, score={score}",
            steps=[
                "Use analyze_and_plan to create agent structure",
                "Define clear scope boundaries per agent",
                "Execute with checkpoint commits",
                "Run verification per agent",
                "Finalize with merge or keep"
            ],
            warnings=[
                "Cross-system changes require isolation",
                "Consider rollback strategy"
            ] + (["Auth changes detected - verify security"] if signals.has_auth else [])
        )
```

### 1.7 Main Analysis Output

```python
def analyze_current_context(self) -> str:
    """
    Generate markdown analysis of current task context.

    Returns actionable guidance without requiring tool call.
    """
    git_info = self._extract_from_git()
    branch_hint = self._extract_from_branch_name()
    signals = self.extract_complexity_signals(branch_hint or "")
    recommendation = self.suggest_approach(signals)

    # Infer task type
    task_type = self._infer_task_type(branch_hint or "")

    # Build markdown
    lines = ["# Task Analysis"]

    # Task detection
    if branch_hint:
        lines.append(f"\n**Detected Task:** \"{branch_hint}\"")
        lines.append(f"**Inferred from:** Git branch `{git_info.get('branch', 'unknown')}`")
    else:
        lines.append("\n**Task:** Not detected from git context")
        lines.append("*Provide task description via get_task_guidance tool for better analysis*")

    lines.append(f"\n**Task Type:** {task_type}")

    # Complexity assessment
    lines.append("\n## Complexity Assessment")
    lines.append(f"- **Complexity Score:** {signals.total_score}/10")
    lines.append(f"- **Systems Affected:** {signals.multi_system_count}")
    lines.append(f"- **Expected Files:** ~{signals.affected_files_estimate}")

    if signals.scope_keywords:
        lines.append(f"- **Scope Keywords:** {', '.join(signals.scope_keywords)}")
    if signals.has_auth:
        lines.append("- **Auth Component:** Yes (security-sensitive)")
    if signals.has_payments:
        lines.append("- **Payment Component:** Yes (extra verification needed)")

    # Recommendation
    lines.append("\n## Recommended Approach")
    if recommendation.approach == "direct":
        lines.append("✅ **Direct execution** - Simple task, proceed directly")
    elif recommendation.approach == "checkpointed":
        lines.append("📌 **Checkpointed execution** - Create commits at logical points")
    else:
        lines.append("🔄 **Orchestrated execution** - Use multi-agent workflow")

    lines.append(f"\n**Why?** {recommendation.reason}")

    lines.append("\n### Suggested Steps")
    for i, step in enumerate(recommendation.steps, 1):
        lines.append(f"{i}. {step}")

    if recommendation.warnings:
        lines.append("\n### Warnings")
        for warning in recommendation.warnings:
            lines.append(f"⚠️ {warning}")

    # Modified files context
    if git_info.get("modified_files"):
        lines.append("\n## Files In Progress")
        for f in git_info["modified_files"][:10]:
            lines.append(f"- `{f}`")
        if len(git_info["modified_files"]) > 10:
            lines.append(f"- ... and {len(git_info['modified_files']) - 10} more")

    # Cross-reference
    lines.append("\n---")
    lines.append("💡 Read `agent://workspace/dependency-status` for missing packages")
    lines.append("💡 Read `agent://guidance/verification-checklist` for test steps")

    return "\n".join(lines)

def _infer_task_type(self, task: str) -> str:
    """Infer task type from keywords."""
    task_lower = task.lower()

    if any(w in task_lower for w in ["fix", "bug", "error", "issue"]):
        return "Bug fix"
    elif any(w in task_lower for w in ["add", "new", "create", "implement"]):
        return "Feature implementation"
    elif any(w in task_lower for w in ["refactor", "cleanup", "improve"]):
        return "Refactoring"
    elif any(w in task_lower for w in ["test", "spec"]):
        return "Testing"
    elif any(w in task_lower for w in ["doc", "readme"]):
        return "Documentation"
    elif any(w in task_lower for w in ["update", "upgrade", "version"]):
        return "Update/upgrade"
    else:
        return "General task"
```

### 1.8 Verification Checklist Generation

```python
def generate_verification_checklist(self) -> str:
    """
    Generate verification checklist based on task analysis.

    Returns markdown checklist.
    """
    signals = self.extract_complexity_signals()
    git_info = self._extract_from_git()

    lines = ["# Verification Checklist"]

    # Basic checks
    lines.append("\n## Required")
    lines.append("- [ ] All existing tests pass")
    lines.append("- [ ] No linter errors")
    lines.append("- [ ] Code compiles/runs without errors")

    # Type-specific checks
    if signals.has_auth:
        lines.append("\n## Security (Auth)")
        lines.append("- [ ] Passwords are hashed (never stored plain)")
        lines.append("- [ ] Tokens have expiration")
        lines.append("- [ ] Failed login attempts are rate-limited")
        lines.append("- [ ] Session invalidation works")

    if signals.has_payments:
        lines.append("\n## Payments")
        lines.append("- [ ] Test mode used for development")
        lines.append("- [ ] No real card numbers in logs")
        lines.append("- [ ] Error handling for declined payments")
        lines.append("- [ ] Webhook signatures verified")

    # Multi-system checks
    if signals.multi_system_count >= 2:
        lines.append("\n## Cross-System")
        lines.append("- [ ] API contracts match between systems")
        lines.append("- [ ] Database migrations applied")
        lines.append("- [ ] Frontend reflects backend changes")

    # File-specific checks
    modified = git_info.get("modified_files", [])
    if modified:
        lines.append("\n## Changed Files Verification")

        # Group by type
        tests_modified = [f for f in modified if "test" in f.lower()]
        if tests_modified:
            lines.append("- [ ] Modified tests still pass:")
            for t in tests_modified[:5]:
                lines.append(f"  - `{t}`")

        api_modified = [f for f in modified if any(x in f.lower() for x in ["api", "route", "endpoint"])]
        if api_modified:
            lines.append("- [ ] API endpoints tested:")
            for a in api_modified[:5]:
                lines.append(f"  - `{a}`")

    lines.append("\n## Manual Verification")
    lines.append("- [ ] Feature works as expected in browser/CLI")
    lines.append("- [ ] Edge cases handled gracefully")
    lines.append("- [ ] No console errors/warnings")

    return "\n".join(lines)
```

---

## Tier 2: Verification Plan

### 2.1 Unit Tests

```python
# tests/test_task_analyzer.py

def test_branch_name_parsing_feature():
    """Given: branch 'feature/add-auth'
       When: _extract_from_branch_name()
       Then: returns 'add auth'"""

def test_branch_name_parsing_fix():
    """Given: branch 'fix/login-bug'
       When: _extract_from_branch_name()
       Then: returns 'login bug'"""

def test_branch_name_main_branch():
    """Given: branch 'main'
       When: _extract_from_branch_name()
       Then: returns None"""

def test_complexity_simple_task():
    """Given: task 'fix typo'
       When: extract_complexity_signals()
       Then: score < 3"""

def test_complexity_multi_system():
    """Given: task 'add auth to frontend and backend'
       When: extract_complexity_signals()
       Then: score >= 5, multi_system_count >= 2"""

def test_approach_direct():
    """Given: score=2, systems=1
       When: suggest_approach()
       Then: approach='direct'"""

def test_approach_checkpointed():
    """Given: score=4, systems=2
       When: suggest_approach()
       Then: approach='checkpointed'"""

def test_approach_orchestrated():
    """Given: score=6, systems=3
       When: suggest_approach()
       Then: approach='orchestrated'"""
```

### 2.2 Integration Tests

```python
def test_full_analysis_with_git_context():
    """Create git repo, make commits, verify analysis output."""

def test_verification_checklist_with_auth():
    """Verify auth-specific checks appear when auth detected."""

def test_markdown_output_format():
    """Verify output is valid markdown with expected sections."""
```

### 2.3 Performance Tests

```python
def test_analysis_performance():
    """Analysis should complete in <200ms."""

def test_git_operations_timeout():
    """Git operations should timeout gracefully at 5s."""
```

### 2.4 Rollback Criteria

- **ROLLBACK IF:** Analysis fails silently (should handle missing git gracefully)
- **ROLLBACK IF:** Git operations hang indefinitely
- **ROLLBACK IF:** Memory usage spikes during analysis

---

## Tier 3: Validation Checklist

### 3.1 Code Quality

- [ ] All methods have docstrings
- [ ] Type hints on all public methods
- [ ] No circular imports
- [ ] Subprocess calls have timeouts
- [ ] Exception handling for all external calls

### 3.2 Functionality

- [ ] Branch name parsing works for all prefixes
- [ ] Complexity scoring is consistent
- [ ] Approach recommendations make sense
- [ ] Git context extraction is robust

### 3.3 Integration

- [ ] Works when git is not installed
- [ ] Works in non-git directories
- [ ] PassiveContextProvider integration correct
- [ ] Lazy loading pattern matches existing

### 3.4 Edge Cases

- [ ] Empty repository (no commits)
- [ ] Detached HEAD state
- [ ] Very long branch names
- [ ] Non-ASCII branch names
- [ ] Missing .git directory

---

## Implementation Notes

### No Breaking Changes

This is a NEW file with no modifications to existing code.

### Dependencies

- `subprocess` for git operations
- `passive_context.py` for codebase context
- `dataclasses` for signal structures

### File Location

```
src/agent_harness/
├── task_analyzer.py  <-- NEW
├── workspace_monitor.py
├── mcp_server.py
├── passive_context.py
└── models.py
```
