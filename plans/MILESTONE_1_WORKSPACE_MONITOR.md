# Milestone 1: WorkspaceMonitor Implementation

**File:** `src/agent_harness/workspace_monitor.py` (NEW)
**Estimated Lines:** ~400
**Priority:** HIGH

---

## Objective

Create a real-time workspace analyzer that detects missing dependencies and generates install commands. This enables the MCP to proactively guide Claude on dependency issues without requiring explicit tool calls.

---

## Tier 1: Implementation Plan (Exhaustive, No Breaking Changes)

### 1.1 Core Classes and Data Structures

```python
# Import from models.py (to be added in Milestone 3)
from .models import DependencyReport, MissingPackage, OutdatedPackage, Conflict

@dataclass
class PackageManager:
    """Metadata for a package manager ecosystem."""
    name: str                    # "npm", "pip", "go", etc.
    manifest_file: str           # "package.json", "pyproject.toml"
    lock_file: Optional[str]     # "package-lock.json", "uv.lock"
    install_dir: str             # "node_modules", ".venv/lib"
    install_command_template: str # "npm install {package}", "pip install {package}"
```

### 1.2 WorkspaceMonitor Class Structure

```python
class WorkspaceMonitor:
    """
    Real-time workspace dependency analyzer.

    Features:
    - Scans package manifests (package.json, pyproject.toml, etc.)
    - Detects missing packages by checking install directories
    - Generates ready-to-run install commands
    - Calculates workspace health score
    - Caches results with TTL for performance
    """

    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self._cache: Optional[DependencyReport] = None
        self._cache_time: float = 0
        self._cache_ttl: float = 60.0  # seconds
        self._file_mtimes: Dict[str, float] = {}  # For incremental scanning

    # Core scanning methods
    def scan_dependencies(self) -> DependencyReport
    def detect_missing_packages(self) -> List[MissingPackage]
    def suggest_install_commands(self) -> List[str]
    def calculate_health_score(self, report: DependencyReport) -> int

    # Formatting methods
    def format_dependency_report(self) -> str  # Markdown output
    def format_health_report(self) -> str
    def get_quick_status(self) -> str  # One-line summary

    # Caching methods
    def needs_rescan(self) -> bool
    def invalidate_cache(self) -> None
```

### 1.3 Package Manager Detection

Supported ecosystems in priority order:
1. **npm/yarn/pnpm** (JavaScript/TypeScript)
   - Manifest: `package.json`
   - Install dir: `node_modules/`
   - Detection: Check if package dir exists in node_modules

2. **pip/uv** (Python)
   - Manifest: `pyproject.toml`, `requirements.txt`
   - Install dir: `.venv/lib/python*/site-packages/` or system site-packages
   - Detection: Use `importlib.util.find_spec()` or check site-packages

3. **go modules** (Go)
   - Manifest: `go.mod`
   - Install dir: `$GOPATH/pkg/mod/`
   - Detection: Check go.sum for resolved versions

4. **cargo** (Rust)
   - Manifest: `Cargo.toml`
   - Install dir: `target/`
   - Detection: Check Cargo.lock for resolved deps

5. **gem** (Ruby)
   - Manifest: `Gemfile`
   - Install dir: `vendor/bundle/`
   - Detection: Check Gemfile.lock

### 1.4 Dependency Detection Algorithm

```python
def scan_dependencies(self) -> DependencyReport:
    """
    Main scanning algorithm.

    Steps:
    1. Identify which package managers are in use
    2. For each ecosystem:
       a. Parse declared dependencies from manifest
       b. Check if each dependency is installed
       c. Cross-reference imports in source files (optional)
       d. Generate install commands for missing packages
    3. Calculate severity levels:
       - Critical: Package imported in code but not installed
       - Warning: Package in manifest but not installed
       - Info: Available updates
    4. Build comprehensive report
    """
```

### 1.5 npm/JavaScript Implementation

```python
def _scan_npm(self) -> Tuple[List[MissingPackage], List[OutdatedPackage]]:
    """Scan JavaScript/TypeScript dependencies."""
    pkg_json = self.repo_root / "package.json"
    if not pkg_json.exists():
        return [], []

    try:
        data = json.loads(pkg_json.read_text())
    except json.JSONDecodeError:
        return [], []

    missing = []
    deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
    node_modules = self.repo_root / "node_modules"

    for name, version in deps.items():
        pkg_dir = node_modules / name
        if not pkg_dir.exists():
            missing.append(MissingPackage(
                name=name,
                ecosystem="npm",
                install_command=f"npm install {name}",
                detected_from="package.json",
                severity="warning"
            ))

    return missing, []
```

### 1.6 Python Implementation

