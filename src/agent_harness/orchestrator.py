"""
Orchestrator - Main coordination engine for multi-agent execution.

Provides:
- Contract validation and execution planning
- Agent lifecycle management
- Signal-based coordination
- Workspace isolation
- Result aggregation
"""

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Callable, Any
from datetime import datetime

from .models import (
    Contract, Signal, SignalType, AgentState, AgentStatus,
    Trajectory, ExecutionPlan
)
from .parser import ContractParser
from .signals import SignalBroker, create_broker
from .isolator import FilesystemIsolator, IsolatedWorkspace
from .claude_client import ClaudeClient, AgentConversation, AgentResponse


logger = logging.getLogger(__name__)


@dataclass
class AgentResult:
    """Result of an agent's execution."""
    agent_name: str
    status: AgentStatus
    signals: list[Signal]
    files_modified: dict[str, str]  # path -> content
    files_created: dict[str, str]
    verification_passed: bool
    error: Optional[str] = None
    duration_seconds: float = 0.0
    restart_count: int = 0
    final_response: Optional[AgentResponse] = None


@dataclass
class OrchestratorResult:
    """Result of orchestrating multiple agents."""
    success: bool
    agents: dict[str, AgentResult]
    total_duration_seconds: float
    execution_order: list[str]
    signals: list[Signal]
    errors: list[str] = field(default_factory=list)


