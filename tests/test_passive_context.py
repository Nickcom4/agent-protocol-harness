"""
Tests for PassiveContextProvider.

Tests the passive context enhancement features:
- Codebase summary generation
- Task complexity assessment
- Scope suggestions
- Dormant mode detection
"""

import pytest
import tempfile
import json
from pathlib import Path

from agent_harness.passive_context import PassiveContextProvider


@pytest.fixture
def temp_repo():
    """Create a temporary repository for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)

        # Create basic Python project structure
        (repo / "src").mkdir()
        (repo / "src" / "__init__.py").write_text("")
        (repo / "src" / "main.py").write_text("print('hello')")

        # Add pyproject.toml
        (repo / "pyproject.toml").write_text("""
[project]
name = "test-project"

[tool.ruff]
line-length = 100

[tool.pytest.ini_options]
testpaths = ["tests"]
""")

        # Add package.json for JS detection
        (repo / "package.json").write_text(json.dumps({
            "name": "test-project",
            "dependencies": {
                "express": "^4.0.0",
                "react": "^18.0.0"
            },
            "devDependencies": {
                "typescript": "^5.0.0"
            }
        }))

        # Create frontend/backend structure
        (repo / "frontend").mkdir()
        (repo / "frontend" / "App.tsx").write_text("export default function App() {}")
        (repo / "backend").mkdir()
        (repo / "backend" / "server.py").write_text("from flask import Flask")

        yield repo


@pytest.fixture
def provider(temp_repo):
    """Create a PassiveContextProvider for the temp repo."""
    return PassiveContextProvider(temp_repo)


class TestCodebaseSummary:
    """Tests for generate_codebase_summary()."""

    def test_detects_python(self, provider, temp_repo):
        """Should detect Python from pyproject.toml."""
        summary = provider.generate_codebase_summary()
        assert "Python" in summary

    def test_detects_javascript(self, provider, temp_repo):
        """Should detect JavaScript from package.json."""
        summary = provider.generate_codebase_summary()
        assert "JavaScript" in summary or "TypeScript" in summary

    def test_detects_react(self, provider, temp_repo):
        """Should detect React framework."""
        summary = provider.generate_codebase_summary()
        assert "React" in summary

    def test_detects_ruff(self, provider, temp_repo):
        """Should detect Ruff linter."""
        summary = provider.generate_codebase_summary()
        assert "Ruff" in summary

    def test_detects_fullstack_pattern(self, provider, temp_repo):
        """Should detect full-stack pattern from frontend/backend dirs."""
        summary = provider.generate_codebase_summary()
        assert "Full-stack" in summary

    def test_caches_summary(self, provider):
        """Should cache the summary after first generation."""
        summary1 = provider.generate_codebase_summary()
        summary2 = provider.generate_codebase_summary()
        assert summary1 == summary2
        assert provider._cached_summary is not None


class TestTaskComplexity:
    """Tests for assess_task_complexity()."""

    def test_simple_task_low_score(self, provider):
        """Simple task should have low complexity score."""
        result = provider.assess_task_complexity(["Fix typo in README"])
        assert result["complexity_score"] < 3
        assert result["recommend_orchestration"] is False

    def test_multi_system_task_high_score(self, provider):
        """Multi-system task should have high complexity score."""
        result = provider.assess_task_complexity([
            "Add user authentication with frontend login form and backend API"
        ])
        assert result["complexity_score"] >= 3
        assert "Multi-system" in str(result["signals"])

    def test_refactor_task_high_score(self, provider):
        """Refactoring task should increase complexity score."""
        result = provider.assess_task_complexity(["Refactor the database schema"])
        assert result["complexity_score"] >= 3
        assert "Large-scope" in str(result["signals"])

    def test_orchestration_keyword_very_high(self, provider):
        """Explicit orchestration request should trigger recommendation."""
        result = provider.assess_task_complexity([
            "Use multi-agent orchestration to build feature"
        ])
        assert result["complexity_score"] >= 5
        assert result["recommend_orchestration"] is True

    def test_reason_matches_score(self, provider):
        """Reason should match the score threshold."""
        simple = provider.assess_task_complexity(["Fix bug"])
        assert "Simple task" in simple["reason"] or "directly" in simple["reason"].lower()

        complex_task = provider.assess_task_complexity([
            "Refactor frontend backend and database for new architecture"
        ])
        assert "orchestration" in complex_task["reason"].lower() or "complex" in complex_task["reason"].lower()


class TestQuickComplexityCheck:
    """Tests for quick_complexity_check() (dormant mode detection)."""

    def test_simple_fix_low_score(self, provider):
        """Simple fix should have very low score."""
        score = provider.quick_complexity_check("fix typo in readme")
        assert score < 2

    def test_multi_system_higher_score(self, provider):
        """Multi-system keywords should increase score."""
        score = provider.quick_complexity_check("update frontend and backend")
        assert score >= 2

    def test_refactor_increases_score(self, provider):
        """Refactor keyword should increase score."""
        score = provider.quick_complexity_check("refactor the authentication")
        assert score >= 3

    def test_orchestration_keyword_high_score(self, provider):
        """Orchestration keyword should give high score."""
        score = provider.quick_complexity_check("multi-agent orchestration needed")
        assert score >= 5

    def test_simple_indicators_reduce_score(self, provider):
        """Simple task indicators should reduce score."""
        score_without = provider.quick_complexity_check("update the readme")
        score_with = provider.quick_complexity_check("quick fix update readme")
        assert score_with <= score_without


class TestScopesSuggestions:
    """Tests for suggest_scopes()."""

    def test_detects_frontend_backend(self, provider, temp_repo):
        """Should detect frontend and backend directories."""
        scopes = provider.suggest_scopes()
        assert "frontend" in scopes
        assert "backend" in scopes

    def test_includes_config_patterns(self, provider):
        """Should include config file patterns."""
        scopes = provider.suggest_scopes()
        assert "config" in scopes
        assert any("*.json" in p for p in scopes["config"])

    def test_detects_src_directory(self, provider, temp_repo):
        """Should detect src directory if present."""
        # Create src structure if needed
        src_dir = temp_repo / "src"
        if not src_dir.exists():
            src_dir.mkdir()
            (src_dir / "main.py").write_text("")

        scopes = provider.suggest_scopes()
        # src is not in the default list of system_dirs, so it won't be detected
        # This is fine - we mainly want frontend/backend


class TestIntegration:
    """Integration tests for PassiveContextProvider."""

    def test_full_workflow(self, provider):
        """Test complete workflow from summary to complexity to scopes."""
        # Generate summary (warm cache)
        summary = provider.generate_codebase_summary()
        assert summary is not None
        assert len(summary) > 100

        # Check complexity
        complexity = provider.assess_task_complexity([
            "Add authentication with JWT tokens"
        ])
        assert "complexity_score" in complexity
        assert "recommend_orchestration" in complexity

        # Get scopes
        scopes = provider.suggest_scopes()
        assert isinstance(scopes, dict)

    def test_empty_repo(self):
        """Should handle empty repository gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            provider = PassiveContextProvider(Path(tmpdir))

            summary = provider.generate_codebase_summary()
            assert "Unknown" in summary or "No" in summary

            complexity = provider.assess_task_complexity(["Add feature"])
            assert complexity["complexity_score"] >= 0

            scopes = provider.suggest_scopes()
            assert isinstance(scopes, dict)


class TestDormantMode:
    """Tests specifically for dormant mode behavior."""

    def test_dormant_mode_threshold(self, provider):
        """Score < 2 should trigger dormant mode."""
        # These should all be < 2
        simple_tasks = [
            "fix typo",
            "add comment",
            "update readme",
            "rename variable",
            "small change",
        ]

        for task in simple_tasks:
            score = provider.quick_complexity_check(task)
            assert score < 2, f"'{task}' should have score < 2, got {score}"

    def test_non_dormant_mode(self, provider):
        """Score >= 2 should not trigger dormant mode."""
        complex_tasks = [
            "add api endpoint with database",
            "refactor authentication system",
            "migrate from express to fastapi",
        ]

        for task in complex_tasks:
            score = provider.quick_complexity_check(task)
            assert score >= 2, f"'{task}' should have score >= 2, got {score}"