```python
def _scan_python(self) -> Tuple[List[MissingPackage], List[OutdatedPackage]]:
    """Scan Python dependencies."""
    missing = []

    # Check pyproject.toml
    pyproject = self.repo_root / "pyproject.toml"
    if pyproject.exists():
        try:
            import tomllib
            data = tomllib.loads(pyproject.read_text())
            deps = data.get("project", {}).get("dependencies", [])

            for dep in deps:
                # Parse "package>=version" format
                name = re.split(r'[<>=!~]', dep)[0].strip()
                if not self._is_python_package_installed(name):
                    missing.append(MissingPackage(
                        name=name,
                        ecosystem="pip",
                        install_command=f"pip install {name}",
                        detected_from="pyproject.toml",
                        severity="warning"
                    ))
        except Exception:
            pass

    # Check requirements.txt
    requirements = self.repo_root / "requirements.txt"
    if requirements.exists():
        for line in requirements.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                name = re.split(r'[<>=!~]', line)[0].strip()
                if not self._is_python_package_installed(name):
                    missing.append(MissingPackage(
                        name=name,
                        ecosystem="pip",
                        install_command=f"pip install {name}",
                        detected_from="requirements.txt",
                        severity="warning"
                    ))

    return missing, []

def _is_python_package_installed(self, name: str) -> bool:
    """Check if a Python package is installed."""
    import importlib.util
    # Handle package name vs import name differences
    import_name = name.replace("-", "_").lower()
    return importlib.util.find_spec(import_name) is not None
```

### 1.7 Source Import Cross-Reference (Enhancement)

```python
def _cross_reference_imports(self, missing: List[MissingPackage]) -> List[MissingPackage]:
    """
    Upgrade severity to 'critical' if package is imported in source code.

    Scans .py, .js, .ts files for import statements.
    """
    critical_packages = set()

    # Scan Python imports
    for py_file in self.repo_root.rglob("*.py"):
        try:
            content = py_file.read_text()
            # Match: import X, from X import Y
            imports = re.findall(r'^(?:import|from)\s+(\w+)', content, re.MULTILINE)
            critical_packages.update(imports)
        except Exception:
            pass

    # Scan JS/TS imports
    for ext in ["*.js", "*.ts", "*.jsx", "*.tsx"]:
        for js_file in self.repo_root.rglob(ext):
            try:
                content = js_file.read_text()
                # Match: import ... from 'package', require('package')
                imports = re.findall(r'(?:from|require\()\s*[\'"]([^./][^\'"/]*)', content)
                critical_packages.update(imports)
            except Exception:
                pass

    # Upgrade severity for packages found in imports
    for pkg in missing:
        normalized = pkg.name.replace("-", "_").lower()
        if normalized in critical_packages or pkg.name in critical_packages:
            pkg.severity = "critical"

    return missing
```

### 1.8 Health Score Calculation

```python
def calculate_health_score(self, report: DependencyReport) -> int:
    """
    Calculate workspace health score 0-100.

    Deductions:
    - Critical missing: -15 each
    - Warning missing: -5 each
    - Outdated: -2 each
    - Conflicts: -10 each
    """
    score = 100

    for pkg in report.missing:
        if pkg.severity == "critical":
            score -= 15
        else:
            score -= 5

    score -= len(report.outdated) * 2
    score -= len(report.conflicts) * 10

    return max(0, min(100, score))
```

### 1.9 Markdown Formatting

```python
def format_dependency_report(self) -> str:
    """Format full dependency report as markdown."""
    report = self.scan_dependencies()

    lines = ["# Dependency Status"]

    # Group by severity
    critical = [p for p in report.missing if p.severity == "critical"]
    warning = [p for p in report.missing if p.severity == "warning"]

    if critical:
        lines.append("\n## Critical (Blocks Execution)")
        for pkg in critical:
            lines.append(f"\n- **{pkg.name}** ({pkg.ecosystem})")
            lines.append(f"  - Source: `{pkg.detected_from}`")
            lines.append(f"  ```bash")
            lines.append(f"  {pkg.install_command}")
            lines.append(f"  ```")

    if warning:
        lines.append("\n## Warning (Should Install)")
        for pkg in warning:
            lines.append(f"\n- **{pkg.name}** ({pkg.ecosystem})")
            lines.append(f"  ```bash")
            lines.append(f"  {pkg.install_command}")
            lines.append(f"  ```")

    # Quick fix section
    all_missing = critical + warning
    if all_missing:
        lines.append("\n## Quick Fix")
        lines.append("```bash")
        by_ecosystem = {}
        for pkg in all_missing:
            by_ecosystem.setdefault(pkg.ecosystem, []).append(pkg.name)
        for eco, pkgs in by_ecosystem.items():
            if eco == "npm":
                lines.append(f"npm install {' '.join(pkgs)}")
            elif eco == "pip":
                lines.append(f"pip install {' '.join(pkgs)}")
        lines.append("```")

    lines.append(f"\n## Health Score: {report.health_score}/100")

    return "\n".join(lines)