class Orchestrator:
    """
    Coordinates multi-agent execution with isolation and signaling.
    
    Flow:
    1. Parse and validate contracts
    2. Build execution plan from dependencies  
    3. Create isolated workspaces
    4. Run agents (parallel where possible)
    5. Coordinate via signals
    6. Aggregate and return results
    """
    
    def __init__(
        self,
        repo_root: Path,
        api_key: Optional[str] = None,
        model: str = "claude-sonnet-4-20250514",
        protocol_path: Optional[Path] = None,
        signal_backend: str = "memory",
        use_docker: bool = False,
        max_concurrent: int = 4,
        agent_timeout: float = 600,  # 10 minutes per agent
    ):
        self.repo_root = Path(repo_root).resolve()
        self.model = model
        self.protocol_path = protocol_path
        self.signal_backend = signal_backend
        self.use_docker = use_docker
        self.max_concurrent = max_concurrent
        self.agent_timeout = agent_timeout
        
        # Components
        self.client = ClaudeClient(
            api_key=api_key,
            model=model,
            protocol_path=protocol_path,
        )
        self.broker = create_broker(signal_backend)
        self.isolator = FilesystemIsolator(
            repo_root=self.repo_root,
            use_docker=use_docker,
        )
        
        # State
        self.agent_states: dict[str, AgentState] = {}
        self.workspaces: dict[str, IsolatedWorkspace] = {}
        self.results: dict[str, AgentResult] = {}
    
    async def run(
        self,
        contracts: list[Contract],
        goals: Optional[dict[str, str]] = None,
    ) -> OrchestratorResult:
        """
        Execute a set of agent contracts.
        
        Args:
            contracts: List of agent contracts
            goals: Optional per-agent goals (defaults to contract.goal)
            
        Returns:
            OrchestratorResult with all outcomes
        """
        start_time = datetime.now()
        goals = goals or {}
        
        # Validate contracts
        errors = ContractParser.validate_contracts(contracts)
        if errors:
            return OrchestratorResult(
                success=False,
                agents={},
                total_duration_seconds=0,
                execution_order=[],
                signals=[],
                errors=errors,
            )
        
        # Build execution plan
        plan = ExecutionPlan.from_contracts(contracts)
        logger.info(f"Execution plan: {plan.sequential_order}")
        logger.info(f"Parallel groups: {plan.parallel_groups}")
        
        # Initialize agent states
        for contract in contracts:
            contract.goal = goals.get(contract.name, contract.goal)
            self.agent_states[contract.name] = AgentState(contract=contract)
        
        # Clear any previous signals
        await self.broker.clear()
        
        # Execute agents according to plan
        execution_order = []
        all_signals = []
        
        try:
            for group in plan.parallel_groups:
                # Run group in parallel (up to max_concurrent)
                semaphore = asyncio.Semaphore(self.max_concurrent)
                
                async def run_with_semaphore(agent_name: str):
                    async with semaphore:
                        return await self._run_agent(agent_name)
                
                group_results = await asyncio.gather(
                    *[run_with_semaphore(name) for name in group],
                    return_exceptions=True
                )
                
                # Process results
                for name, result in zip(group, group_results):
                    execution_order.append(name)
                    
                    if isinstance(result, Exception):
                        self.results[name] = AgentResult(
                            agent_name=name,
                            status=AgentStatus.FAILED,
                            signals=[],
                            files_modified={},
                            files_created={},
                            verification_passed=False,
                            error=str(result),
                        )
                    else:
                        self.results[name] = result
                        all_signals.extend(result.signals)
                
                # Check for failures that should stop execution
                for name in group:
                    result = self.results.get(name)
                    if result and result.status == AgentStatus.FAILED:
                        # Check if dependent agents exist
                        has_dependents = any(
                            f"READY:{name}" in c.get_dependency_signals()
                            for c in contracts
                        )
                        if has_dependents:
                            logger.warning(
                                f"Agent {name} failed, dependent agents may fail"
                            )
        
        finally:
            # Cleanup workspaces
            for workspace in self.workspaces.values():
                try:
                    await workspace.cleanup()
                except Exception as e:
                    logger.warning(f"Cleanup error: {e}")
        
        duration = (datetime.now() - start_time).total_seconds()
        
        # Determine overall success
        success = all(
            r.status == AgentStatus.COMPLETED 
            for r in self.results.values()
        )
        
        return OrchestratorResult(
            success=success,
            agents=self.results,
            total_duration_seconds=duration,
            execution_order=execution_order,
            signals=all_signals,
            errors=[
                r.error for r in self.results.values() 
                if r.error
            ],
        )
    
    async def _run_agent(self, agent_name: str) -> AgentResult:
        """Run a single agent to completion."""
        state = self.agent_states[agent_name]
        contract = state.contract
        start_time = datetime.now()
        
        logger.info(f"Starting agent: {agent_name}")
        
        # Wait for dependencies
        for dep_signal in contract.get_dependency_signals():
            logger.info(f"{agent_name} waiting for {dep_signal}")
            signal = await self.broker.wait_for(
                dep_signal, 
                timeout=self.agent_timeout
            )
            if not signal:
                return AgentResult(
                    agent_name=agent_name,
                    status=AgentStatus.BLOCKED,
                    signals=[],
                    files_modified={},
                    files_created={},
                    verification_passed=False,
                    error=f"Timeout waiting for {dep_signal}",
                )
        
        # Create isolated workspace
        signal_dir = Path("/tmp/agent_signals") / agent_name
        signal_dir.mkdir(parents=True, exist_ok=True)
        
        workspace = await self.isolator.create_workspace(contract, signal_dir)
        self.workspaces[agent_name] = workspace
        
        # Create conversation
        conversation = await self.client.create_conversation(
            contract=contract,
            goal=contract.goal,
        )
        
        # Register tool handlers
        conversation.set_tool_handler(
            "read_file", 
            self._make_read_handler(workspace, contract)
        )
        conversation.set_tool_handler(
            "write_file",
            self._make_write_handler(workspace, contract)
        )
        conversation.set_tool_handler(
            "execute",
            self._make_execute_handler(workspace)
        )
        conversation.set_tool_handler(
            "list_files",
            self._make_list_handler(workspace, contract)
        )
        conversation.set_tool_handler(
            "signal",
            self._make_signal_handler(agent_name)
        )
        
        # Run agent loop
        files_modified = {}
        files_created = {}
        signals = []
        final_response = None
        
        try:
            # Initial message
            initial_msg = f"""
Your goal: {contract.goal}

Your workspace contains files from: {', '.join(contract.scope)}

Begin execution. Follow the protocol header format.
"""
            
            for attempt in range(state.max_restarts + 1):
                response = await asyncio.wait_for(
                    conversation.send(initial_msg if attempt == 0 else "Continue."),
                    timeout=self.agent_timeout
                )
                
                final_response = response
                signals.extend(response.signals)
                
                # Emit signals to broker
                for signal in response.signals:
                    await self.broker.emit(signal)
                
                # Track files
                for path in response.files_created:
                    content = await self._read_workspace_file(workspace, path)
                    if content:
                        files_created[path] = content
                
                for path in response.files_modified:
                    content = await self._read_workspace_file(workspace, path)
                    if content:
                        files_modified[path] = content
                
                # Check completion
                if response.is_complete:
                    state.status = AgentStatus.COMPLETED
                    break
                elif response.is_blocked:
                    if state.can_restart():
                        state.restart_count += 1
                        logger.info(
                            f"{agent_name} blocked, restarting "
                            f"({state.restart_count}/{state.max_restarts})"
                        )
                        initial_msg = f"Previous attempt blocked: {response.block_reason}. Try different approach."
                        continue
                    else:
                        state.status = AgentStatus.BLOCKED
                        break
                elif response.trajectory == Trajectory.ESCAPING:
                    if state.can_restart():
                        state.restart_count += 1
                        initial_msg = "You were escaping scope. Reset and try again."
                        continue
                    else:
                        state.status = AgentStatus.FAILED
                        break
            
            # Sync files back
            synced = await self.isolator.sync_back(workspace)
            logger.info(f"{agent_name} synced {len(synced)} files")
            
            # Verify outputs
            verification_passed = await self._verify_contract(
                contract, workspace
            )
            
            duration = (datetime.now() - start_time).total_seconds()
            
            return AgentResult(
                agent_name=agent_name,
                status=state.status,
                signals=signals,
                files_modified=files_modified,
                files_created=files_created,
                verification_passed=verification_passed,
                duration_seconds=duration,
                restart_count=state.restart_count,
                final_response=final_response,
            )
            
        except asyncio.TimeoutError:
            return AgentResult(
                agent_name=agent_name,
                status=AgentStatus.FAILED,
                signals=signals,
                files_modified=files_modified,
                files_created=files_created,
                verification_passed=False,
                error="Agent timed out",
                duration_seconds=self.agent_timeout,
                restart_count=state.restart_count,
            )
        except Exception as e:
            logger.exception(f"Agent {agent_name} failed")
            return AgentResult(
                agent_name=agent_name,
                status=AgentStatus.FAILED,
                signals=signals,
                files_modified=files_modified,
                files_created=files_created,
                verification_passed=False,
                error=str(e),
                restart_count=state.restart_count,
            )
    
    def _make_read_handler(
        self, 
        workspace: IsolatedWorkspace, 
        contract: Contract
    ) -> Callable:
        """Create a read_file tool handler with scope enforcement."""
        async def handler(args: dict) -> str:
            path = args.get("path", "")
            
            if not contract.path_allowed(path):
                raise PermissionError(f"Path outside scope: {path}")
            
            full_path = workspace.workspace_path / path
            if not full_path.exists():
                raise FileNotFoundError(f"File not found: {path}")
            
            workspace.files_read.append(path)
            return full_path.read_text()
        
        return handler
    
    def _make_write_handler(
        self,
        workspace: IsolatedWorkspace,
        contract: Contract
    ) -> Callable:
        """Create a write_file tool handler with scope enforcement."""
        async def handler(args: dict) -> str:
            path = args.get("path", "")
            content = args.get("content", "")
            
            if not contract.path_allowed(path):
                raise PermissionError(f"Path outside scope: {path}")
            
            full_path = workspace.workspace_path / path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content)
            
            workspace.files_written.append(path)
            return f"Written {len(content)} bytes to {path}"
        
        return handler
    
    def _make_execute_handler(
        self,
        workspace: IsolatedWorkspace
    ) -> Callable:
        """Create an execute tool handler."""
        async def handler(args: dict) -> str:
            command = args.get("command", "")
            
            returncode, stdout, stderr = await self.isolator.execute_in_workspace(
                workspace, command, timeout=60
            )
            
            result = f"Exit code: {returncode}\n"
            if stdout:
                result += f"stdout:\n{stdout}\n"
            if stderr:
                result += f"stderr:\n{stderr}\n"
            
            return result
        
        return handler
    
    def _make_list_handler(
        self,
        workspace: IsolatedWorkspace,
        contract: Contract
    ) -> Callable:
        """Create a list_files tool handler."""
        async def handler(args: dict) -> str:
            path = args.get("path", ".")
            
            if not contract.path_allowed(path):
                raise PermissionError(f"Path outside scope: {path}")
            
            full_path = workspace.workspace_path / path
            if not full_path.is_dir():
                raise NotADirectoryError(f"Not a directory: {path}")
            
            files = []
            for item in full_path.iterdir():
                rel = item.relative_to(workspace.workspace_path)
                prefix = "d" if item.is_dir() else "f"
                files.append(f"{prefix} {rel}")
            
            return "\n".join(sorted(files))
        
        return handler
    
    def _make_signal_handler(self, agent_name: str) -> Callable:
        """Create a signal tool handler."""
        async def handler(args: dict) -> str:
            signal_type = SignalType(args.get("type", "READY"))
            payload = args.get("payload")
            
            signal = Signal(
                type=signal_type,
                agent=agent_name,
                payload=payload,
            )
            
            await self.broker.emit(signal)
            return f"Emitted {signal}"
        
        return handler
    
    async def _read_workspace_file(
        self, 
        workspace: IsolatedWorkspace, 
        path: str
    ) -> Optional[str]:
        """Read a file from workspace, returning None if not found."""
        full_path = workspace.workspace_path / path
        if full_path.exists():
            return full_path.read_text()
        return None
    
    async def _verify_contract(
        self,
        contract: Contract,
        workspace: IsolatedWorkspace,
    ) -> bool:
        """Run contract verification commands."""
        if not contract.verify:
            return True
        
        all_passed = True
        for cmd in contract.verify:
            returncode, _, _ = await self.isolator.execute_in_workspace(
                workspace, cmd, timeout=120
            )
            if returncode != 0:
                logger.warning(f"Verification failed: {cmd}")
                all_passed = False
        
        return all_passed


async def run_orchestration(
    contracts_source: str,
    repo_root: Path,
    goals: Optional[dict[str, str]] = None,
    **kwargs
) -> OrchestratorResult:
    """
    Convenience function to run orchestration.
    
    Args:
        contracts_source: Markdown or YAML with contract definitions
        repo_root: Path to repository
        goals: Per-agent goals
        **kwargs: Additional Orchestrator arguments
        
    Returns:
        OrchestratorResult
    """
    from .parser import parse_contracts
    
    contracts = parse_contracts(contracts_source)
    orchestrator = Orchestrator(repo_root=repo_root, **kwargs)
    
    return await orchestrator.run(contracts, goals)
