"""
Verification Planner - Auto-generates verification plans.

For each agent contract, generates a comprehensive verification plan:
1. Automated checks (tests, linting, type checking)
2. Endpoint verification (for APIs)
3. Manual verification prompts (for UX)
4. Integration checks (cross-agent)

The plan is presented to the user for review/modification
BEFORE execution, not after.
"""

from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path
import re


@dataclass
class VerificationCheck:
    """A single verification check."""
    type: str  # "command", "endpoint", "file_exists", "manual", "integration"
    description: str
    
    # For command type
    command: Optional[str] = None
    expected_exit_code: int = 0
    expected_output_contains: Optional[str] = None
    
    # For endpoint type
    url: Optional[str] = None
    method: str = "GET"
    expected_status: int = 200
    request_body: Optional[dict] = None
    
    # For file_exists type
    file_path: Optional[str] = None
    file_contains: Optional[str] = None
    
    # For manual type
    prompt: Optional[str] = None  # What to ask user
    
    # For integration type
    depends_on_agents: list[str] = field(default_factory=list)
    
    # Result tracking
    passed: Optional[bool] = None
    output: str = ""
    error: str = ""


@dataclass
class VerificationPlan:
    """Complete verification plan for an agent."""
    agent_name: str
    
    # Pre-execution checks (environment ready?)
    pre_checks: list[VerificationCheck] = field(default_factory=list)
    
    # Post-execution automated checks
    automated_checks: list[VerificationCheck] = field(default_factory=list)
    
    # Manual verification (user must confirm)
    manual_checks: list[VerificationCheck] = field(default_factory=list)
    
    # Integration checks (require other agents)
    integration_checks: list[VerificationCheck] = field(default_factory=list)
    
    # Rollback plan if verification fails
    rollback_commands: list[str] = field(default_factory=list)


