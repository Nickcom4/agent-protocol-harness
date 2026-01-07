"""
Error Reconciliation - Analyzes errors and attempts auto-resolution.

Instead of just retrying with feedback, this:
1. Parses error output to identify root cause
2. Checks common fixes (missing deps, wrong paths, etc.)
3. Applies fixes automatically when safe
4. Escalates to user when uncertain

Common auto-resolvable issues:
- Missing npm/pip packages
- Import errors (wrong path)
- Type errors (with clear fixes)
- Port conflicts
- Permission issues
- Missing environment variables (with .env.example)
"""

import re
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional, Callable


class ErrorCategory(Enum):
    MISSING_DEPENDENCY = "missing_dependency"
    IMPORT_ERROR = "import_error"
    TYPE_ERROR = "type_error"
    SYNTAX_ERROR = "syntax_error"
    PORT_CONFLICT = "port_conflict"
    PERMISSION_DENIED = "permission_denied"
    FILE_NOT_FOUND = "file_not_found"
    ENV_VAR_MISSING = "env_var_missing"
    TEST_FAILURE = "test_failure"
    BUILD_ERROR = "build_error"
    NETWORK_ERROR = "network_error"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"


@dataclass
class ErrorAnalysis:
    """Result of analyzing an error."""
    category: ErrorCategory
    description: str
    root_cause: str
    
    # Auto-resolution
    can_auto_resolve: bool = False
    resolution_command: Optional[str] = None
    resolution_description: Optional[str] = None
    
    # If can't auto-resolve
    suggested_fix: Optional[str] = None
    requires_user_input: bool = False
    user_prompt: Optional[str] = None
    
    # For learning
    error_pattern: str = ""
    raw_output: str = ""


@dataclass
class Resolution:
    """Applied resolution and its outcome."""
    analysis: ErrorAnalysis
    command_run: Optional[str] = None
    success: bool = False
    output: str = ""
    follow_up_needed: bool = False


