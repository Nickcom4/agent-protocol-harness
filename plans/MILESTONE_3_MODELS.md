# Milestone 3: Models Additions

**File:** `src/agent_harness/models.py` (MODIFY - ADD to end)
**Estimated Lines:** ~100 added
**Priority:** MEDIUM (required before Milestone 4)

---

## Objective

Add dataclass models for dependency detection and task analysis. These provide structured data for WorkspaceMonitor and TaskAnalyzer.

---

## Tier 1: Implementation Plan (Exhaustive, No Breaking Changes)

### 1.1 New Dataclasses to Add

Add to **end of file** (after `ExecutionPlan` class):

```python
# ============================================================
# Dependency Detection Models (for WorkspaceMonitor)
# ============================================================

@dataclass
class MissingPackage:
    """A dependency that's declared but not installed."""
    name: str
    ecosystem: str  # "npm", "pip", "gem", "go", "cargo"
    install_command: str  # Ready-to-run command, e.g., "npm install express"
    detected_from: str  # Source file where reference was found, e.g., "package.json"
    severity: str = "warning"  # "critical", "warning", "info"

    def __post_init__(self):
        """Validate severity."""
        valid_severities = {"critical", "warning", "info"}
        if self.severity not in valid_severities:
            raise ValueError(f"severity must be one of {valid_severities}")


@dataclass
class OutdatedPackage:
    """A dependency with available updates."""
    name: str
    ecosystem: str
    current_version: str
    latest_version: str
    update_command: str  # e.g., "npm update express"

    @property
    def is_major_update(self) -> bool:
        """Check if this is a major version bump."""
        try:
            current_major = int(self.current_version.split('.')[0].lstrip('v^~'))
            latest_major = int(self.latest_version.split('.')[0].lstrip('v^~'))
            return latest_major > current_major
        except (ValueError, IndexError):
            return False


@dataclass
class Conflict:
    """Version conflict between dependencies."""
    package: str
    required_by: list[str]  # List of packages requiring this
    conflicting_versions: list[str]  # The different versions required
    resolution_hint: str = ""  # Optional hint for resolution


@dataclass
class DependencyReport:
    """Comprehensive dependency analysis report."""
    missing: list[MissingPackage] = field(default_factory=list)
    outdated: list[OutdatedPackage] = field(default_factory=list)
    unused: list[str] = field(default_factory=list)  # Declared but never imported
    conflicts: list[Conflict] = field(default_factory=list)
    health_score: int = 100  # 0-100

    @property
    def has_critical(self) -> bool:
        """Check if any critical issues exist."""
        return any(p.severity == "critical" for p in self.missing)

    @property
    def critical_count(self) -> int:
        """Count of critical missing packages."""
        return sum(1 for p in self.missing if p.severity == "critical")

    @property
    def warning_count(self) -> int:
        """Count of warning-level missing packages."""
        return sum(1 for p in self.missing if p.severity == "warning")

    def get_install_commands_by_ecosystem(self) -> dict[str, list[str]]:
        """Group install commands by ecosystem for batch execution."""
        by_ecosystem: dict[str, list[str]] = {}
        for pkg in self.missing:
            if pkg.ecosystem not in by_ecosystem:
                by_ecosystem[pkg.ecosystem] = []
            by_ecosystem[pkg.ecosystem].append(pkg.name)
        return by_ecosystem

    def format_quick_install(self) -> str:
        """Generate combined install command."""
        lines = []
        by_eco = self.get_install_commands_by_ecosystem()

        if "npm" in by_eco:
            lines.append(f"npm install {' '.join(by_eco['npm'])}")
        if "pip" in by_eco:
            lines.append(f"pip install {' '.join(by_eco['pip'])}")
        if "go" in by_eco:
            for pkg in by_eco["go"]:
                lines.append(f"go get {pkg}")
        if "cargo" in by_eco:
            for pkg in by_eco["cargo"]:
                lines.append(f"cargo add {pkg}")
        if "gem" in by_eco:
            lines.append(f"gem install {' '.join(by_eco['gem'])}")

        return "\n".join(lines)


# ============================================================
# Task Analysis Models (for TaskAnalyzer)
# ============================================================

@dataclass
class ComplexitySignals:
    """Signals extracted from task complexity analysis."""
    multi_system_count: int = 0  # Number of systems mentioned (frontend, backend, etc.)
    scope_keywords: list[str] = field(default_factory=list)  # refactor, migrate, etc.
    affected_files_estimate: int = 0
    has_auth: bool = False
    has_payments: bool = False
    total_score: int = 0

    @property
    def is_simple(self) -> bool:
        return self.total_score < 3 and self.multi_system_count <= 1

    @property
    def is_complex(self) -> bool:
        return self.total_score >= 5 or self.multi_system_count >= 3


@dataclass
class ApproachRecommendation:
    """Recommended approach for task execution."""
    approach: str  # "direct", "checkpointed", "orchestrated"
    reason: str
    steps: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self):
        """Validate approach."""
        valid_approaches = {"direct", "checkpointed", "orchestrated"}
        if self.approach not in valid_approaches:
            raise ValueError(f"approach must be one of {valid_approaches}")


@dataclass
class TaskAnalysis:
    """Complete analysis of a coding task."""
    task_description: str = ""
    task_type: str = ""  # "feature", "bugfix", "refactor", "test", "docs"
    inferred_from: str = ""  # "git branch", "user input", "modified files"
    complexity: ComplexitySignals = field(default_factory=ComplexitySignals)
    recommendation: ApproachRecommendation = field(
        default_factory=lambda: ApproachRecommendation(
            approach="direct",
            reason="Default recommendation"
        )
    )
    verification_steps: list[str] = field(default_factory=list)
    potential_pitfalls: list[str] = field(default_factory=list)
    affected_files: list[str] = field(default_factory=list)


# ============================================================
# Package Manager Configuration (for WorkspaceMonitor)
# ============================================================

@dataclass
class PackageManagerConfig:
    """Configuration for a package manager ecosystem."""
    name: str  # "npm", "pip", etc.
    manifest_files: list[str]  # ["package.json"]
    lock_files: list[str] = field(default_factory=list)  # ["package-lock.json"]
    install_dir: str = ""  # "node_modules"
    install_command_template: str = ""  # "{manager} install {package}"
    check_command: str = ""  # Command to check if package installed


# Predefined package manager configurations
NPM_CONFIG = PackageManagerConfig(
    name="npm",
    manifest_files=["package.json"],
    lock_files=["package-lock.json", "yarn.lock", "pnpm-lock.yaml"],
    install_dir="node_modules",
    install_command_template="npm install {package}",
    check_command="npm list {package}"
)

PIP_CONFIG = PackageManagerConfig(
    name="pip",
    manifest_files=["pyproject.toml", "requirements.txt", "setup.py"],
    lock_files=["uv.lock", "poetry.lock", "Pipfile.lock"],
    install_dir=".venv/lib",
    install_command_template="pip install {package}",
    check_command="pip show {package}"
)

GO_CONFIG = PackageManagerConfig(
    name="go",
    manifest_files=["go.mod"],
    lock_files=["go.sum"],
    install_dir="",
    install_command_template="go get {package}",
    check_command="go list -m {package}"
)

CARGO_CONFIG = PackageManagerConfig(
    name="cargo",
    manifest_files=["Cargo.toml"],
    lock_files=["Cargo.lock"],
    install_dir="target",
    install_command_template="cargo add {package}",
    check_command="cargo tree -p {package}"
)

GEM_CONFIG = PackageManagerConfig(
    name="gem",
    manifest_files=["Gemfile"],
    lock_files=["Gemfile.lock"],
    install_dir="vendor/bundle",
    install_command_template="gem install {package}",
    check_command="gem list {package}"
)

# Export all configs
PACKAGE_MANAGER_CONFIGS = {
    "npm": NPM_CONFIG,
    "pip": PIP_CONFIG,
    "go": GO_CONFIG,
    "cargo": CARGO_CONFIG,
    "gem": GEM_CONFIG,
}
```