class VerificationPlanner:
    """
    Generates verification plans from contracts.
    
    Analyzes:
    - Contract's PRODUCES field → file/endpoint checks
    - Contract's VERIFY field → command checks
    - Contract's scope → test discovery
    - Heuristics for common patterns
    """
    
    def __init__(self, repo_root: Path):
        self.repo_root = Path(repo_root)
    
    def generate_plan(self, contract: "Contract") -> VerificationPlan:
        """Generate a verification plan for a contract."""
        plan = VerificationPlan(agent_name=contract.name)
        
        # Pre-checks: verify dependencies exist
        plan.pre_checks = self._generate_pre_checks(contract)
        
        # Parse explicit verify commands
        for cmd in contract.verify:
            plan.automated_checks.append(VerificationCheck(
                type="command",
                description=f"Contract verify: {cmd}",
                command=cmd,
            ))
        
        # Generate checks from PRODUCES
        for produce in contract.produces:
            checks = self._infer_checks_from_produce(produce, contract)
            plan.automated_checks.extend(checks)
        
        # Discover tests in scope
        test_checks = self._discover_tests(contract)
        plan.automated_checks.extend(test_checks)
        
        # Generate manual checks for UX-related produces
        manual = self._generate_manual_checks(contract)
        plan.manual_checks.extend(manual)
        
        # Integration checks if depends on other agents
        if contract.depends:
            integration = self._generate_integration_checks(contract)
            plan.integration_checks.extend(integration)
        
        # Rollback plan
        plan.rollback_commands = self._generate_rollback(contract)
        
        return plan
    
    def _generate_pre_checks(self, contract: "Contract") -> list[VerificationCheck]:
        """Generate pre-execution environment checks."""
        checks = []
        
        # Check dependencies are satisfied (signals exist)
        for dep in contract.depends:
            if dep.lower() != "none":
                checks.append(VerificationCheck(
                    type="signal",
                    description=f"Dependency signal exists: {dep}",
                ))
        
        # Check expected inputs exist
        for expect in contract.expects:
            if "/" in expect:  # Looks like a path or endpoint
                if expect.startswith("/api") or expect.startswith("http"):
                    checks.append(VerificationCheck(
                        type="endpoint",
                        description=f"Expected endpoint available: {expect}",
                        url=expect,
                        method="OPTIONS",  # Just check it exists
                    ))
                else:
                    checks.append(VerificationCheck(
                        type="file_exists",
                        description=f"Expected file exists: {expect}",
                        file_path=expect,
                    ))
        
        return checks
    
    def _infer_checks_from_produce(
        self, 
        produce: str, 
        contract: "Contract"
    ) -> list[VerificationCheck]:
        """Infer verification checks from a PRODUCES item."""
        checks = []
        produce_lower = produce.lower()
        
        # API endpoint pattern
        endpoint_match = re.search(r'(/api/\S+)', produce)
        if endpoint_match or "endpoint" in produce_lower:
            url = endpoint_match.group(1) if endpoint_match else None
            
            # Infer method from description
            method = "GET"
            if "post" in produce_lower or "create" in produce_lower or "register" in produce_lower:
                method = "POST"
            elif "put" in produce_lower or "update" in produce_lower:
                method = "PUT"
            elif "delete" in produce_lower:
                method = "DELETE"
            
            checks.append(VerificationCheck(
                type="endpoint",
                description=f"Endpoint works: {produce}",
                url=url or "/api/unknown",
                method=method,
                expected_status=200 if method == "GET" else 201,
            ))
        
        # File pattern
        file_match = re.search(r'(\S+\.(jsx?|tsx?|py|go|rs|java|vue|svelte))', produce)
        if file_match:
            filepath = file_match.group(1)
            # Find in scope
            for scope in contract.scope:
                possible_path = scope.rstrip('/') + '/' + filepath
                checks.append(VerificationCheck(
                    type="file_exists",
                    description=f"File created: {filepath}",
                    file_path=possible_path,
                ))
                break
        
        # Component pattern (React, Vue, etc.)
        if "component" in produce_lower or "page" in produce_lower:
            checks.append(VerificationCheck(
                type="command",
                description=f"Component builds: {produce}",
                command="npm run build 2>&1 | head -50",
                expected_exit_code=0,
            ))
        
        # Database pattern
        if "table" in produce_lower or "migration" in produce_lower:
            checks.append(VerificationCheck(
                type="command",
                description=f"Database migrated: {produce}",
                command="npx prisma migrate status || npm run migrate:status",
                expected_exit_code=0,
            ))
        
        return checks
    
    def _discover_tests(self, contract: "Contract") -> list[VerificationCheck]:
        """Discover test files in scope."""
        checks = []
        
        for scope in contract.scope:
            scope_path = self.repo_root / scope.rstrip('/')
            if not scope_path.exists():
                continue
            
            # Find test files
            test_patterns = ['*test*.py', '*_test.py', '*.test.js', '*.test.ts', 
                           '*.spec.js', '*.spec.ts', '*Test.java']
            
            for pattern in test_patterns:
                for test_file in scope_path.rglob(pattern):
                    rel_path = test_file.relative_to(self.repo_root)
                    
                    # Determine test runner
                    if test_file.suffix == '.py':
                        cmd = f"pytest {rel_path} -v"
                    elif test_file.suffix in ('.js', '.ts', '.jsx', '.tsx'):
                        cmd = f"npm test -- --testPathPattern={rel_path}"
                    else:
                        continue
                    
                    checks.append(VerificationCheck(
                        type="command",
                        description=f"Tests pass: {rel_path}",
                        command=cmd,
                        expected_exit_code=0,
                    ))
        
        return checks
    
    def _generate_manual_checks(self, contract: "Contract") -> list[VerificationCheck]:
        """Generate manual verification prompts."""
        checks = []
        
        for produce in contract.produces:
            produce_lower = produce.lower()
            
            # UI components need visual verification
            if any(term in produce_lower for term in ['page', 'form', 'button', 'modal', 'ui']):
                checks.append(VerificationCheck(
                    type="manual",
                    description=f"Visual check: {produce}",
                    prompt=f"Please verify that {produce} looks correct and functions as expected.",
                ))
            
            # Auth flows need manual testing
            if any(term in produce_lower for term in ['login', 'register', 'auth', 'logout']):
                checks.append(VerificationCheck(
                    type="manual",
                    description=f"Auth flow: {produce}",
                    prompt=f"Please test the {produce} flow manually to ensure it works end-to-end.",
                ))
        
        return checks
    
    def _generate_integration_checks(self, contract: "Contract") -> list[VerificationCheck]:
        """Generate integration checks with dependent agents."""
        checks = []
        
        for dep in contract.depends:
            if dep.lower() == "none":
                continue
            
            # Extract agent name from "READY:agent"
            agent = dep.split(":")[-1] if ":" in dep else dep
            
            checks.append(VerificationCheck(
                type="integration",
                description=f"Integration with {agent}",
                depends_on_agents=[agent],
                prompt=f"Verify that this agent's outputs integrate correctly with {agent}'s outputs.",
            ))
        
        return checks
    
    def _generate_rollback(self, contract: "Contract") -> list[str]:
        """Generate rollback commands if verification fails."""
        rollback = []
        
        # Git rollback is always available
        rollback.append("git checkout HEAD~1 -- .")
        
        # Database rollback if relevant
        for scope in contract.scope:
            if any(term in scope for term in ['database', 'migrations', 'prisma']):
                rollback.append("npx prisma migrate reset --skip-generate")
                break
        
        return rollback
    
    def format_plan_for_review(self, plan: VerificationPlan) -> str:
        """Format plan as readable text for user review."""
        lines = [
            f"## Verification Plan: {plan.agent_name}",
            "",
        ]
        
        if plan.pre_checks:
            lines.append("### Pre-Execution Checks")
            for check in plan.pre_checks:
                lines.append(f"- [ ] {check.description}")
            lines.append("")
        
        if plan.automated_checks:
            lines.append("### Automated Verification")
            for check in plan.automated_checks:
                if check.command:
                    lines.append(f"- [ ] `{check.command}`")
                    lines.append(f"      {check.description}")
                elif check.url:
                    lines.append(f"- [ ] {check.method} {check.url} → {check.expected_status}")
                else:
                    lines.append(f"- [ ] {check.description}")
            lines.append("")
        
        if plan.manual_checks:
            lines.append("### Manual Verification (You'll Be Asked)")
            for check in plan.manual_checks:
                lines.append(f"- [ ] {check.description}")
                if check.prompt:
                    lines.append(f"      _{check.prompt}_")
            lines.append("")
        
        if plan.integration_checks:
            lines.append("### Integration Checks")
            for check in plan.integration_checks:
                lines.append(f"- [ ] {check.description}")
            lines.append("")
        
        if plan.rollback_commands:
            lines.append("### Rollback (If Verification Fails)")
            for cmd in plan.rollback_commands:
                lines.append(f"```")
                lines.append(cmd)
                lines.append(f"```")
        
        return "\n".join(lines)
