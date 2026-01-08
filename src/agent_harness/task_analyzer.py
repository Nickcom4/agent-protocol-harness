"""
Task analyzer for intelligent task context extraction and complexity assessment.

Uses heuristics to infer task context from:
1. Git branch name
2. Recent commit messages
3. Modified files
4. Resource URI parameters

Provides actionable guidance without requiring explicit tool calls.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, TYPE_CHECKING
import re
import subprocess

from .models import ComplexitySignals, ApproachRecommendation, TaskAnalysis

if TYPE_CHECKING:
    from .passive_context import PassiveContextProvider


class TaskAnalyzer:
    """
    Lightweight task analysis without requiring tool calls.

    Uses heuristics to infer task context from:
    1. Git branch name
    2. Recent commit messages
    3. Modified files
    4. Resource URI parameters
    """

    # Git subprocess timeout in seconds
    GIT_TIMEOUT = 5

    # Branch prefixes to strip when parsing task hints
    BRANCH_PREFIXES = [
        "feature/", "fix/", "bugfix/", "hotfix/",
        "refactor/", "chore/", "docs/"
    ]

    # Default branches (no task hint)
    DEFAULT_BRANCHES = ["main", "master", "develop", "dev"]

    # Multi-system keywords for complexity scoring
    MULTI_SYSTEM_KEYWORDS = [
        "frontend", "backend", "database", "api",
        "server", "client", "ui", "db"
    ]

    # Large scope keywords
    LARGE_SCOPE_KEYWORDS = [
        "refactor", "migrate", "restructure",
        "architecture", "redesign", "overhaul"
    ]

    # Auth-related keywords
    AUTH_KEYWORDS = [
        "auth", "login", "password", "session", "jwt", "oauth"
    ]

    # Payment-related keywords
    PAYMENT_KEYWORDS = [
        "payment", "billing", "stripe", "checkout", "subscription"
    ]

    def __init__(
        self,
        repo_root: Path,
        passive_context: 'PassiveContextProvider'
    ) -> None:
        """
        Initialize the task analyzer.

        Args:
            repo_root: Root directory of the repository.
            passive_context: PassiveContextProvider for codebase context.
        """
        self.repo_root = repo_root
        self.passive_context = passive_context
        self._git_info: Optional[Dict] = None

    # =========================================================================
    # Primary Analysis Methods
    # =========================================================================

    def analyze_current_context(self) -> str:
        """
        Generate markdown analysis of current task context.

        Returns actionable guidance without requiring tool call.

        Returns:
            Markdown-formatted analysis string.
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
            lines.append("**Direct execution** - Simple task, proceed directly")
        elif recommendation.approach == "checkpointed":
            lines.append("**Checkpointed execution** - Create commits at logical points")
        else:
            lines.append("**Orchestrated execution** - Use multi-agent workflow")

        lines.append(f"\n**Why?** {recommendation.reason}")

        lines.append("\n### Suggested Steps")
        for i, step in enumerate(recommendation.steps, 1):
            lines.append(f"{i}. {step}")

        if recommendation.warnings:
            lines.append("\n### Warnings")
            for warning in recommendation.warnings:
                lines.append(f"- {warning}")

        # Modified files context
        if git_info.get("modified_files"):
            lines.append("\n## Files In Progress")
            for f in git_info["modified_files"][:10]:
                lines.append(f"- `{f}`")
            if len(git_info["modified_files"]) > 10:
                lines.append(f"- ... and {len(git_info['modified_files']) - 10} more")

        # Cross-reference
        lines.append("\n---")
        lines.append("Read `agent://workspace/dependency-status` for missing packages")
        lines.append("Read `agent://guidance/verification-checklist` for test steps")

        return "\n".join(lines)

    def extract_complexity_signals(self, task: str = "") -> ComplexitySignals:
        """
        Extract complexity signals from task and git context.

        Scoring:
        - Multi-system keywords (frontend, backend, database): +2 each
        - Large scope (refactor, migrate, architecture): +3
        - Auth/payments: +2
        - Modified files > 10: +2
        - AI session branch: +1 (implies complex work in progress)

        Args:
            task: Task description (optional, supplements git context).

        Returns:
            ComplexitySignals with extracted signals and total score.
        """
        # Combine task with git context
        git_info = self._extract_from_git()
        branch_hint = self._extract_from_branch_name() or ""

        all_context = f"{task} {branch_hint} {' '.join(git_info.get('recent_commits', []))}".lower()

        # Count multi-system keywords
        systems_mentioned = [
            w for w in self.MULTI_SYSTEM_KEYWORDS
            if w in all_context
        ]
        multi_system_count = len(set(systems_mentioned))

        # Check scope keywords
        scope_keywords = []
        for word in self.LARGE_SCOPE_KEYWORDS:
            if word in all_context:
                scope_keywords.append(word)

        # Auth/payments detection
        has_auth = any(w in all_context for w in self.AUTH_KEYWORDS)
        has_payments = any(w in all_context for w in self.PAYMENT_KEYWORDS)

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

    def suggest_approach(self, signals: ComplexitySignals) -> ApproachRecommendation:
        """
        Recommend execution approach based on complexity signals.

        Thresholds:
        - < 3: Direct execution (simple, single-system)
        - 3-4: Checkpointed (moderate complexity)
        - >= 5: Orchestrated (complex, multi-system)

        Args:
            signals: ComplexitySignals from extract_complexity_signals().

        Returns:
            ApproachRecommendation with approach, reason, steps, and warnings.
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
            warnings = [
                "Cross-system changes require isolation",
                "Consider rollback strategy"
            ]
            if signals.has_auth:
                warnings.append("Auth changes detected - verify security")

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
                warnings=warnings
            )

    def generate_verification_checklist(self) -> str:
        """
        Generate verification checklist based on task analysis.

        Returns:
            Markdown-formatted checklist.
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

            api_modified = [
                f for f in modified
                if any(x in f.lower() for x in ["api", "route", "endpoint"])
            ]
            if api_modified:
                lines.append("- [ ] API endpoints tested:")
                for a in api_modified[:5]:
                    lines.append(f"  - `{a}`")

        lines.append("\n## Manual Verification")
        lines.append("- [ ] Feature works as expected in browser/CLI")
        lines.append("- [ ] Edge cases handled gracefully")
        lines.append("- [ ] No console errors/warnings")

        return "\n".join(lines)

    # =========================================================================
    # Git Context Extraction
    # =========================================================================

    def _extract_from_git(self) -> Dict:
        """
        Extract all relevant git context.

        Returns:
            Dictionary with branch, recent_commits, modified_files, untracked_files.
        """
        if self._git_info is not None:
            return self._git_info

        info: Dict = {
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
                timeout=self.GIT_TIMEOUT
            )
            if result.returncode == 0:
                info["branch"] = result.stdout.strip()

            # Recent commits (last 5)
            result = subprocess.run(
                ["git", "log", "--oneline", "-5"],
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                timeout=self.GIT_TIMEOUT
            )
            if result.returncode == 0 and result.stdout.strip():
                info["recent_commits"] = [
                    line for line in result.stdout.strip().split("\n")
                    if line.strip()
                ]

            # Modified files (staged + unstaged)
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                timeout=self.GIT_TIMEOUT
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    if line:
                        status = line[:2]
                        filepath = line[3:].strip()
                        if status.strip():
                            info["modified_files"].append(filepath)
                        else:
                            info["untracked_files"].append(filepath)

        except subprocess.TimeoutExpired:
            # Git operation timed out - return partial info
            pass
        except FileNotFoundError:
            # Git not installed
            pass
        except Exception:
            # Any other error - return partial info
            pass

        self._git_info = info
        return info

    def _extract_from_branch_name(self) -> Optional[str]:
        """
        Parse task hint from branch name.

        Common patterns:
        - feature/add-auth -> "add auth"
        - fix/login-bug -> "login bug"
        - refactor/api-cleanup -> "api cleanup"

        Returns:
            Task hint string, or None if no hint could be extracted.
        """
        git_info = self._extract_from_git()
        branch = git_info.get("branch", "")

        if not branch or branch in self.DEFAULT_BRANCHES:
            return None

        # Remove common prefixes
        for prefix in self.BRANCH_PREFIXES:
            if branch.startswith(prefix):
                branch = branch[len(prefix):]
                break

        # Convert kebab-case/snake_case to words
        task_hint = branch.replace("-", " ").replace("_", " ")

        return task_hint if task_hint else None

    def _extract_from_recent_commits(self) -> List[str]:
        """
        Get recent commit messages.

        Returns:
            List of recent commit messages (up to 5).
        """
        git_info = self._extract_from_git()
        return git_info.get("recent_commits", [])

    def _extract_from_modified_files(self) -> List[str]:
        """
        Get list of modified files.

        Returns:
            List of modified file paths.
        """
        git_info = self._extract_from_git()
        return git_info.get("modified_files", [])

    # =========================================================================
    # Analysis Helpers
    # =========================================================================

    def _infer_task_type(self, task: str) -> str:
        """
        Infer task type from keywords.

        Args:
            task: Task description or branch name hint.

        Returns:
            One of: "Bug fix", "Feature implementation", "Refactoring",
                    "Testing", "Documentation", "Update/upgrade", "General task"
        """
        task_lower = task.lower()

        # Check for bug fix first (highest priority)
        if any(w in task_lower for w in ["fix", "bug", "error", "issue"]):
            return "Bug fix"
        # Check for testing before feature (handles "add tests" case)
        elif any(w in task_lower for w in ["test", "spec"]):
            return "Testing"
        # Check for documentation
        elif any(w in task_lower for w in ["doc", "readme"]):
            return "Documentation"
        # Check for refactoring
        elif any(w in task_lower for w in ["refactor", "cleanup", "improve"]):
            return "Refactoring"
        # Check for updates/upgrades
        elif any(w in task_lower for w in ["update", "upgrade", "version"]):
            return "Update/upgrade"
        # Check for new feature (most general, check last)
        elif any(w in task_lower for w in ["add", "new", "create", "implement"]):
            return "Feature implementation"
        else:
            return "General task"

    def _estimate_files_from_task(self, task: str) -> int:
        """
        Estimate file count from task description.

        Args:
            task: Task description.

        Returns:
            Estimated number of files to be modified.
        """
        task_lower = task.lower()

        # Direct mentions
        if "file" in task_lower:
            # Try to extract number
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

    def _infer_affected_systems(self, task: str) -> List[str]:
        """
        Infer which systems are affected by the task.

        Args:
            task: Task description.

        Returns:
            List of affected system names (e.g., ["frontend", "backend"]).
        """
        task_lower = task.lower()
        systems = []

        for keyword in self.MULTI_SYSTEM_KEYWORDS:
            if keyword in task_lower:
                systems.append(keyword)

        return list(set(systems))

    # =========================================================================
    # Full Analysis (for TaskAnalysis model)
    # =========================================================================

    def analyze_task(self, task: str = "") -> TaskAnalysis:
        """
        Generate complete task analysis.

        Args:
            task: Explicit task description (optional).

        Returns:
            TaskAnalysis with all analysis details.
        """
        # Get task from branch if not provided
        branch_hint = self._extract_from_branch_name()
        task_description = task or branch_hint or ""
        inferred_from = "user input" if task else ("git branch" if branch_hint else "unknown")

        # Extract complexity signals
        complexity = self.extract_complexity_signals(task_description)

        # Get recommendation
        recommendation = self.suggest_approach(complexity)

        # Infer task type
        task_type = self._infer_task_type(task_description)

        # Get affected files
        git_info = self._extract_from_git()
        affected_files = git_info.get("modified_files", [])

        # Generate verification steps
        verification_steps = []
        verification_steps.append("Run existing tests")
        verification_steps.append("Run linter")

        if complexity.has_auth:
            verification_steps.append("Test authentication flows")
        if complexity.has_payments:
            verification_steps.append("Verify payment processing (test mode)")
        if complexity.multi_system_count >= 2:
            verification_steps.append("Test cross-system integration")

        verification_steps.append("Manual feature verification")

        # Identify potential pitfalls
        pitfalls = []
        if complexity.has_auth:
            pitfalls.append("Security: Ensure proper password hashing and token handling")
        if complexity.has_payments:
            pitfalls.append("Payments: Use test mode only, verify webhook signatures")
        if complexity.multi_system_count >= 2:
            pitfalls.append("Cross-system: API contracts may drift between systems")
        if complexity.affected_files_estimate > 10:
            pitfalls.append("Large change: Consider breaking into smaller commits")

        return TaskAnalysis(
            task_description=task_description,
            task_type=task_type,
            inferred_from=inferred_from,
            complexity=complexity,
            recommendation=recommendation,
            verification_steps=verification_steps,
            potential_pitfalls=pitfalls,
            affected_files=affected_files
        )

    def clear_cache(self) -> None:
        """Clear cached git information."""
        self._git_info = None