---

## Tier 2: Verification Plan

### 2.1 Unit Tests

```python
# tests/test_models_dependency.py

def test_missing_package_creation():
    """Verify MissingPackage dataclass works correctly."""
    pkg = MissingPackage(
        name="express",
        ecosystem="npm",
        install_command="npm install express",
        detected_from="package.json"
    )
    assert pkg.severity == "warning"  # Default

def test_missing_package_invalid_severity():
    """Verify severity validation works."""
    with pytest.raises(ValueError):
        MissingPackage(
            name="test",
            ecosystem="npm",
            install_command="npm install test",
            detected_from="package.json",
            severity="invalid"
        )

def test_outdated_package_major_update():
    """Verify major update detection."""
    pkg = OutdatedPackage(
        name="react",
        ecosystem="npm",
        current_version="17.0.0",
        latest_version="18.2.0",
        update_command="npm update react"
    )
    assert pkg.is_major_update is True

def test_dependency_report_critical_count():
    """Verify critical count calculation."""
    report = DependencyReport(
        missing=[
            MissingPackage("a", "npm", "npm i a", "package.json", "critical"),
            MissingPackage("b", "npm", "npm i b", "package.json", "warning"),
            MissingPackage("c", "npm", "npm i c", "package.json", "critical"),
        ]
    )
    assert report.critical_count == 2
    assert report.warning_count == 1

def test_dependency_report_quick_install():
    """Verify batch install command generation."""
    report = DependencyReport(
        missing=[
            MissingPackage("express", "npm", "npm i express", "package.json"),
            MissingPackage("flask", "pip", "pip i flask", "requirements.txt"),
        ]
    )
    install = report.format_quick_install()
    assert "npm install express" in install
    assert "pip install flask" in install

def test_complexity_signals_is_simple():
    """Verify simple task detection."""
    signals = ComplexitySignals(total_score=2, multi_system_count=1)
    assert signals.is_simple is True

def test_complexity_signals_is_complex():
    """Verify complex task detection."""
    signals = ComplexitySignals(total_score=6, multi_system_count=3)
    assert signals.is_complex is True

def test_approach_recommendation_validation():
    """Verify approach validation."""
    with pytest.raises(ValueError):
        ApproachRecommendation(approach="invalid", reason="test")
```