class ErrorReconciler:
    """
    Analyzes errors and attempts automatic resolution.
    
    Uses pattern matching and heuristics to identify
    common issues and their fixes.
    """
    
    def __init__(self, repo_root: Path):
        self.repo_root = Path(repo_root)
        self._load_patterns()
    
    def _load_patterns(self):
        """Load error patterns and their resolutions."""
        self.patterns = {
            # NPM/Node errors
            r"Cannot find module '([^']+)'": {
                "category": ErrorCategory.MISSING_DEPENDENCY,
                "extract": lambda m: m.group(1),
                "resolution": lambda pkg: f"npm install {pkg}",
                "auto_resolve": True,
            },
            r"Module not found: Error: Can't resolve '([^']+)'": {
                "category": ErrorCategory.MISSING_DEPENDENCY,
                "extract": lambda m: m.group(1),
                "resolution": lambda pkg: f"npm install {pkg}",
                "auto_resolve": True,
            },
            r"npm ERR! missing: ([^,]+)": {
                "category": ErrorCategory.MISSING_DEPENDENCY,
                "extract": lambda m: m.group(1),
                "resolution": lambda pkg: f"npm install {pkg}",
                "auto_resolve": True,
            },
            
            # Python errors
            r"ModuleNotFoundError: No module named '([^']+)'": {
                "category": ErrorCategory.MISSING_DEPENDENCY,
                "extract": lambda m: m.group(1).split('.')[0],
                "resolution": lambda pkg: f"pip install {pkg}",
                "auto_resolve": True,
            },
            r"ImportError: cannot import name '([^']+)' from '([^']+)'": {
                "category": ErrorCategory.IMPORT_ERROR,
                "extract": lambda m: (m.group(1), m.group(2)),
                "resolution": None,  # Needs investigation
                "auto_resolve": False,
                "suggested_fix": "Check if the import name is correct and the module version is compatible",
            },
            
            # Port conflicts
            r"EADDRINUSE.*:(\d+)": {
                "category": ErrorCategory.PORT_CONFLICT,
                "extract": lambda m: m.group(1),
                "resolution": lambda port: f"lsof -ti:{port} | xargs kill -9",
                "auto_resolve": True,
                "confirm": True,  # Ask before killing
            },
            r"address already in use.*:(\d+)": {
                "category": ErrorCategory.PORT_CONFLICT,
                "extract": lambda m: m.group(1),
                "resolution": lambda port: f"lsof -ti:{port} | xargs kill -9",
                "auto_resolve": True,
                "confirm": True,
            },
            
            # Environment variables
            r"Error: ([\w_]+) is not defined|missing.*([\w_]+).*environment": {
                "category": ErrorCategory.ENV_VAR_MISSING,
                "extract": lambda m: m.group(1) or m.group(2),
                "resolution": None,
                "auto_resolve": False,
                "suggested_fix": "Check .env.example for required variables",
            },
            
            # File not found
            r"ENOENT.*'([^']+)'|FileNotFoundError.*'([^']+)'": {
                "category": ErrorCategory.FILE_NOT_FOUND,
                "extract": lambda m: m.group(1) or m.group(2),
                "resolution": None,
                "auto_resolve": False,
            },
            
            # Permission errors
            r"EACCES|PermissionError|permission denied": {
                "category": ErrorCategory.PERMISSION_DENIED,
                "extract": lambda m: None,
                "resolution": None,
                "auto_resolve": False,
                "suggested_fix": "Check file permissions. May need sudo or chmod.",
            },
            
            # Syntax errors
            r"SyntaxError: ([^\n]+)": {
                "category": ErrorCategory.SYNTAX_ERROR,
                "extract": lambda m: m.group(1),
                "resolution": None,
                "auto_resolve": False,
            },
            r"Parsing error: ([^\n]+)": {
                "category": ErrorCategory.SYNTAX_ERROR,
                "extract": lambda m: m.group(1),
                "resolution": None,
                "auto_resolve": False,
            },
            
            # Type errors
            r"TypeError: ([^\n]+)": {
                "category": ErrorCategory.TYPE_ERROR,
                "extract": lambda m: m.group(1),
                "resolution": None,
                "auto_resolve": False,
            },
            
            # Test failures (not auto-resolvable but categorizable)
            r"(\d+) failing|FAIL\s+(\S+)|AssertionError": {
                "category": ErrorCategory.TEST_FAILURE,
                "extract": lambda m: m.group(0),
                "resolution": None,
                "auto_resolve": False,
            },
            
            # Build errors
            r"Build failed|Compilation failed|error TS\d+": {
                "category": ErrorCategory.BUILD_ERROR,
                "extract": lambda m: m.group(0),
                "resolution": None,
                "auto_resolve": False,
            },
            
            # Network errors
            r"ECONNREFUSED|ETIMEDOUT|network.*(error|failed)": {
                "category": ErrorCategory.NETWORK_ERROR,
                "extract": lambda m: m.group(0),
                "resolution": None,
                "auto_resolve": False,
                "suggested_fix": "Check if required services are running",
            },
        }
    
    def analyze(self, error_output: str, context: dict = None) -> ErrorAnalysis:
        """
        Analyze error output and return diagnosis.
        
        Args:
            error_output: The error text (stderr, exception, etc.)
            context: Additional context (agent name, command run, etc.)
        """
        context = context or {}
        
        for pattern, config in self.patterns.items():
            match = re.search(pattern, error_output, re.IGNORECASE | re.MULTILINE)
            if match:
                extracted = config["extract"](match) if config["extract"] else None
                
                resolution_cmd = None
                if config.get("resolution") and extracted:
                    if callable(config["resolution"]):
                        resolution_cmd = config["resolution"](extracted)
                    else:
                        resolution_cmd = config["resolution"]
                
                return ErrorAnalysis(
                    category=config["category"],
                    description=f"{config['category'].value}: {extracted or match.group(0)}",
                    root_cause=str(extracted) if extracted else match.group(0),
                    can_auto_resolve=config.get("auto_resolve", False),
                    resolution_command=resolution_cmd,
                    resolution_description=f"Run: {resolution_cmd}" if resolution_cmd else None,
                    suggested_fix=config.get("suggested_fix"),
                    requires_user_input=config.get("confirm", False),
                    error_pattern=pattern,
                    raw_output=error_output[:1000],
                )
        
        # No pattern matched
        return ErrorAnalysis(
            category=ErrorCategory.UNKNOWN,
            description="Unknown error",
            root_cause=error_output[:500],
            can_auto_resolve=False,
            suggested_fix="Review the error output manually",
            raw_output=error_output[:1000],
        )
    
    async def attempt_resolution(
        self, 
        analysis: ErrorAnalysis,
        confirm_callback: Callable[[str], bool] = None,
    ) -> Resolution:
        """
        Attempt to resolve an analyzed error.
        
        Args:
            analysis: The error analysis
            confirm_callback: Optional callback to confirm dangerous operations
        """
        if not analysis.can_auto_resolve or not analysis.resolution_command:
            return Resolution(
                analysis=analysis,
                success=False,
                output="Cannot auto-resolve this error type",
                follow_up_needed=True,
            )
        
        # Check if confirmation needed
        if analysis.requires_user_input and confirm_callback:
            confirmed = confirm_callback(
                f"Auto-fix will run: {analysis.resolution_command}\nProceed?"
            )
            if not confirmed:
                return Resolution(
                    analysis=analysis,
                    success=False,
                    output="User declined auto-resolution",
                    follow_up_needed=True,
                )
        
        # Run resolution command
        try:
            result = subprocess.run(
                analysis.resolution_command,
                shell=True,
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                timeout=120,
            )
            
            success = result.returncode == 0
            
            return Resolution(
                analysis=analysis,
                command_run=analysis.resolution_command,
                success=success,
                output=result.stdout + result.stderr,
                follow_up_needed=not success,
            )
        
        except subprocess.TimeoutExpired:
            return Resolution(
                analysis=analysis,
                command_run=analysis.resolution_command,
                success=False,
                output="Resolution command timed out",
                follow_up_needed=True,
            )
        except Exception as e:
            return Resolution(
                analysis=analysis,
                command_run=analysis.resolution_command,
                success=False,
                output=str(e),
                follow_up_needed=True,
            )
    
    def format_for_retry(self, analysis: ErrorAnalysis, resolution: Resolution = None) -> str:
        """
        Format error analysis as context for retry.
        
        This is included in the agent's next prompt to help it understand
        what went wrong and what was tried.
        """
        lines = [
            "## Previous Error Analysis",
            "",
            f"**Category:** {analysis.category.value}",
            f"**Root Cause:** {analysis.root_cause}",
            "",
        ]
        
        if resolution and resolution.command_run:
            lines.extend([
                "**Auto-Resolution Attempted:**",
                f"```",
                f"$ {resolution.command_run}",
                f"{resolution.output[:500]}",
                f"```",
                f"**Result:** {'Success' if resolution.success else 'Failed'}",
                "",
            ])
        
        if analysis.suggested_fix:
            lines.extend([
                "**Suggested Fix:**",
                analysis.suggested_fix,
                "",
            ])
        
        lines.extend([
            "Please address this issue in your next attempt.",
            "",
        ])
        
        return "\n".join(lines)


