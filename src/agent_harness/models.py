"""
Core data models for the Agent Protocol Harness.

These models represent the contract language from CLAUDE_v3.md
with actual runtime enforcement capabilities.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from pathlib import Path
import re


class Trajectory(Enum):
    """Observable agent state - maps to TRAJ field in protocol."""
    BOUNDED = "BOUNDED"         # Working within scope, making progress
    ESCAPING = "ESCAPING"       # Touching files outside scope or thrashing
    CONVERGED = "CONVERGED"     # All checks pass, work complete
    OSCILLATING = "OSCILLATING" # Same file modified 3+ times


class SignalType(Enum):
    """Inter-agent coordination signals."""
    READY = "READY"       # Work complete, outputs available
    BLOCKED = "BLOCKED"   # Cannot proceed
    DATA = "DATA"         # Intermediate output ready
    FAILED = "FAILED"     # Unrecoverable failure
    ESCALATE = "ESCALATE" # Needs human/parent intervention


class AgentStatus(Enum):
    """Lifecycle status of an agent."""
    PENDING = "pending"       # Waiting for dependencies
    RUNNING = "running"       # Actively executing
    BLOCKED = "blocked"       # Waiting on something
    COMPLETED = "completed"   # Successfully finished
    FAILED = "failed"         # Unrecoverable error
    ESCALATED = "escalated"   # Needs human intervention


@dataclass
class Signal:
    """
    Coordination primitive between agents.
    
    Examples:
        READY:backend
        BLOCKED:auth:missing API key
        DATA:parser:/tmp/ast.json
    """
    type: SignalType
    agent: str
    payload: Optional[str] = None
    timestamp: float = 0.0
    
    def __str__(self) -> str:
        if self.payload:
            return f"{self.type.value}:{self.agent}:{self.payload}"
        return f"{self.type.value}:{self.agent}"
    
    @classmethod
    def parse(cls, s: str) -> "Signal":
        """Parse signal from string format."""
        parts = s.split(":", 2)
        if len(parts) < 2:
            raise ValueError(f"Invalid signal format: {s}")
        
        signal_type = SignalType(parts[0])
        agent = parts[1]
        payload = parts[2] if len(parts) > 2 else None
        
        return cls(type=signal_type, agent=agent, payload=payload)


@dataclass
class Contract:
    """
    Agent contract defining scope, dependencies, and verification.
    
    Maps to SCOPE FORMAT in the protocol:
    ---AGENT:name
    SCOPE:[exact paths]
    CANNOT:[forbidden paths]
    DEPENDS:[signals or none]
    EXPECTS:[inputs]
    PRODUCES:[outputs]
    VERIFY:[how to test]
    ---
    """
    name: str
    scope: list[str]              # Glob patterns for allowed paths
    cannot: list[str] = field(default_factory=list)  # Forbidden paths
    depends: list[str] = field(default_factory=list) # Signal dependencies
    expects: list[str] = field(default_factory=list) # Required inputs
    produces: list[str] = field(default_factory=list) # Expected outputs
    verify: list[str] = field(default_factory=list)   # Verification commands
    goal: str = ""                # The task to accomplish
    
    def path_allowed(self, path: str | Path) -> bool:
        """Check if a path is within scope and not forbidden."""
        path_str = str(path)
        
        # Check forbidden first
        for pattern in self.cannot:
            if self._matches_glob(path_str, pattern):
                return False
        
        # Check allowed
        for pattern in self.scope:
            if self._matches_glob(path_str, pattern):
                return True
        
        return False
    
    def _matches_glob(self, path: str, pattern: str) -> bool:
        """Simple glob matching."""
        # Convert glob to regex
        regex = pattern.replace(".", r"\.").replace("*", ".*").replace("?", ".")
        if not regex.endswith(".*"):
            regex = f"^{regex}.*"
        return bool(re.match(regex, path))
    
    def get_dependency_signals(self) -> list[str]:
        """Extract signal names from depends field."""
        signals = []
        for dep in self.depends:
            if dep.lower() != "none":
                # Handle "READY:backend" format
                if ":" in dep:
                    signals.append(dep)
                else:
                    signals.append(f"READY:{dep}")
        return signals
    
    def to_system_prompt_section(self) -> str:
        """Generate the contract section for Claude's system prompt."""
        return f"""
## YOUR CONTRACT

You are agent `{self.name}` operating under strict isolation.

### SCOPE (Files you CAN access)
{chr(10).join(f"- {s}" for s in self.scope)}

### CANNOT (Files you MUST NOT touch - access will be denied)
{chr(10).join(f"- {c}" for c in self.cannot) if self.cannot else "- (none specified)"}

### DEPENDS (Signals that must exist before you start)
{chr(10).join(f"- {d}" for d in self.depends) if self.depends else "- none"}

### EXPECTS (Inputs you require)
{chr(10).join(f"- {e}" for e in self.expects) if self.expects else "- (none)"}

### PRODUCES (Outputs you must create)
{chr(10).join(f"- {p}" for p in self.produces) if self.produces else "- (none specified)"}

### VERIFY (Commands that must pass before signaling READY)
{chr(10).join(f"- {v}" for v in self.verify) if self.verify else "- (manual verification)"}

### ENFORCEMENT
- File operations outside SCOPE will fail with PermissionError
- You cannot see files in CANNOT paths
- You must signal READY when complete, or BLOCKED/FAILED if stuck
- The orchestrator validates PRODUCES before accepting READY
"""


