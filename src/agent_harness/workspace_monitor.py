"""
Workspace dependency monitor for the Agent Protocol Harness.

Provides real-time dependency analysis, missing package detection,
and health scoring for codebases. Enables proactive guidance on
dependency issues without explicit tool calls.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import importlib.util
import json
import re
import time

from .models import (
    DependencyReport,
    MissingPackage,
    OutdatedPackage,
    Conflict,
    PACKAGE_MANAGER_CONFIGS,
)


@dataclass
class PackageManager:
    """Metadata for a package manager ecosystem."""
    name: str                      # "npm", "pip", "go", etc.
    manifest_file: str             # "package.json", "pyproject.toml"
    lock_file: Optional[str]       # "package-lock.json", "uv.lock"
    install_dir: str               # "node_modules", ".venv/lib"
    install_command_template: str  # "npm install {package}", "pip install {package}"


class WorkspaceMonitor:
    """
    Real-time workspace dependency analyzer.

    Features:
    - Scans package manifests (package.json, pyproject.toml, etc.)
    - Detects missing packages by checking install directories
    - Generates ready-to-run install commands
    - Calculates workspace health score
    - Caches results with TTL for performance

    Example:
        monitor = WorkspaceMonitor(Path("/my/project"))
        report = monitor.scan_dependencies()
        print(monitor.format_dependency_report())
    """

    # Manifest files to track for cache invalidation
    MANIFEST_FILES = [
        "package.json", "package-lock.json",
        "pyproject.toml", "uv.lock", "requirements.txt",
        "go.mod", "go.sum",
        "Cargo.toml", "Cargo.lock",
        "Gemfile", "Gemfile.lock"
    ]

    def __init__(self, repo_root: Path) -> None:
        """
        Initialize the workspace monitor.

        Args:
            repo_root: Path to the repository root directory.
        """
        self.repo_root = Path(repo_root)
        self._cache: Optional[DependencyReport] = None
        self._cache_time: float = 0
        self._cache_ttl: float = 60.0  # seconds
        self._file_mtimes: dict[str, float] = {}  # For incremental scanning

    def scan_dependencies(self) -> DependencyReport:
        """
        Scan the workspace for dependency issues.

        Main scanning algorithm:
        1. Check if cached results are still valid
        2. Identify which package managers are in use
        3. For each ecosystem:
           a. Parse declared dependencies from manifest
           b. Check if each dependency is installed
           c. Cross-reference imports in source files
           d. Generate install commands for missing packages
        4. Calculate severity levels and health score
        5. Build and cache comprehensive report

        Returns:
            DependencyReport with missing, outdated, and conflicting packages.
        """
        # Return cached result if still valid
        if self._cache is not None and not self.needs_rescan():
            if time.time() - self._cache_time < self._cache_ttl:
                return self._cache

        missing: list[MissingPackage] = []
        outdated: list[OutdatedPackage] = []
        conflicts: list[Conflict] = []

        # Scan each ecosystem
        npm_missing, npm_outdated = self._scan_npm()
        missing.extend(npm_missing)
        outdated.extend(npm_outdated)

        python_missing, python_outdated = self._scan_python()
        missing.extend(python_missing)
        outdated.extend(python_outdated)

        # Cross-reference imports to upgrade severity
        missing = self._cross_reference_imports(missing)

        # Build report
        report = DependencyReport(
            missing=missing,
            outdated=outdated,
            unused=[],  # Not implemented yet
            conflicts=conflicts,
            health_score=0
        )
        report.health_score = self.calculate_health_score(report)

        # Cache the result
        self._cache = report
        self._cache_time = time.time()
        self._update_mtime_cache()

        return report

    def detect_missing_packages(self) -> list[MissingPackage]:
        """
        Detect packages that are declared but not installed.

        This is a convenience wrapper around scan_dependencies()
        that returns only the missing packages list.

        Returns:
            List of missing packages with install commands.
        """
        report = self.scan_dependencies()
        return report.missing

    def suggest_install_commands(self) -> list[str]:
        """
        Generate install commands for all missing packages.

        Groups packages by ecosystem to generate efficient
        batch install commands.

        Returns:
            List of shell commands to install missing packages.
        """
        report = self.scan_dependencies()
        commands: list[str] = []

        # Group by ecosystem
        by_ecosystem: dict[str, list[str]] = {}
        for pkg in report.missing:
            if pkg.ecosystem not in by_ecosystem:
                by_ecosystem[pkg.ecosystem] = []
            by_ecosystem[pkg.ecosystem].append(pkg.name)

        # Generate batch commands
        if "npm" in by_ecosystem:
            commands.append(f"npm install {' '.join(by_ecosystem['npm'])}")
        if "pip" in by_ecosystem:
            commands.append(f"pip install {' '.join(by_ecosystem['pip'])}")
        if "go" in by_ecosystem:
            for pkg in by_ecosystem["go"]:
                commands.append(f"go get {pkg}")
        if "cargo" in by_ecosystem:
            for pkg in by_ecosystem["cargo"]:
                commands.append(f"cargo add {pkg}")
        if "gem" in by_ecosystem:
            commands.append(f"gem install {' '.join(by_ecosystem['gem'])}")

        return commands

    def calculate_health_score(self, report: DependencyReport) -> int:
        """
        Calculate workspace health score from 0-100.

        Scoring deductions:
        - Critical missing package: -15 each
        - Warning missing package: -5 each
        - Outdated package: -2 each
        - Conflict: -10 each

        Args:
            report: The dependency report to score.

        Returns:
            Health score between 0 and 100.
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

    def format_dependency_report(self) -> str:
        """
        Format a full dependency report as markdown.

        Includes:
        - Critical issues (blocks execution)
        - Warnings (should install)
        - Quick fix commands
        - Health score

        Returns:
            Markdown-formatted dependency report.
        """
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
                lines.append("  ```bash")
                lines.append(f"  {pkg.install_command}")
                lines.append("  ```")

        if warning:
            lines.append("\n## Warning (Should Install)")
            for pkg in warning:
                lines.append(f"\n- **{pkg.name}** ({pkg.ecosystem})")
                lines.append("  ```bash")
                lines.append(f"  {pkg.install_command}")
                lines.append("  ```")

        # Quick fix section
        all_missing = critical + warning
        if all_missing:
            lines.append("\n## Quick Fix")
            lines.append("```bash")
            by_ecosystem: dict[str, list[str]] = {}
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

    def format_health_report(self) -> str:
        """
        Format a condensed health report as markdown.

        Focuses on actionable information: score, critical count,
        and primary fix command.

        Returns:
            Markdown-formatted health summary.
        """
        report = self.scan_dependencies()

        lines = ["# Workspace Health"]
        lines.append(f"\n**Score:** {report.health_score}/100")

        if report.missing:
            critical_count = sum(1 for p in report.missing if p.severity == "critical")
            warning_count = len(report.missing) - critical_count

            if critical_count > 0:
                lines.append(f"\n**Critical Issues:** {critical_count}")
            if warning_count > 0:
                lines.append(f"\n**Warnings:** {warning_count}")

            # Primary fix
            commands = self.suggest_install_commands()
            if commands:
                lines.append("\n**Quick Fix:**")
                lines.append("```bash")
                for cmd in commands[:3]:  # Limit to first 3
                    lines.append(cmd)
                lines.append("```")
        else:
            lines.append("\nAll dependencies are installed.")

        return "\n".join(lines)

    def get_quick_status(self) -> str:
        """
        Get a one-line status summary.

        Format: "Health: XX/100 | N critical, M warnings"

        Returns:
            Single-line status string.
        """
        report = self.scan_dependencies()
        critical = sum(1 for p in report.missing if p.severity == "critical")
        warnings = sum(1 for p in report.missing if p.severity == "warning")

        if critical == 0 and warnings == 0:
            return f"Health: {report.health_score}/100 | All dependencies OK"

        parts = []
        if critical > 0:
            parts.append(f"{critical} critical")
        if warnings > 0:
            parts.append(f"{warnings} warnings")

        return f"Health: {report.health_score}/100 | {', '.join(parts)}"

    def needs_rescan(self) -> bool:
        """
        Check if manifest files have changed since last scan.

        Compares file modification times to cached values
        to determine if a rescan is needed.

        Returns:
            True if any manifest file has changed.
        """
        for name in self.MANIFEST_FILES:
            path = self.repo_root / name
            if path.exists():
                try:
                    mtime = path.stat().st_mtime
                    if self._file_mtimes.get(name, 0) != mtime:
                        return True
                except (OSError, PermissionError):
                    # File access error - assume changed
                    return True

        return False

    def invalidate_cache(self) -> None:
        """
        Clear the cached dependency report.

        Forces the next scan_dependencies() call to perform
        a full rescan.
        """
        self._cache = None
        self._cache_time = 0
        self._file_mtimes.clear()

    # =========================================================
    # Private scanning methods
    # =========================================================

    def _scan_npm(self) -> tuple[list[MissingPackage], list[OutdatedPackage]]:
        """
        Scan JavaScript/TypeScript dependencies.

        Parses package.json and checks node_modules for
        installed packages.

        Returns:
            Tuple of (missing packages, outdated packages).
        """
        pkg_json = self.repo_root / "package.json"
        if not pkg_json.exists():
            return [], []

        try:
            data = json.loads(pkg_json.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, PermissionError):
            # Invalid JSON or file access error
            return [], []

        missing: list[MissingPackage] = []
        deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
        node_modules = self.repo_root / "node_modules"

        for name, version in deps.items():
            pkg_dir = node_modules / name
            # Handle scoped packages like @types/node
            if name.startswith("@"):
                parts = name.split("/", 1)
                if len(parts) == 2:
                    pkg_dir = node_modules / parts[0] / parts[1]

            if not pkg_dir.exists():
                missing.append(MissingPackage(
                    name=name,
                    ecosystem="npm",
                    install_command=f"npm install {name}",
                    detected_from="package.json",
                    severity="warning"
                ))

        return missing, []

    def _scan_python(self) -> tuple[list[MissingPackage], list[OutdatedPackage]]:
        """
        Scan Python dependencies.

        Checks both pyproject.toml and requirements.txt for
        declared dependencies, then verifies installation.

        Returns:
            Tuple of (missing packages, outdated packages).
        """
        missing: list[MissingPackage] = []
        seen_packages: set[str] = set()  # Avoid duplicates

        # Check pyproject.toml
        pyproject = self.repo_root / "pyproject.toml"
        if pyproject.exists():
            try:
                # Use tomllib for Python 3.11+, fallback to tomli
                try:
                    import tomllib
                    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
                except ImportError:
                    try:
                        import tomli as tomllib  # type: ignore
                        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
                    except ImportError:
                        data = {}

                # Get dependencies from [project.dependencies]
                deps = data.get("project", {}).get("dependencies", [])

                # Also check [tool.poetry.dependencies] for Poetry projects
                poetry_deps = data.get("tool", {}).get("poetry", {}).get("dependencies", {})
                if isinstance(poetry_deps, dict):
                    deps.extend(poetry_deps.keys())

                for dep in deps:
                    # Parse "package>=version" or "package[extras]>=version" format
                    name = re.split(r'[\[<>=!~;\s]', str(dep))[0].strip()
                    if name and name not in seen_packages and name.lower() != "python":
                        seen_packages.add(name)
                        if not self._is_python_package_installed(name):
                            missing.append(MissingPackage(
                                name=name,
                                ecosystem="pip",
                                install_command=f"pip install {name}",
                                detected_from="pyproject.toml",
                                severity="warning"
                            ))
            except (OSError, PermissionError):
                pass

        # Check requirements.txt
        requirements = self.repo_root / "requirements.txt"
        if requirements.exists():
            try:
                for line in requirements.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    # Skip empty lines, comments, and -r/-e directives
                    if not line or line.startswith("#") or line.startswith("-"):
                        continue

                    # Parse package name (handles package>=version, package[extras], etc.)
                    name = re.split(r'[\[<>=!~;\s]', line)[0].strip()
                    if name and name not in seen_packages:
                        seen_packages.add(name)
                        if not self._is_python_package_installed(name):
                            missing.append(MissingPackage(
                                name=name,
                                ecosystem="pip",
                                install_command=f"pip install {name}",
                                detected_from="requirements.txt",
                                severity="warning"
                            ))
            except (OSError, PermissionError):
                pass

        return missing, []

    def _is_python_package_installed(self, name: str) -> bool:
        """
        Check if a Python package is installed.

        Uses importlib.util.find_spec to check if the package
        can be imported. Handles common name transformations
        (e.g., package-name -> package_name).

        Args:
            name: Package name as declared in manifest.

        Returns:
            True if the package is importable.
        """
        # Common transformations for package name -> import name
        import_name = name.replace("-", "_").lower()

        # Some packages have different import names
        # Common mappings
        name_mappings = {
            "pillow": "PIL",
            "beautifulsoup4": "bs4",
            "pyyaml": "yaml",
            "scikit-learn": "sklearn",
            "opencv-python": "cv2",
            "opencv-python-headless": "cv2",
            "python-dateutil": "dateutil",
            "typing-extensions": "typing_extensions",
        }

        if name.lower() in name_mappings:
            import_name = name_mappings[name.lower()]

        try:
            return importlib.util.find_spec(import_name) is not None
        except (ModuleNotFoundError, ValueError):
            # Try original name if transformed didn't work
            try:
                return importlib.util.find_spec(name) is not None
            except (ModuleNotFoundError, ValueError):
                return False

    def _cross_reference_imports(
        self, missing: list[MissingPackage]
    ) -> list[MissingPackage]:
        """
        Upgrade severity for packages actually imported in code.

        Scans source files for import statements and upgrades
        missing packages to 'critical' if they're being used.

        Args:
            missing: List of missing packages to check.

        Returns:
            Updated list with severity adjustments.
        """
        if not missing:
            return missing

        critical_packages: set[str] = set()

        # Build set of package names to look for (normalized)
        package_names = {
            pkg.name.replace("-", "_").lower() for pkg in missing
        }
        package_names.update(pkg.name for pkg in missing)

        # Scan Python imports
        try:
            for py_file in self.repo_root.rglob("*.py"):
                # Skip common non-source directories
                path_str = str(py_file)
                if any(skip in path_str for skip in [
                    "node_modules", ".venv", "venv", "__pycache__",
                    ".git", "dist", "build", ".tox", ".eggs"
                ]):
                    continue

                try:
                    content = py_file.read_text(encoding="utf-8", errors="ignore")
                    # Match: import X, from X import Y
                    imports = re.findall(
                        r'^(?:import|from)\s+([a-zA-Z_][a-zA-Z0-9_]*)',
                        content,
                        re.MULTILINE
                    )
                    for imp in imports:
                        normalized = imp.replace("-", "_").lower()
                        if normalized in package_names or imp in package_names:
                            critical_packages.add(normalized)
                            critical_packages.add(imp)
                except (OSError, PermissionError):
                    pass
        except (OSError, PermissionError):
            pass

        # Scan JS/TS imports
        for ext in ["*.js", "*.ts", "*.jsx", "*.tsx", "*.mjs", "*.cjs"]:
            try:
                for js_file in self.repo_root.rglob(ext):
                    # Skip node_modules and other non-source
                    path_str = str(js_file)
                    if any(skip in path_str for skip in [
                        "node_modules", ".venv", "dist", "build", ".git"
                    ]):
                        continue

                    try:
                        content = js_file.read_text(encoding="utf-8", errors="ignore")
                        # Match: import ... from 'package', require('package')
                        imports = re.findall(
                            r'''(?:from|require\()\s*['"]([^./'"@][^'"]*?)['"]''',
                            content
                        )
                        # Also match @scope/package imports
                        scoped_imports = re.findall(
                            r'''(?:from|require\()\s*['"](@[^/'"]+/[^'"]+)['"]''',
                            content
                        )
                        critical_packages.update(imports)
                        critical_packages.update(scoped_imports)
                    except (OSError, PermissionError):
                        pass
            except (OSError, PermissionError):
                pass

        # Upgrade severity for packages found in imports
        for pkg in missing:
            normalized = pkg.name.replace("-", "_").lower()
            if normalized in critical_packages or pkg.name in critical_packages:
                pkg.severity = "critical"

        return missing

    def _update_mtime_cache(self) -> None:
        """
        Update cached file modification times after scan.

        Records the mtime of each manifest file for later
        comparison in needs_rescan().
        """
        for name in self.MANIFEST_FILES:
            path = self.repo_root / name
            if path.exists():
                try:
                    self._file_mtimes[name] = path.stat().st_mtime
                except (OSError, PermissionError):
                    pass