```

### 1.10 Performance Optimizations

```python
def needs_rescan(self) -> bool:
    """Check if manifest files changed since last scan."""
    manifest_files = [
        "package.json", "package-lock.json",
        "pyproject.toml", "uv.lock", "requirements.txt",
        "go.mod", "go.sum",
        "Cargo.toml", "Cargo.lock",
        "Gemfile", "Gemfile.lock"
    ]

    for name in manifest_files:
        path = self.repo_root / name
        if path.exists():
            mtime = path.stat().st_mtime
            if self._file_mtimes.get(name, 0) != mtime:
                return True

    return False

def _update_mtime_cache(self) -> None:
    """Update cached mtimes after scan."""
    manifest_files = [
        "package.json", "pyproject.toml", "requirements.txt",
        "go.mod", "Cargo.toml", "Gemfile"
    ]
    for name in manifest_files:
        path = self.repo_root / name
        if path.exists():
            self._file_mtimes[name] = path.stat().st_mtime
```

---

## Tier 2: Verification Plan

### 2.1 Unit Tests

```python
# tests/test_workspace_monitor.py

def test_detect_missing_npm_packages():
    """Given: package.json with express, no node_modules
       When: scan_dependencies()
       Then: returns MissingPackage(name="express", ecosystem="npm")"""

def test_detect_missing_python_packages():
    """Given: requirements.txt with flask, flask not in site-packages
       When: scan_dependencies()
       Then: returns MissingPackage(name="flask", ecosystem="pip")"""

def test_generate_install_commands():
    """Given: missing packages detected
       When: suggest_install_commands()
       Then: returns correct install commands per ecosystem"""

def test_health_score_calculation():
    """Given: 2 critical missing, 1 warning
       When: calculate health score
       Then: score = 100 - 15*2 - 5 = 65"""

def test_cache_invalidation():
    """Given: package.json modified
       When: needs_rescan()
       Then: returns True"""

def test_critical_severity_upgrade():
    """Given: package missing AND imported in source
       When: _cross_reference_imports()
       Then: severity upgraded to 'critical'"""
```

### 2.2 Integration Tests

```python
def test_full_scan_npm_project():
    """Create temp directory with package.json, verify scan results."""

def test_full_scan_python_project():
    """Create temp directory with pyproject.toml, verify scan results."""

def test_markdown_formatting():
    """Verify output format matches expected markdown structure."""
```

### 2.3 Performance Tests

```python
def test_scan_performance_small_project():
    """Scan should complete in <100ms for small project."""

def test_scan_performance_large_project():
    """Scan should complete in <500ms for project with 1000+ files."""

def test_cache_hit_performance():
    """Cached read should complete in <10ms."""
```

### 2.4 Rollback Criteria

- **ROLLBACK IF:** Scan takes >5s on any reasonable project
- **ROLLBACK IF:** Memory usage exceeds 100MB during scan
- **ROLLBACK IF:** Any existing tests fail after integration

---

## Tier 3: Validation Checklist

### 3.1 Code Quality

- [ ] All methods have docstrings
- [ ] Type hints on all public methods
- [ ] No circular imports
- [ ] Follows existing code style (ruff clean)
- [ ] No hardcoded paths (uses repo_root)

### 3.2 Functionality

- [ ] Correctly detects npm packages
- [ ] Correctly detects Python packages
- [ ] Install commands are valid shell commands
- [ ] Health score calculation is accurate
- [ ] Cache invalidation works correctly

### 3.3 Integration

- [ ] Imports work from `mcp_server.py`
- [ ] Lazy loading pattern matches existing components
- [ ] No impact on MCP server startup time
- [ ] Works with existing test fixtures

### 3.4 Edge Cases

- [ ] Empty project (no package files)
- [ ] Corrupted package.json (invalid JSON)
- [ ] Missing permissions on directories
- [ ] Symlinked node_modules
- [ ] Virtual environment detection

---

## Implementation Notes

### No Breaking Changes

This is a NEW file with no modifications to existing code. Integration happens in Milestone 4 when we modify `mcp_server.py`.

### Dependencies

- Uses `tomllib` (Python 3.11+ stdlib) for TOML parsing
- Uses `importlib.util` (stdlib) for package detection
- Uses `dataclasses` from models.py (Milestone 3)

### File Location

```
src/agent_harness/
├── workspace_monitor.py  <-- NEW
├── mcp_server.py
├── passive_context.py
└── models.py
```