@dataclass
class AgentState:
    """Runtime state of an agent instance."""
    contract: Contract
    status: AgentStatus = AgentStatus.PENDING
    trajectory: Trajectory = Trajectory.BOUNDED
    
    # Execution tracking
    container_id: Optional[str] = None
    conversation_id: Optional[str] = None
    
    # Progress
    files_modified: list[str] = field(default_factory=list)
    restart_count: int = 0
    max_restarts: int = 3
    
    # Outputs
    signals_emitted: list[Signal] = field(default_factory=list)
    verification_results: dict[str, bool] = field(default_factory=dict)
    
    def can_restart(self) -> bool:
        return self.restart_count < self.max_restarts
    
    def record_file_modification(self, path: str) -> None:
        """Track file modifications for oscillation detection."""
        self.files_modified.append(path)
        
        # Check for oscillation (same file modified 3+ times)
        from collections import Counter
        counts = Counter(self.files_modified)
        if any(c >= 3 for c in counts.values()):
            self.trajectory = Trajectory.OSCILLATING
    
    def check_scope_violation(self, path: str) -> bool:
        """Returns True if path violates scope (ESCAPING)."""
        if not self.contract.path_allowed(path):
            self.trajectory = Trajectory.ESCAPING
            return True
        return False


@dataclass 
class ExecutionPlan:
    """
    Orchestration plan for multiple agents.
    
    Derived from SPLIT analysis in the protocol.
    """
    agents: list[Contract]
    parallel_groups: list[list[str]]  # Groups that can run concurrently
    sequential_order: list[str]       # Strict ordering where needed
    
    @classmethod
    def from_contracts(cls, contracts: list[Contract]) -> "ExecutionPlan":
        """Build execution plan from dependency analysis."""
        # Build dependency graph
        deps: dict[str, set[str]] = {}
        for c in contracts:
            agent_deps = set()
            for sig in c.get_dependency_signals():
                # Extract agent name from "READY:agent" format
                if ":" in sig:
                    agent_deps.add(sig.split(":")[1])
            deps[c.name] = agent_deps
        
        # Topological sort for sequential order
        sequential = []
        remaining = set(deps.keys())
        
        while remaining:
            # Find agents with no unmet dependencies
            ready = {a for a in remaining if deps[a].issubset(set(sequential))}
            if not ready:
                raise ValueError(f"Circular dependency detected among: {remaining}")
            sequential.extend(sorted(ready))
            remaining -= ready
        
        # Group parallel executables (same depth in dependency tree)
        parallel_groups = []
        processed = set()
        
        for agent in sequential:
            if agent in processed:
                continue
            
            # Find all agents that can run with this one
            group = [agent]
            for other in sequential:
                if other in processed or other == agent:
                    continue
                # Can run in parallel if neither depends on the other
                if other not in deps[agent] and agent not in deps[other]:
                    # And they have the same dependencies
                    if deps[agent] == deps[other]:
                        group.append(other)
            
            parallel_groups.append(group)
            processed.update(group)
        
        return cls(
            agents=contracts,
            parallel_groups=parallel_groups,
            sequential_order=sequential
        )