class ResolutionChain:
    """
    Chains multiple resolution attempts with escalation.
    
    Tries auto-resolution first, then suggests fixes,
    then escalates to user if all fails.
    """
    
    def __init__(self, reconciler: ErrorReconciler, max_attempts: int = 3):
        self.reconciler = reconciler
        self.max_attempts = max_attempts
        self.attempts: list[Resolution] = []
    
    async def resolve_with_escalation(
        self,
        error_output: str,
        context: dict = None,
        user_callback: Callable[[str], str] = None,
    ) -> tuple[bool, str]:
        """
        Attempt to resolve error with escalation chain.
        
        Returns:
            (resolved: bool, message: str)
        """
        analysis = self.reconciler.analyze(error_output, context)
        
        # Level 1: Auto-resolution
        if analysis.can_auto_resolve:
            resolution = await self.reconciler.attempt_resolution(analysis)
            self.attempts.append(resolution)
            
            if resolution.success:
                return True, f"Auto-resolved: {analysis.resolution_description}"
        
        # Level 2: Suggested fixes (for retry)
        if analysis.suggested_fix:
            return False, self.reconciler.format_for_retry(
                analysis, 
                self.attempts[-1] if self.attempts else None
            )
        
        # Level 3: Escalate to user
        if user_callback:
            user_input = user_callback(
                f"Error could not be auto-resolved:\n\n"
                f"{analysis.description}\n\n"
                f"Raw output:\n{analysis.raw_output[:500]}\n\n"
                f"How would you like to proceed?"
            )
            return False, f"User guidance: {user_input}"
        
        return False, "Error requires manual intervention"
