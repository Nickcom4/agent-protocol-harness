"""
Agent Protocol Harness - Multi-agent orchestration with true isolation.

This package provides:
- Contract parsing from markdown/YAML
- Signal-based inter-agent coordination
- Filesystem isolation via Docker
- Claude API integration with contract injection
- Orchestration of parallel/sequential agent execution
- Session persistence (survives context exhaustion)
- Auto-verification planning
- Smart error reconciliation
"""

from .models import (
    Contract,
    Signal,
    SignalType,
    AgentState,
    AgentStatus,
    Trajectory,
    ExecutionPlan,
)
from .parser import ContractParser, parse_contracts
from .signals import SignalBroker, create_broker
from .isolator import FilesystemIsolator, IsolatedWorkspace, ScopeEnforcer
from .claude_client import ClaudeClient, AgentConversation, AgentResponse
from .orchestrator import Orchestrator, OrchestratorResult, AgentResult, run_orchestration
from .persistence import SessionPersistence, SessionState, get_resume_prompt
from .verification import VerificationPlanner, VerificationPlan, VerificationCheck
from .reconciler import ErrorReconciler, ResolutionChain, ErrorCategory
from .executor import FullPowerExecutor

__version__ = "0.2.0"

__all__ = [
    # Models
    "Contract",
    "Signal", 
    "SignalType",
    "AgentState",
    "AgentStatus",
    "Trajectory",
    "ExecutionPlan",
    
    # Parser
    "ContractParser",
    "parse_contracts",
    
    # Signals
    "SignalBroker",
    "create_broker",
    
    # Isolation
    "FilesystemIsolator",
    "IsolatedWorkspace",
    "ScopeEnforcer",
    
    # Claude Client
    "ClaudeClient",
    "AgentConversation",
    "AgentResponse",
    
    # Orchestrator
    "Orchestrator",
    "OrchestratorResult",
    "AgentResult",
    "run_orchestration",
    
    # Persistence (v2)
    "SessionPersistence",
    "SessionState",
    "get_resume_prompt",
    
    # Verification (v2)
    "VerificationPlanner",
    "VerificationPlan",
    "VerificationCheck",
    
    # Error Handling (v2)
    "ErrorReconciler",
    "ResolutionChain",
    "ErrorCategory",
    
    # Executor (v2)
    "FullPowerExecutor",
]