### 2.2 Integration Tests

```python
def test_models_import():
    """Verify all new models can be imported from models.py."""
    from agent_harness.models import (
        MissingPackage,
        OutdatedPackage,
        Conflict,
        DependencyReport,
        ComplexitySignals,
        ApproachRecommendation,
        TaskAnalysis,
        PackageManagerConfig,
        PACKAGE_MANAGER_CONFIGS
    )

def test_models_serialization():
    """Verify models can be serialized to JSON (for MCP resources)."""
    import json
    from dataclasses import asdict

    report = DependencyReport(
        missing=[MissingPackage("x", "npm", "npm i x", "package.json")],
        health_score=85
    )
    # Should not raise
    json.dumps(asdict(report))
```

### 2.3 Rollback Criteria

- **ROLLBACK IF:** Existing model imports break
- **ROLLBACK IF:** Circular import introduced
- **ROLLBACK IF:** Any existing tests fail

---

## Tier 3: Validation Checklist

### 3.1 Code Quality

- [ ] Added to END of file (no changes to existing code)
- [ ] Clear section comments
- [ ] All dataclasses have docstrings
- [ ] Type hints on all fields
- [ ] Default values use `field(default_factory=...)` for mutable types

### 3.2 Functionality

- [ ] MissingPackage severity validation works
- [ ] OutdatedPackage major update detection works
- [ ] DependencyReport aggregation methods work
- [ ] ComplexitySignals properties compute correctly
- [ ] ApproachRecommendation validation works

### 3.3 Integration

- [ ] All imports from `models.py` still work
- [ ] No circular imports
- [ ] JSON serialization works (for MCP resources)
- [ ] WorkspaceMonitor can use these models
- [ ] TaskAnalyzer can use these models

### 3.4 Backwards Compatibility

- [ ] Existing Contract class unchanged
- [ ] Existing Signal class unchanged
- [ ] Existing ExecutionPlan class unchanged
- [ ] All existing imports still work

---

## Implementation Notes

### No Breaking Changes

- Only ADD to end of file
- No modifications to existing classes
- No changes to existing imports

### File Location

```
src/agent_harness/
├── models.py  <-- MODIFY (add to end)
├── workspace_monitor.py
├── task_analyzer.py
├── mcp_server.py
└── passive_context.py
```

### Order of Operations

This milestone should be completed BEFORE Milestone 1 and 2 start importing these models.
