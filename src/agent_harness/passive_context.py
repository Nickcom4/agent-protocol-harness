"""
Passive context enhancement - no tool calls required.

Automatically injects helpful context into Claude's conversation via MCP resources.
"""

from pathlib import Path
import json
import subprocess
from typing import Dict, List, Optional


class PassiveContextProvider:
    """Provides passive context enhancements via MCP resources."""

    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self._cached_summary: Optional[str] = None

    def generate_codebase_summary(self) -> str:
        """
        Auto-detect project structure and patterns.

        Returns markdown summary that helps Claude understand the codebase.
        """
        if self._cached_summary:
            return self._cached_summary

        # Detect tech stack
        tech_stack = self._detect_tech_stack()

        # Find key directories
        structure = self._analyze_structure()

        # Detect patterns (e.g., mono repo, microservices, etc.)
        patterns = self._detect_patterns()

        # Detect conventions
        conventions = self._detect_conventions()

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

        self._cached_summary = summary
        return summary

    def _detect_tech_stack(self) -> str:
        """Detect languages and frameworks."""
        stack = []

        # JavaScript/TypeScript
        if (self.repo_root / "package.json").exists():
            stack.append("- **JavaScript/TypeScript** (Node.js)")
            try:
                with open(self.repo_root / "package.json") as f:
                    pkg = json.load(f)
                    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
                    if "react" in deps:
                        stack.append("  - React")
                    if "vue" in deps:
                        stack.append("  - Vue")
                    if "express" in deps:
                        stack.append("  - Express")
                    if "next" in deps:
                        stack.append("  - Next.js")
                    if "typescript" in deps:
                        stack.append("  - TypeScript")
            except (json.JSONDecodeError, IOError):
                pass

        # Python
        if (self.repo_root / "pyproject.toml").exists() or (self.repo_root / "setup.py").exists():
            stack.append("- **Python**")
            # Check pyproject.toml for frameworks
            pyproject = self.repo_root / "pyproject.toml"
            if pyproject.exists():
                try:
                    content = pyproject.read_text()
                    if "django" in content.lower():
                        stack.append("  - Django")
                    if "flask" in content.lower():
                        stack.append("  - Flask")
                    if "fastapi" in content.lower():
                        stack.append("  - FastAPI")
                    if "mcp" in content.lower():
                        stack.append("  - MCP (Model Context Protocol)")
                except IOError:
                    pass

        # Go
        if (self.repo_root / "go.mod").exists():
            stack.append("- **Go**")

        # Rust
        if (self.repo_root / "Cargo.toml").exists():
            stack.append("- **Rust**")

        # Ruby
        if (self.repo_root / "Gemfile").exists():
            stack.append("- **Ruby**")
            if (self.repo_root / "config" / "routes.rb").exists():
                stack.append("  - Rails")

        # Java/Kotlin
        if (self.repo_root / "pom.xml").exists():
            stack.append("- **Java** (Maven)")
        if (self.repo_root / "build.gradle").exists() or (self.repo_root / "build.gradle.kts").exists():
            stack.append("- **Java/Kotlin** (Gradle)")

        return "\n".join(stack) if stack else "- Unknown (no standard config files detected)"

    def _analyze_structure(self) -> str:
        """Analyze directory structure."""
        # Exclude common non-source directories
        exclude = {
            ".git", "node_modules", "__pycache__", ".venv", "venv",
            "dist", "build", ".next", ".nuxt", "coverage", ".pytest_cache",
            ".mypy_cache", ".ruff_cache", "target", ".idea", ".vscode"
        }

        dirs = []
        try:
            for item in self.repo_root.iterdir():
                if item.is_dir() and item.name not in exclude and not item.name.startswith("."):
                    # Count source files
                    file_count = 0
                    for ext in ["*.py", "*.ts", "*.tsx", "*.js", "*.jsx", "*.go", "*.rs", "*.rb", "*.java", "*.kt"]:
                        file_count += len(list(item.rglob(ext)))
                    if file_count > 0:
                        dirs.append((item.name, file_count))
        except PermissionError:
            pass

        dirs.sort(key=lambda x: x[1], reverse=True)

        structure_lines = []
        for name, count in dirs[:10]:  # Top 10 directories
            structure_lines.append(f"- `{name}/` ({count} source files)")

        return "\n".join(structure_lines) if structure_lines else "- Flat structure"

    def _detect_patterns(self) -> str:
        """Detect architectural patterns."""
        patterns = []

        # Monorepo?
        if (self.repo_root / "packages").exists() or (self.repo_root / "apps").exists():
            patterns.append("- **Monorepo** (packages/ or apps/ detected)")
        if (self.repo_root / "lerna.json").exists() or (self.repo_root / "pnpm-workspace.yaml").exists():
            patterns.append("- **Monorepo** (workspace config detected)")

        # Microservices?
        services_dir = self.repo_root / "services"
        if services_dir.exists() and services_dir.is_dir():
            try:
                service_count = len([d for d in services_dir.iterdir() if d.is_dir()])
                if service_count > 1:
                    patterns.append(f"- **Microservices** ({service_count} services)")
            except PermissionError:
                pass

        # Full stack?
        has_frontend = any([
            (self.repo_root / "frontend").exists(),
            (self.repo_root / "client").exists(),
            (self.repo_root / "web").exists(),
            (self.repo_root / "app").exists() and (self.repo_root / "api").exists(),
        ])
        has_backend = any([
            (self.repo_root / "backend").exists(),
            (self.repo_root / "server").exists(),
            (self.repo_root / "api").exists(),
        ])
        if has_frontend and has_backend:
            patterns.append("- **Full-stack** (frontend + backend detected)")

        # MCP Server?
        if (self.repo_root / "src" / "agent_harness").exists():
            patterns.append("- **MCP Server** (agent harness detected)")

        return "\n".join(patterns) if patterns else "- Single-purpose application"

    def _detect_conventions(self) -> str:
        """Detect code conventions and tooling."""
        conventions = []

        # JavaScript/TypeScript linting/formatting
        if any([
            (self.repo_root / ".eslintrc.json").exists(),
            (self.repo_root / ".eslintrc.js").exists(),
            (self.repo_root / ".eslintrc.cjs").exists(),
            (self.repo_root / "eslint.config.js").exists(),
        ]):
            conventions.append("- ESLint configured")
        if (self.repo_root / ".prettierrc").exists() or (self.repo_root / ".prettierrc.json").exists():
            conventions.append("- Prettier configured")
        if (self.repo_root / "biome.json").exists():
            conventions.append("- Biome configured")

        # Python linting/formatting
        pyproject = self.repo_root / "pyproject.toml"
        if pyproject.exists():
            try:
                content = pyproject.read_text()
                if "ruff" in content:
                    conventions.append("- Ruff (Python linter/formatter)")
                if "black" in content:
                    conventions.append("- Black (Python formatter)")
                if "mypy" in content:
                    conventions.append("- MyPy (Python type checker)")
                if "pytest" in content:
                    conventions.append("- Pytest for testing")
            except IOError:
                pass

        # Testing
        if (self.repo_root / "jest.config.js").exists() or (self.repo_root / "jest.config.ts").exists():
            conventions.append("- Jest for testing")
        if (self.repo_root / "vitest.config.ts").exists():
            conventions.append("- Vitest for testing")
        if (self.repo_root / "pytest.ini").exists():
            conventions.append("- Pytest for testing")

        # CI/CD
        if (self.repo_root / ".github" / "workflows").exists():
            conventions.append("- GitHub Actions CI/CD")
        if (self.repo_root / ".gitlab-ci.yml").exists():
            conventions.append("- GitLab CI/CD")

        # Docker
        if (self.repo_root / "Dockerfile").exists() or (self.repo_root / "docker-compose.yml").exists():
            conventions.append("- Docker containerization")

        return "\n".join(conventions) if conventions else "- No standard tooling detected"

    def assess_task_complexity(self, conversation_history: List[str]) -> Dict:
        """
        Real-time complexity assessment based on conversation.

        Returns JSON with complexity score and orchestration recommendation.
        """
        # Analyze conversation for complexity signals
        all_text = " ".join(conversation_history).lower()

        score = 0
        signals = []

        # Multi-system keywords
        multi_system_keywords = ["frontend", "backend", "database", "api", "server", "client"]
        systems_mentioned = [w for w in multi_system_keywords if w in all_text]
        if len(systems_mentioned) >= 2:
            score += len(systems_mentioned) * 2
            signals.append(f"Multi-system task ({len(systems_mentioned)} systems: {', '.join(systems_mentioned)})")

        # File count estimation
        if "files" in all_text or "components" in all_text or "modules" in all_text:
            score += 1

        # Scope keywords (high complexity)
        scope_words = ["refactor", "migrate", "restructure", "architecture", "redesign", "overhaul"]
        matched_scope = [w for w in scope_words if w in all_text]
        if matched_scope:
            score += 3
            signals.append(f"Large-scope work ({', '.join(matched_scope)})")

        # Orchestration keywords
        if "multi-agent" in all_text or "orchestrat" in all_text:
            score += 5
            signals.append("Explicit orchestration request")

        # Feature complexity
        if "authentication" in all_text or "auth" in all_text:
            score += 2
            signals.append("Authentication feature (cross-cutting)")

        if "payment" in all_text or "billing" in all_text or "stripe" in all_text:
            score += 2
            signals.append("Payment integration (security-sensitive)")

        # Complexity threshold
        recommend_orchestration = score >= 5

        return {
            "complexity_score": score,
            "signals": signals,
            "recommend_orchestration": recommend_orchestration,
            "reason": self._get_complexity_reason(score),
        }

    def _get_complexity_reason(self, score: int) -> str:
        """Get human-readable complexity assessment."""
        if score < 3:
            return "Simple task - handle directly without orchestration"
        elif score < 5:
            return "Moderate task - orchestration optional, consider checkpoints"
        else:
            return "Complex task - orchestration recommended for isolation and verification"

    def suggest_scopes(self) -> Dict[str, List[str]]:
        """
        Suggest natural scope boundaries for potential multi-agent splits.

        Returns JSON mapping system names to file patterns.
        """
        scopes: Dict[str, List[str]] = {}

        # Detect natural boundaries
        system_dirs = [
            "frontend", "backend", "api", "database", "db",
            "services", "packages", "apps", "web", "mobile",
            "server", "client", "core", "lib", "shared"
        ]

        for system in system_dirs:
            system_path = self.repo_root / system
            if system_path.exists() and system_path.is_dir():
                scopes[system] = [f"{system}/**/*"]

        # Detect test boundaries
        for test_dir in ["tests", "test", "__tests__", "spec"]:
            if (self.repo_root / test_dir).exists():
                scopes["tests"] = [f"{test_dir}/**/*"]
                break

        # Detect docs
        for doc_dir in ["docs", "documentation", "doc"]:
            if (self.repo_root / doc_dir).exists():
                scopes["docs"] = [f"{doc_dir}/**/*", "*.md", "README*"]
                break

        # Detect config
        config_patterns = ["*.config.js", "*.config.ts", "*.json", ".env*"]
        scopes["config"] = config_patterns

        return scopes

    def quick_complexity_check(self, task: str) -> int:
        """
        Ultra-lightweight complexity check (no component loading).

        Returns score 0-10 without loading any heavy components.
        Used for dormant mode detection.
        """
        score = 0
        task_lower = task.lower()

        # Quick keyword checks
        multi_system_keywords = ["frontend", "backend", "database", "api", "services", "server", "client"]
        systems_mentioned = sum(1 for kw in multi_system_keywords if kw in task_lower)
        score += systems_mentioned

        # Large scope keywords
        if any(word in task_lower for word in ["refactor", "migrate", "architecture", "redesign"]):
            score += 3

        # Orchestration keywords
        if any(word in task_lower for word in ["orchestrat", "multi-agent", "complex", "multiple systems"]):
            score += 5

        # Simple task indicators (reduce score)
        simple_indicators = ["fix typo", "add comment", "rename", "update readme", "small change", "quick fix"]
        if any(indicator in task_lower for indicator in simple_indicators):
            score = max(0, score - 2)

        return score
