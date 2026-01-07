"""
Session Persistence - Survives context exhaustion.

Saves complete session state to disk so that:
1. If Claude runs out of context, next session can resume
2. User can close terminal, come back later
3. Crash recovery

State is saved after every significant action.
"""

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, Any
import hashlib


@dataclass
class AgentResultPersist:
    """Serializable agent result."""
    agent_name: str
    status: str
    files_created: list[str]
    files_modified: list[str]
    verification_passed: bool
    verification_output: str = ""
    error: Optional[str] = None
    duration_seconds: float = 0.0
    restart_count: int = 0


@dataclass
class ContractPersist:
    """Serializable contract."""
    name: str
    goal: str
    scope: list[str]
    cannot: list[str]
    depends: list[str]
    expects: list[str]
    produces: list[str]
    verify: list[str]
    
    # Verification plan (auto-generated or user-modified)
    verification_plan: list[dict] = field(default_factory=list)
    # e.g. [{"type": "test", "command": "npm test", "expected": "exit 0"},
    #       {"type": "manual", "description": "Login flow works"},
    #       {"type": "endpoint", "url": "/api/auth/login", "method": "POST"}]


@dataclass
class SessionState:
    """
    Complete session state - persisted to disk.
    
    Designed to capture everything needed to resume
    after context exhaustion or restart.
    """
    # Identity
    session_id: str = ""
    created_at: str = ""
    updated_at: str = ""
    
    # Task
    original_goal: str = ""
    refined_goal: str = ""  # After clarification
    
    # Planning phase
    analysis_complete: bool = False
    analysis_result: dict = field(default_factory=dict)
    
    proposed_contracts: list[ContractPersist] = field(default_factory=list)
    verification_plan_approved: bool = False
    execution_plan_approved: bool = False
    
    # User decisions (for resume context)
    user_decisions: list[dict] = field(default_factory=list)
    # e.g. [{"decision": "use bcrypt not argon2", "reason": "existing dep"},
    #       {"decision": "rate limit 100/15min", "reason": "conservative"}]
    
    # Git state
    original_branch: str = ""
    session_branch: str = ""
    commits: list[dict] = field(default_factory=list)
    # e.g. [{"hash": "abc123", "message": "checkpoint: backend", "agent": "backend"}]
    
    # Execution state
    execution_started: bool = False
    current_agent: Optional[str] = None
    completed_agents: list[str] = field(default_factory=list)
    failed_agents: list[str] = field(default_factory=list)
    pending_agents: list[str] = field(default_factory=list)
    
    # Results
    results: dict[str, AgentResultPersist] = field(default_factory=dict)
    
    # Verification phase
    verification_started: bool = False
    verification_results: list[dict] = field(default_factory=list)
    # e.g. [{"check": "npm test", "passed": True, "output": "..."},
    #       {"check": "manual: login flow", "passed": None, "awaiting_user": True}]
    
    # Error recovery
    errors_encountered: list[dict] = field(default_factory=list)
    # e.g. [{"agent": "backend", "error": "missing dep", "resolution": "installed bcrypt"}]
    auto_resolutions: list[dict] = field(default_factory=list)
    escalations: list[dict] = field(default_factory=list)
    
    # Feedback history (for context on resume)
    feedback_history: list[dict] = field(default_factory=list)
    iteration: int = 0
    
    # Phase tracking
    phase: str = "not_started"
    # Phases: not_started → analyzing → planning → plan_review → 
    #         verification_planning → executing → verifying → 
    #         feedback → ready_to_finalize → finalized
    
    # Resume hints (what to do next)
    next_action: str = ""
    resume_context: str = ""  # Human-readable summary for new context window


