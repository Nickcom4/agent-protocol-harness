"""
Agent Harness MCP Server (v2)

Redesigned to address critical gaps:
1. Session persistence - survives context exhaustion
2. Auto-generated verification plans with user review
3. Smart error reconciliation with auto-fixes
4. Full-power sub-agents with all Claude capabilities
5. Git branching with checkpoint commits

Usage with Claude Code CLI:
  claude mcp add agent-harness "agent-harness-mcp"
"""

import asyncio
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional
import logging

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent, Resource
except ImportError:
    raise ImportError("MCP SDK required. Run: pip install mcp")

from .models import Contract, ExecutionPlan
from .parser import ContractParser
from .persistence import SessionPersistence, SessionState, ContractPersist, get_resume_prompt
from .verification import VerificationPlanner, VerificationCheck
from .reconciler import ErrorReconciler, ResolutionChain
from .executor import FullPowerExecutor

logger = logging.getLogger(__name__)


class AgentHarnessMCP:
    """
    MCP Server for multi-agent orchestration.
    
    Key features:
    - Persistent state (survives context exhaustion)
    - Verification planning before execution
    - Auto-error reconciliation
    - Full-power sub-agents
    """
    
    def __init__(self, repo_root: Optional[Path] = None):
        self.repo_root = Path(repo_root or os.getcwd()).resolve()
        
        # Core components
        self.persistence = SessionPersistence(self.repo_root)
        self.verifier = VerificationPlanner(self.repo_root)
        self.reconciler = ErrorReconciler(self.repo_root)
        self.executor = FullPowerExecutor(self.repo_root)
        
        # Load or create session
        self.state = self.persistence.load() or SessionState()
        
        # MCP Server
        self.server = Server("agent-harness")
        self._setup_tools()
        self._setup_resources()
    
    def _save(self):
        """Save state after every operation."""
        self.persistence.save(self.state)
    
    def _setup_resources(self):
        """Expose session state as MCP resources."""
        
        @self.server.list_resources()
        async def list_resources():
            resources = []
            
            # Current session status
            resources.append(Resource(
                uri="agent://session/status",
                name="Session Status",
                description="Current orchestration session state",
                mimeType="application/json",
            ))
            
            # Resume context (for new context windows)
            if self.state.resume_context:
                resources.append(Resource(
                    uri="agent://session/resume",
                    name="Resume Context",
                    description="Context for resuming interrupted session",
                    mimeType="text/markdown",
                ))
            
            return resources
        
        @self.server.read_resource()
        async def read_resource(uri: str):
            if uri == "agent://session/status":
                return json.dumps(self._get_status_dict(), indent=2)
            elif uri == "agent://session/resume":
                return get_resume_prompt(self.state)
            return "Unknown resource"
    
    def _setup_tools(self):
        """Register MCP tools."""
        
        @self.server.list_tools()
        async def list_tools():
            return [
                # Session management
                Tool(
                    name="check_session",
                    description="""
                    CALL THIS FIRST in every conversation.
                    Checks if there's an existing session to resume.
                    Returns session state or indicates fresh start.
                    """,
                    inputSchema={"type": "object", "properties": {}}
                ),
                
                # Planning phase
                Tool(
                    name="analyze_and_plan",
                    description="""
                    Analyze a task and create a multi-agent plan.
                    Auto-generates verification plans for each agent.
                    Presents plan AND verification for user review.
                    """,
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "task": {"type": "string", "description": "What to accomplish"},
                            "agents": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string"},
                                        "goal": {"type": "string"},
                                        "scope": {"type": "array", "items": {"type": "string"}},
                                        "produces": {"type": "array", "items": {"type": "string"}},
                                        "depends": {"type": "array", "items": {"type": "string"}},
                                    },
                                    "required": ["name", "goal", "scope"]
                                }
                            }
                        },
                        "required": ["task", "agents"]
                    }
                ),
                
                Tool(
                    name="modify_plan",
                    description="Modify the plan based on user feedback",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "modifications": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "action": {"type": "string", "enum": ["add", "remove", "update"]},
                                        "agent": {"type": "string"},
                                        "changes": {"type": "object"}
                                    }
                                }
                            }
                        },
                        "required": ["modifications"]
                    }
                ),
                
                Tool(
                    name="approve_plan",
                    description="""
                    User approves the plan (both execution AND verification).
                    Creates feature branch and prepares for execution.
                    """,
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "branch_name": {"type": "string", "description": "Optional custom branch"}
                        }
                    }
                ),
                
                # Execution phase
                Tool(
                    name="execute_next_agent",
                    description="""
                    Execute the next pending agent.
                    Runs as FULL Claude Code session with all capabilities.
                    Creates checkpoint commit on completion.
                    """,
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "agent_name": {"type": "string", "description": "Specific agent (or auto-selects next)"}
                        }
                    }
                ),
                
                Tool(
                    name="get_execution_status",
                    description="Get status of current/completed agent executions",
                    inputSchema={"type": "object", "properties": {}}
                ),
                
                # Verification phase
                Tool(
                    name="run_verification",
                    description="""
                    Run automated verification checks for an agent.
                    Auto-attempts to fix failures when possible.
                    """,
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "agent_name": {"type": "string"}
                        },
                        "required": ["agent_name"]
                    }
                ),
                
                Tool(
                    name="confirm_manual_check",
                    description="User confirms/rejects a manual verification check",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "check_id": {"type": "string"},
                            "passed": {"type": "boolean"},
                            "notes": {"type": "string"}
                        },
                        "required": ["check_id", "passed"]
                    }
                ),
                
                # Error handling
                Tool(
                    name="handle_error",
                    description="""
                    Analyze an error and attempt auto-resolution.
                    Installs missing packages, fixes common issues.
                    Escalates to user if can't auto-fix.
                    """,
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "agent_name": {"type": "string"},
                            "error_output": {"type": "string"},
                            "auto_fix": {"type": "boolean", "default": True}
                        },
                        "required": ["agent_name", "error_output"]
                    }
                ),
                
                # Feedback and iteration
                Tool(
                    name="provide_feedback",
                    description="User provides feedback, triggers retry/adjustment",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "agent_name": {"type": "string"},
                            "feedback": {"type": "string"},
                            "action": {"type": "string", "enum": ["retry", "skip", "revert"]}
                        },
                        "required": ["agent_name", "feedback", "action"]
                    }
                ),
                
                # Finalization
                Tool(
                    name="finalize_session",
                    description="Complete session: merge, keep branch, or discard",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "action": {"type": "string", "enum": ["merge", "keep", "discard"]},
                            "commit_message": {"type": "string"}
                        },
                        "required": ["action"]
                    }
                ),
            ]
        
        @self.server.call_tool()
        async def call_tool(name: str, arguments: dict):
            try:
                handler = getattr(self, f"_tool_{name}", None)
                if not handler:
                    return [TextContent(type="text", text=f"Unknown tool: {name}")]
                
                result = await handler(arguments)
                self._save()  # Persist after every tool call
                return [TextContent(type="text", text=result)]
            except Exception as e:
                logger.exception(f"Tool {name} failed")
                return [TextContent(type="text", text=f"Error: {str(e)}")]
    
    # ==================== Tool Implementations ====================
    
    async def _tool_check_session(self, args: dict) -> str:
        """Check for existing session or start fresh."""
        if self.state.session_id and self.state.phase != "not_started":
            return json.dumps({
                "has_session": True,
                "session_id": self.state.session_id,
                "phase": self.state.phase,
                "goal": self.state.original_goal,
                "resume_context": self.state.resume_context,
                "next_action": self.state.next_action,
                "message": "Existing session found. Review resume_context and continue."
            }, indent=2)
        
        return json.dumps({
            "has_session": False,
            "message": "No existing session. Ready for new task."
        }, indent=2)
    
    async def _tool_analyze_and_plan(self, args: dict) -> str:
        """Create plan with auto-generated verification."""
        task = args["task"]
        agents_data = args["agents"]
        
        # Create session if needed
        if not self.state.session_id:
            self.state = self.persistence.create_new(task)
        
        self.state.original_goal = task
        self.state.phase = "planning"
        
        # Build contracts
        contracts = []
        verification_plans = []
        
        for a in agents_data:
            contract = Contract(
                name=a["name"],
                goal=a["goal"],
                scope=a.get("scope", []),
                cannot=a.get("cannot", []),
                depends=a.get("depends", []),
                produces=a.get("produces", []),
                verify=a.get("verify", []),
            )
            contracts.append(contract)
            
            # Auto-generate verification plan
            vplan = self.verifier.generate_plan(contract)
            verification_plans.append(vplan)
            
            # Store as persistable contract
            self.state.proposed_contracts.append(ContractPersist(
                name=contract.name,
                goal=contract.goal,
                scope=contract.scope,
                cannot=contract.cannot,
                depends=contract.depends,
                expects=contract.expects,
                produces=contract.produces,
                verify=contract.verify,
                verification_plan=[
                    {"type": c.type, "description": c.description, "command": c.command}
                    for c in vplan.automated_checks + vplan.manual_checks
                ],
            ))
        
        # Validate
        errors = ContractParser.validate_contracts(contracts)
        if errors:
            return json.dumps({
                "status": "invalid",
                "errors": errors,
            }, indent=2)
        
        # Build execution plan
        plan = ExecutionPlan.from_contracts(contracts)
        self.state.pending_agents = list(plan.sequential_order)
        
        # Format for user review
        output = {
            "status": "plan_ready",
            "task": task,
            "execution_order": plan.sequential_order,
            "agents": [],
        }
        
        for contract, vplan in zip(contracts, verification_plans):
            output["agents"].append({
                "name": contract.name,
                "goal": contract.goal,
                "scope": contract.scope,
                "depends": contract.depends,
                "produces": contract.produces,
                "verification": {
                    "automated": [
                        {"description": c.description, "command": c.command}
                        for c in vplan.automated_checks
                    ],
                    "manual": [
                        {"description": c.description, "prompt": c.prompt}
                        for c in vplan.manual_checks
                    ],
                }
            })
        
        output["message"] = (
            "Plan created with verification. "
            "Review and call approve_plan when ready, or modify_plan to adjust."
        )
        
        self.state.next_action = "Review plan and verification, then approve or modify"
        
        return json.dumps(output, indent=2)
    
    async def _tool_approve_plan(self, args: dict) -> str:
        """Approve plan and create branch."""
        if not self.state.proposed_contracts:
            return json.dumps({"status": "error", "message": "No plan to approve"})
        
        # Get current branch
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=self.repo_root,
            capture_output=True,
            text=True
        )
        self.state.original_branch = result.stdout.strip() or "main"
        
        # Create session branch
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        branch = args.get("branch_name") or f"ai/session-{timestamp}"
        self.state.session_branch = branch
        
        subprocess.run(
            ["git", "checkout", "-b", branch],
            cwd=self.repo_root,
            capture_output=True
        )
        
        self.state.execution_plan_approved = True
        self.state.verification_plan_approved = True
        self.state.phase = "executing"
        self.state.next_action = "Call execute_next_agent to start"
        
        return json.dumps({
            "status": "approved",
            "branch": branch,
            "agents_to_execute": self.state.pending_agents,
            "message": f"Created branch '{branch}'. Call execute_next_agent to begin."
        }, indent=2)
    
    async def _tool_execute_next_agent(self, args: dict) -> str:
        """Execute next agent with full Claude capabilities."""
        if not self.state.pending_agents:
            return json.dumps({
                "status": "complete",
                "message": "All agents executed. Run verification or finalize."
            })
        
        # Get next agent
        agent_name = args.get("agent_name") or self.state.pending_agents[0]
        
        if agent_name not in self.state.pending_agents:
            return json.dumps({
                "status": "error",
                "message": f"Agent '{agent_name}' not in pending list"
            })
        
        # Find contract
        contract_data = next(
            (c for c in self.state.proposed_contracts if c.name == agent_name),
            None
        )
        if not contract_data:
            return json.dumps({"status": "error", "message": "Contract not found"})
        
        # Convert to Contract
        contract = Contract(
            name=contract_data.name,
            goal=contract_data.goal,
            scope=contract_data.scope,
            cannot=contract_data.cannot,
            depends=contract_data.depends,
            produces=contract_data.produces,
            verify=contract_data.verify,
        )
        
        self.state.current_agent = agent_name
        
        # Execute with full power
        output_buffer = []
        def on_output(line):
            output_buffer.append(line)
        
        execution = await self.executor.execute_agent(
            contract,
            on_output=on_output,
            timeout=600,
        )
        
        # Get result
        result = await self.executor.get_agent_result(agent_name)
        
        # Update state
        self.state.pending_agents.remove(agent_name)
        
        if result and result.get("status") == "complete":
            self.state.completed_agents.append(agent_name)
            
            # Sync changes back
            synced = await self.executor.sync_workspace_back(agent_name)
            
            # Checkpoint commit
            subprocess.run(["git", "add", "-A"], cwd=self.repo_root)
            commit_msg = f"checkpoint: {agent_name} complete"
            subprocess.run(
                ["git", "commit", "-m", commit_msg],
                cwd=self.repo_root,
                capture_output=True
            )
            
            # Get commit hash
            hash_result = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=self.repo_root,
                capture_output=True,
                text=True
            )
            commit_hash = hash_result.stdout.strip()
            
            self.state.commits.append({
                "hash": commit_hash,
                "message": commit_msg,
                "agent": agent_name,
            })
            
            return json.dumps({
                "status": "success",
                "agent": agent_name,
                "files_synced": list(synced.keys()),
                "commit": commit_hash,
                "remaining_agents": self.state.pending_agents,
                "next": "Run verification or execute_next_agent",
            }, indent=2)
        
        elif result and result.get("status") == "blocked":
            self.state.failed_agents.append(agent_name)
            self.state.errors_encountered.append({
                "agent": agent_name,
                "error": result.get("reason", "Unknown"),
                "need": result.get("need"),
            })
            
            return json.dumps({
                "status": "blocked",
                "agent": agent_name,
                "reason": result.get("reason"),
                "need": result.get("need"),
                "next": "Use handle_error or provide_feedback",
            }, indent=2)
        
        else:
            self.state.failed_agents.append(agent_name)
            return json.dumps({
                "status": "failed",
                "agent": agent_name,
                "output": execution.output[-2000:] if execution.output else "No output",
                "next": "Use handle_error to analyze",
            }, indent=2)
    
    async def _tool_handle_error(self, args: dict) -> str:
        """Analyze and auto-fix errors."""
        agent_name = args["agent_name"]
        error_output = args["error_output"]
        auto_fix = args.get("auto_fix", True)
        
        # Analyze
        analysis = self.reconciler.analyze(error_output)
        
        result = {
            "category": analysis.category.value,
            "root_cause": analysis.root_cause,
            "can_auto_fix": analysis.can_auto_resolve,
        }
        
        if analysis.can_auto_resolve and auto_fix:
            # Attempt resolution
            chain = ResolutionChain(self.reconciler)
            resolved, message = await chain.resolve_with_escalation(error_output)
            
            result["auto_fix_attempted"] = True
            result["fixed"] = resolved
            result["message"] = message
            
            if resolved:
                self.state.auto_resolutions.append({
                    "agent": agent_name,
                    "error": analysis.root_cause,
                    "fix": message,
                })
                result["next"] = "Retry the agent with execute_next_agent"
            else:
                result["next"] = "Provide feedback to guide retry"
        else:
            result["auto_fix_attempted"] = False
            result["suggested_fix"] = analysis.suggested_fix
            result["next"] = "Apply suggested fix or provide feedback"
        
        self.state.errors_encountered.append({
            "agent": agent_name,
            "error": analysis.root_cause,
            "resolution": result.get("message"),
        })
        
        return json.dumps(result, indent=2)
    
    async def _tool_run_verification(self, args: dict) -> str:
        """Run verification checks for an agent."""
        agent_name = args["agent_name"]
        
        # Find verification plan
        contract_data = next(
            (c for c in self.state.proposed_contracts if c.name == agent_name),
            None
        )
        if not contract_data:
            return json.dumps({"status": "error", "message": "Contract not found"})
        
        results = []
        all_passed = True
        
        for check in contract_data.verification_plan:
            if check.get("command"):
                # Run automated check
                proc = subprocess.run(
                    check["command"],
                    shell=True,
                    cwd=self.repo_root,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                
                passed = proc.returncode == 0
                all_passed = all_passed and passed
                
                results.append({
                    "type": "automated",
                    "description": check["description"],
                    "command": check["command"],
                    "passed": passed,
                    "output": (proc.stdout + proc.stderr)[:500],
                })
                
                # Auto-fix if failed
                if not passed:
                    analysis = self.reconciler.analyze(proc.stdout + proc.stderr)
                    if analysis.can_auto_resolve:
                        chain = ResolutionChain(self.reconciler)
                        resolved, _ = await chain.resolve_with_escalation(
                            proc.stdout + proc.stderr
                        )
                        results[-1]["auto_fix_attempted"] = True
                        results[-1]["auto_fixed"] = resolved
            else:
                # Manual check - needs user confirmation
                results.append({
                    "type": "manual",
                    "description": check["description"],
                    "passed": None,
                    "awaiting_user": True,
                    "check_id": f"{agent_name}:{check['description'][:20]}",
                })
                all_passed = False
        
        self.state.verification_results.extend(results)
        self.state.verification_started = True
        
        manual_pending = [r for r in results if r.get("awaiting_user")]
        
        return json.dumps({
            "agent": agent_name,
            "all_automated_passed": all_passed if not manual_pending else "pending manual",
            "results": results,
            "manual_checks_pending": len(manual_pending),
            "next": "Use confirm_manual_check for pending items" if manual_pending else (
                "Ready to finalize" if all_passed else "Fix failures and re-verify"
            ),
        }, indent=2)
    
    async def _tool_confirm_manual_check(self, args: dict) -> str:
        """User confirms a manual verification check."""
        check_id = args["check_id"]
        passed = args["passed"]
        notes = args.get("notes", "")
        
        # Find and update check
        for result in self.state.verification_results:
            if result.get("check_id") == check_id:
                result["passed"] = passed
                result["awaiting_user"] = False
                result["notes"] = notes
                break
        
        # Check if all manual checks done
        pending = [r for r in self.state.verification_results if r.get("awaiting_user")]
        
        return json.dumps({
            "status": "confirmed",
            "check_id": check_id,
            "passed": passed,
            "remaining_manual_checks": len(pending),
        }, indent=2)
    
    async def _tool_provide_feedback(self, args: dict) -> str:
        """Handle user feedback."""
        agent_name = args["agent_name"]
        feedback = args["feedback"]
        action = args["action"]
        
        self.state.feedback_history.append({
            "iteration": self.state.iteration,
            "agent": agent_name,
            "feedback": feedback,
            "action": action,
        })
        self.state.iteration += 1
        
        if action == "retry":
            # Update contract goal with feedback
            for c in self.state.proposed_contracts:
                if c.name == agent_name:
                    c.goal = f"{c.goal}\n\nFEEDBACK: {feedback}"
                    break
            
            # Add back to pending
            if agent_name in self.state.failed_agents:
                self.state.failed_agents.remove(agent_name)
            if agent_name in self.state.completed_agents:
                self.state.completed_agents.remove(agent_name)
            if agent_name not in self.state.pending_agents:
                self.state.pending_agents.insert(0, agent_name)
            
            return json.dumps({
                "status": "ready_to_retry",
                "agent": agent_name,
                "next": "Call execute_next_agent",
            }, indent=2)
        
        elif action == "skip":
            if agent_name in self.state.pending_agents:
                self.state.pending_agents.remove(agent_name)
            
            return json.dumps({
                "status": "skipped",
                "agent": agent_name,
                "remaining": self.state.pending_agents,
            }, indent=2)
        
        elif action == "revert":
            # Git revert to before this agent
            agent_commit = next(
                (c for c in reversed(self.state.commits) if c["agent"] == agent_name),
                None
            )
            if agent_commit:
                subprocess.run(
                    ["git", "revert", "--no-commit", agent_commit["hash"]],
                    cwd=self.repo_root,
                    capture_output=True,
                )
            
            return json.dumps({
                "status": "reverted",
                "agent": agent_name,
            }, indent=2)
        
        return json.dumps({"status": "error", "message": f"Unknown action: {action}"})
    
    async def _tool_finalize_session(self, args: dict) -> str:
        """Complete the session."""
        action = args["action"]
        original_branch = self.state.original_branch
        session_branch = self.state.session_branch
        
        if action == "merge":
            commit_msg = args.get("commit_message") or f"feat: {self.state.original_goal}"
            
            subprocess.run(
                ["git", "checkout", original_branch],
                cwd=self.repo_root,
                capture_output=True,
            )
            subprocess.run(
                ["git", "merge", "--squash", session_branch],
                cwd=self.repo_root,
                capture_output=True,
            )
            subprocess.run(
                ["git", "commit", "-m", commit_msg],
                cwd=self.repo_root,
                capture_output=True,
            )
            subprocess.run(
                ["git", "branch", "-D", session_branch],
                cwd=self.repo_root,
                capture_output=True,
            )
            
            # Archive session
            self.state.phase = "finalized"
            self.persistence.archive(self.state)
            self.state = SessionState()
            
            return json.dumps({
                "status": "merged",
                "message": f"Merged to {original_branch}",
            }, indent=2)
        
        elif action == "keep":
            subprocess.run(
                ["git", "checkout", original_branch],
                cwd=self.repo_root,
                capture_output=True,
            )
            
            self.state.phase = "finalized"
            self.persistence.archive(self.state)
            self.state = SessionState()
            
            return json.dumps({
                "status": "kept",
                "branch": session_branch,
                "message": "Branch kept for manual review",
            }, indent=2)
        
        elif action == "discard":
            subprocess.run(
                ["git", "checkout", original_branch],
                cwd=self.repo_root,
                capture_output=True,
            )
            if session_branch:
                subprocess.run(
                    ["git", "branch", "-D", session_branch],
                    cwd=self.repo_root,
                    capture_output=True,
                )
            
            self.state = SessionState()
            self.persistence.save(self.state)
            
            return json.dumps({
                "status": "discarded",
                "message": "All changes removed",
            }, indent=2)
        
        return json.dumps({"status": "error", "message": f"Unknown action: {action}"})
    
    async def _tool_modify_plan(self, args: dict) -> str:
        """Modify the plan based on user feedback."""
        for mod in args["modifications"]:
            action = mod["action"]
            agent = mod["agent"]
            changes = mod.get("changes", {})
            
            if action == "remove":
                self.state.proposed_contracts = [
                    c for c in self.state.proposed_contracts if c.name != agent
                ]
                if agent in self.state.pending_agents:
                    self.state.pending_agents.remove(agent)
            
            elif action == "update":
                for c in self.state.proposed_contracts:
                    if c.name == agent:
                        for key, value in changes.items():
                            if hasattr(c, key):
                                setattr(c, key, value)
                        break
            
            elif action == "add":
                self.state.proposed_contracts.append(ContractPersist(
                    name=agent,
                    goal=changes.get("goal", ""),
                    scope=changes.get("scope", []),
                    cannot=changes.get("cannot", []),
                    depends=changes.get("depends", []),
                    expects=changes.get("expects", []),
                    produces=changes.get("produces", []),
                    verify=changes.get("verify", []),
                    verification_plan=[],
                ))
                self.state.pending_agents.append(agent)
        
        return json.dumps({
            "status": "modified",
            "agents": [c.name for c in self.state.proposed_contracts],
            "pending": self.state.pending_agents,
        }, indent=2)
    
    async def _tool_get_execution_status(self, args: dict) -> str:
        """Get current execution status."""
        return json.dumps(self._get_status_dict(), indent=2)
    
    def _get_status_dict(self) -> dict:
        """Build status dictionary."""
        return {
            "session_id": self.state.session_id,
            "phase": self.state.phase,
            "goal": self.state.original_goal,
            "branch": self.state.session_branch,
            "iteration": self.state.iteration,
            "agents": {
                "completed": self.state.completed_agents,
                "failed": self.state.failed_agents,
                "pending": self.state.pending_agents,
                "current": self.state.current_agent,
            },
            "commits": self.state.commits[-5:],
            "errors": len(self.state.errors_encountered),
            "auto_fixes": len(self.state.auto_resolutions),
            "verification_complete": self.state.verification_started and not any(
                r.get("awaiting_user") for r in self.state.verification_results
            ),
            "next_action": self.state.next_action,
        }
    
    async def run(self):
        """Run the MCP server."""
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                self.server.create_initialization_options()
            )


def main():
    """Entry point."""
    import sys
    repo_root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    
    server = AgentHarnessMCP(repo_root)
    asyncio.run(server.run())


if __name__ == "__main__":
    main()