class SessionPersistence:
    """
    Manages session state persistence.
    
    State is saved to .agent-harness/session.json in repo root.
    """
    
    def __init__(self, repo_root: Path):
        self.repo_root = Path(repo_root)
        self.state_dir = self.repo_root / ".agent-harness"
        self.state_file = self.state_dir / "session.json"
        self.history_dir = self.state_dir / "history"
        
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.history_dir.mkdir(parents=True, exist_ok=True)
    
    def load(self) -> Optional[SessionState]:
        """Load existing session or return None."""
        if not self.state_file.exists():
            return None
        
        try:
            data = json.loads(self.state_file.read_text())
            return self._dict_to_state(data)
        except (json.JSONDecodeError, KeyError) as e:
            # Corrupted state - backup and return None
            backup = self.state_file.with_suffix('.json.corrupted')
            self.state_file.rename(backup)
            return None
    
    def save(self, state: SessionState) -> None:
        """Save session state to disk."""
        state.updated_at = datetime.now().isoformat()
        
        # Update resume context
        state.resume_context = self._generate_resume_context(state)
        
        data = self._state_to_dict(state)
        
        # Atomic write
        tmp_file = self.state_file.with_suffix('.tmp')
        tmp_file.write_text(json.dumps(data, indent=2, default=str))
        tmp_file.rename(self.state_file)
    
    def create_new(self, goal: str) -> SessionState:
        """Create a new session."""
        session_id = hashlib.sha256(
            f"{goal}_{datetime.now().isoformat()}".encode()
        ).hexdigest()[:12]
        
        state = SessionState(
            session_id=session_id,
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
            original_goal=goal,
            phase="analyzing",
            next_action="analyze_task",
        )
        
        self.save(state)
        return state
    
    def archive(self, state: SessionState) -> Path:
        """Archive completed session to history."""
        archive_name = f"{state.session_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        archive_path = self.history_dir / archive_name
        
        data = self._state_to_dict(state)
        archive_path.write_text(json.dumps(data, indent=2, default=str))
        
        # Remove active session
        if self.state_file.exists():
            self.state_file.unlink()
        
        return archive_path
    
    def _generate_resume_context(self, state: SessionState) -> str:
        """
        Generate human-readable context for resuming.
        
        This is injected into Claude's context when session resumes
        so it understands where we left off.
        """
        lines = [
            f"# Session Resume Context",
            f"",
            f"## Original Goal",
            f"{state.original_goal}",
            f"",
            f"## Current Phase: {state.phase}",
            f"",
        ]
        
        if state.user_decisions:
            lines.append("## User Decisions Made")
            for d in state.user_decisions:
                lines.append(f"- {d['decision']}: {d.get('reason', '')}")
            lines.append("")
        
        if state.proposed_contracts:
            lines.append("## Planned Agents")
            for c in state.proposed_contracts:
                status = "✓" if c.name in state.completed_agents else "○"
                if c.name in state.failed_agents:
                    status = "✗"
                if c.name == state.current_agent:
                    status = "▶"
                lines.append(f"  {status} {c.name}: {c.goal[:50]}...")
            lines.append("")
        
        if state.errors_encountered:
            lines.append("## Errors Encountered")
            for e in state.errors_encountered[-3:]:  # Last 3
                lines.append(f"- {e['agent']}: {e['error'][:100]}")
                if e.get('resolution'):
                    lines.append(f"  → Resolved: {e['resolution']}")
            lines.append("")
        
        if state.commits:
            lines.append("## Git Checkpoints")
            for c in state.commits[-5:]:  # Last 5
                lines.append(f"- {c['hash']}: {c['message']}")
            lines.append("")
        
        lines.append(f"## Next Action")
        lines.append(f"{state.next_action}")
        lines.append("")
        
        if state.phase == "verifying":
            pending = [v for v in state.verification_results if v.get('awaiting_user')]
            if pending:
                lines.append("## Awaiting User Verification")
                for v in pending:
                    lines.append(f"- {v['check']}")
        
        return "\n".join(lines)
    
    def _state_to_dict(self, state: SessionState) -> dict:
        """Convert state to serializable dict."""
        d = asdict(state)
        # Convert nested dataclasses
        d['proposed_contracts'] = [asdict(c) if hasattr(c, '__dataclass_fields__') else c 
                                   for c in state.proposed_contracts]
        d['results'] = {k: asdict(v) if hasattr(v, '__dataclass_fields__') else v 
                        for k, v in state.results.items()}
        return d
    
    def _dict_to_state(self, data: dict) -> SessionState:
        """Convert dict back to state."""
        # Convert nested structures
        contracts = [ContractPersist(**c) for c in data.get('proposed_contracts', [])]
        results = {k: AgentResultPersist(**v) for k, v in data.get('results', {}).items()}
        
        data['proposed_contracts'] = contracts
        data['results'] = results
        
        return SessionState(**data)


def get_resume_prompt(state: SessionState) -> str:
    """
    Generate a prompt to inject when resuming a session.
    
    This helps Claude understand the context even in a fresh context window.
    """
    return f"""
[RESUMING PREVIOUS SESSION]

You are resuming an agent orchestration session that was interrupted 
(likely due to context exhaustion).

{state.resume_context}

The session state has been loaded from disk. You have access to all 
previous decisions, commits, and progress.

Please acknowledge the resume and continue from where we left off.
The next action is: {state.next_action}
"""
