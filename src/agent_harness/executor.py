"""
Full-Powered Agent Executor

The critical insight: sub-agents should NOT be crippled Claude instances
running through limited tool handlers. They should be FULL Claude Code
sessions with inherited permissions.

This module:
1. Spawns sub-agents as real Claude Code CLI processes
2. Passes full tool/MCP permissions to sub-agents
3. Provides contract context without limiting capabilities
4. Allows agents to install packages, use web search, etc.
"""

import asyncio
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable, AsyncIterator
import shutil


@dataclass
class AgentExecution:
    """Tracks a running agent."""
    name: str
    process: Optional[asyncio.subprocess.Process] = None
    workspace: Optional[Path] = None
    log_file: Optional[Path] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    exit_code: Optional[int] = None
    output: str = ""


class FullPowerExecutor:
    """
    Executes agents as full Claude Code sessions.
    
    ⚠️  DESIGNED FOR DEV CONTAINERS ONLY ⚠️
    
    This executor spawns sub-agents with --dangerously-skip-permissions,
    meaning they have FULL autonomous access to:
    - File system (create, modify, delete)
    - Network (web search, API calls)
    - Package managers (npm, pip, apt)
    - Shell commands
    - Git operations
    
    ONLY use this in isolated dev container environments where:
    - DOTFILES_CONTAINER=true or /workspaces/ path detected
    - Repository is a working copy (not production)
    - Network is sandboxed or acceptable for autonomous access
    
    Key principle: Agents get ALL the capabilities of Claude Code,
    including:
    - Web search
    - MCP tools (GitHub, Notion, etc.)
    - Package installation (npm, pip, apt)
    - File system access (within workspace)
    - Subprocess execution
    
    The contract provides CONTEXT and GOALS, not RESTRICTIONS.
    Isolation is achieved through workspace separation, not capability removal.
    """
    
    def __init__(
        self,
        repo_root: Path,
        work_dir: Optional[Path] = None,
        claude_path: str = "claude",  # Path to claude CLI
        inherit_env: bool = True,
        inherit_mcp: bool = True,
        require_container: bool = True,  # Safety check
    ):
        self.repo_root = Path(repo_root).resolve()
        self.work_dir = Path(work_dir or tempfile.mkdtemp(prefix="agent_exec_"))
        self.claude_path = claude_path
        self.inherit_env = inherit_env
        self.inherit_mcp = inherit_mcp
        
        # Safety check: only run in dev containers
        if require_container and not self._is_dev_container():
            raise RuntimeError(
                "FullPowerExecutor requires a dev container environment.\n"
                "Detected: not in container (no DOTFILES_CONTAINER or /workspaces/).\n"
                "\n"
                "This executor spawns sub-agents with --dangerously-skip-permissions,\n"
                "which grants full autonomous access. This is only safe in isolated\n"
                "dev container environments.\n"
                "\n"
                "If you're sure you want to proceed, set require_container=False."
            )
        
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.executions: dict[str, AgentExecution] = {}
    
    def _is_dev_container(self) -> bool:
        """Check if running in a dev container."""
        # Check environment variable
        if os.environ.get("DOTFILES_CONTAINER") == "true":
            return True
        
        # Check for /workspaces/ path (GitHub Codespaces, VS Code Dev Containers)
        if self.repo_root.as_posix().startswith("/workspaces/"):
            return True
        
        # Check for devcontainer.json in repo
        if (self.repo_root / ".devcontainer" / "devcontainer.json").exists():
            return True
        if (self.repo_root / ".devcontainer.json").exists():
            return True
        
        # Check for common container indicators
        if Path("/.dockerenv").exists():
            return True
        
        return False
    
    async def execute_agent(
        self,
        contract: "Contract",
        on_output: Optional[Callable[[str], None]] = None,
        timeout: float = 600,
    ) -> AgentExecution:
        """
        Execute an agent as a full Claude Code session.
        
        The agent runs in its own workspace with full capabilities.
        Contract scope is advisory (in the prompt), not enforced.
        """
        # Create workspace
        workspace = self.work_dir / f"agent_{contract.name}_{os.getpid()}"
        workspace.mkdir(parents=True, exist_ok=True)
        
        # Copy repo to workspace
        await self._copy_repo_to_workspace(workspace)
        
        # Create log file
        log_file = workspace / ".agent_log.txt"
        
        # Build the agent prompt
        prompt = self._build_agent_prompt(contract)
        
        # Write prompt to file (for claude --prompt-file)
        prompt_file = workspace / ".agent_prompt.md"
        prompt_file.write_text(prompt)
        
        # Build environment
        env = self._build_environment(contract, workspace)
        
        # Build command
        cmd = self._build_command(contract, workspace, prompt_file)
        
        execution = AgentExecution(
            name=contract.name,
            workspace=workspace,
            log_file=log_file,
            started_at=datetime.now(),
        )
        self.executions[contract.name] = execution
        
        # Run Claude Code
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=workspace,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            execution.process = process
            
            # Stream output
            output_lines = []
            while True:
                try:
                    line = await asyncio.wait_for(
                        process.stdout.readline(),
                        timeout=timeout
                    )
                    if not line:
                        break
                    
                    decoded = line.decode('utf-8', errors='replace')
                    output_lines.append(decoded)
                    
                    # Callback for real-time output
                    if on_output:
                        on_output(decoded)
                    
                    # Write to log
                    with open(log_file, 'a') as f:
                        f.write(decoded)
                        
                except asyncio.TimeoutError:
                    process.kill()
                    output_lines.append("\n[TIMEOUT - Agent killed]\n")
                    break
            
            await process.wait()
            
            execution.exit_code = process.returncode
            execution.output = "".join(output_lines)
            execution.finished_at = datetime.now()
            
        except Exception as e:
            execution.output = f"Execution error: {str(e)}"
            execution.exit_code = -1
            execution.finished_at = datetime.now()
        
        return execution
    
    def _build_agent_prompt(self, contract: "Contract") -> str:
        """
        Build the prompt that gives the agent its mission.
        
        This is CONTEXT, not RESTRICTION. The agent has full powers
        but is told what to focus on.
        """
        return f"""
# Agent Mission: {contract.name}

## Your Goal
{contract.goal}

## Context

You are an autonomous agent working on a specific part of a larger task.
You have FULL CAPABILITIES - you can:
- Install any packages you need (npm, pip, apt-get, etc.)
- Search the web for documentation or solutions
- Use all available MCP tools
- Create, modify, delete any files
- Run any commands

## Your Focus Area

You should primarily work in these areas:
{chr(10).join(f"- {s}" for s in contract.scope)}

Other agents are handling:
{chr(10).join(f"- {c}" for c in contract.cannot) if contract.cannot else "- (no other agents specified)"}

## What You're Expected to Produce
{chr(10).join(f"- {p}" for p in contract.produces) if contract.produces else "- Complete the goal"}

## How to Verify Success
{chr(10).join(f"- {v}" for v in contract.verify) if contract.verify else "- Ensure your changes work correctly"}

## Inputs Available
{chr(10).join(f"- {e}" for e in contract.expects) if contract.expects else "- Standard codebase"}

## Instructions

1. Analyze what needs to be done
2. Install any dependencies you need
3. Implement the solution
4. Test your implementation
5. When complete, create a file `.agent_complete.json` with:
   ```json
   {{
     "status": "complete",
     "files_created": ["list", "of", "files"],
     "files_modified": ["list", "of", "files"],
     "verification": {{
       "commands_run": ["npm test"],
       "results": "all passed"
     }},
     "notes": "any important notes for integration"
   }}
   ```

If you get stuck or need user input:
- Create `.agent_blocked.json` with the reason and what you need

Work autonomously. Make decisions. Get it done.
"""
    
    def _build_environment(self, contract: "Contract", workspace: Path) -> dict:
        """Build environment for agent process."""
        env = os.environ.copy() if self.inherit_env else {}
        
        # Agent-specific vars
        env.update({
            "AGENT_NAME": contract.name,
            "AGENT_WORKSPACE": str(workspace),
            "AGENT_GOAL": contract.goal,
            "DOTFILES_CONTAINER": "true",  # Signal autonomous mode
        })
        
        # Ensure PATH includes common tools
        if "PATH" in env:
            env["PATH"] = f"/usr/local/bin:/usr/bin:/bin:{env['PATH']}"
        
        return env
    
    def _build_command(
        self, 
        contract: "Contract", 
        workspace: Path,
        prompt_file: Path,
    ) -> list[str]:
        """
        Build the claude CLI command.
        
        IMPORTANT: This spawns sub-agents with full autonomous permissions.
        Only use in isolated dev containers where this is safe.
        """
        cmd = [self.claude_path]
        
        # Use prompt file
        cmd.extend(["--prompt-file", str(prompt_file)])
        
        # CRITICAL: Skip permission prompts for autonomous execution
        # This is safe because we're in an isolated dev container
        cmd.append("--dangerously-skip-permissions")
        
        # Continue without asking (autonomous mode)
        cmd.extend(["--yes"])
        
        # Inherit MCP servers if configured
        if self.inherit_mcp:
            mcp_config = os.environ.get("CLAUDE_MCP_SERVERS")
            if mcp_config:
                cmd.extend(["--mcp-config", mcp_config])
        
        return cmd
    
    async def _copy_repo_to_workspace(self, workspace: Path) -> None:
        """Copy repository to workspace."""
        # Use git clone if it's a git repo (preserves history)
        git_dir = self.repo_root / ".git"
        if git_dir.exists():
            process = await asyncio.create_subprocess_exec(
                "git", "clone", "--local", str(self.repo_root), str(workspace),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await process.wait()
        else:
            # Copy files
            shutil.copytree(
                self.repo_root, 
                workspace, 
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns(
                    'node_modules', '__pycache__', '.git', 'venv', '.env'
                )
            )
    
    async def get_agent_result(self, name: str) -> Optional[dict]:
        """Get the result from an agent's completion file."""
        execution = self.executions.get(name)
        if not execution or not execution.workspace:
            return None
        
        complete_file = execution.workspace / ".agent_complete.json"
        if complete_file.exists():
            return json.loads(complete_file.read_text())
        
        blocked_file = execution.workspace / ".agent_blocked.json"
        if blocked_file.exists():
            return {
                "status": "blocked",
                **json.loads(blocked_file.read_text())
            }
        
        return {"status": "unknown", "output": execution.output[-2000:]}
    
    async def sync_workspace_back(self, name: str) -> dict[str, Path]:
        """Sync agent's workspace changes back to main repo."""
        execution = self.executions.get(name)
        if not execution or not execution.workspace:
            return {}
        
        synced = {}
        
        # If git repo, get diff
        git_dir = execution.workspace / ".git"
        if git_dir.exists():
            # Get list of changed files
            process = await asyncio.create_subprocess_exec(
                "git", "diff", "--name-only", "HEAD",
                cwd=execution.workspace,
                stdout=asyncio.subprocess.PIPE,
            )
            stdout, _ = await process.communicate()
            
            for line in stdout.decode().strip().split('\n'):
                if line:
                    src = execution.workspace / line
                    dst = self.repo_root / line
                    if src.exists():
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src, dst)
                        synced[line] = dst
        else:
            # Manual diff (compare modification times)
            for src in execution.workspace.rglob('*'):
                if src.is_file() and not src.name.startswith('.agent'):
                    rel = src.relative_to(execution.workspace)
                    dst = self.repo_root / rel
                    
                    # Copy if new or modified
                    if not dst.exists() or src.stat().st_mtime > dst.stat().st_mtime:
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src, dst)
                        synced[str(rel)] = dst
        
        return synced
    
    async def cleanup(self, name: Optional[str] = None) -> None:
        """Clean up workspace(s)."""
        if name:
            execution = self.executions.get(name)
            if execution and execution.workspace and execution.workspace.exists():
                shutil.rmtree(execution.workspace)
        else:
            if self.work_dir.exists():
                shutil.rmtree(self.work_dir)


class DelegatingExecutor:
    """
    Alternative: Delegates to Claude API with full tool definitions.
    
    Use this if claude CLI is not available. Makes API calls with
    all tools enabled.
    """
    
    def __init__(
        self,
        repo_root: Path,
        api_key: Optional[str] = None,
        model: str = "claude-sonnet-4-20250514",
    ):
        self.repo_root = Path(repo_root)
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.model = model
    
    async def execute_agent(
        self,
        contract: "Contract",
        available_tools: list[dict],  # Full tool definitions from MCP
        on_message: Optional[Callable[[str], None]] = None,
    ) -> dict:
        """
        Execute agent via API with full tool access.
        
        Args:
            contract: Agent contract
            available_tools: All tools available (from MCP discovery)
            on_message: Callback for messages
        """
        import anthropic
        
        client = anthropic.Anthropic(api_key=self.api_key)
        
        # Build system prompt with full permissions
        system = f"""
You are an autonomous agent with FULL capabilities.

Your mission: {contract.goal}

Focus on: {', '.join(contract.scope)}

You have access to ALL tools. Use whatever you need to accomplish the goal.
Install packages, search the web, create files - do whatever is necessary.

When complete, call the 'signal_complete' tool with your results.
If blocked, call 'signal_blocked' with what you need.
"""
        
        # Add our signal tools to the available tools
        tools = available_tools + [
            {
                "name": "signal_complete",
                "description": "Signal that your work is complete",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "files_created": {"type": "array", "items": {"type": "string"}},
                        "files_modified": {"type": "array", "items": {"type": "string"}},
                        "verification_output": {"type": "string"},
                        "notes": {"type": "string"},
                    }
                }
            },
            {
                "name": "signal_blocked",
                "description": "Signal that you are blocked and need help",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "reason": {"type": "string"},
                        "need": {"type": "string"},
                    },
                    "required": ["reason"]
                }
            }
        ]
        
        messages = [{"role": "user", "content": f"Execute your mission: {contract.goal}"}]
        
        # Agentic loop
        while True:
            response = client.messages.create(
                model=self.model,
                max_tokens=8192,
                system=system,
                tools=tools,
                messages=messages,
            )
            
            # Process response
            assistant_content = []
            result = None
            
            for block in response.content:
                if block.type == "text":
                    if on_message:
                        on_message(block.text)
                    assistant_content.append({"type": "text", "text": block.text})
                
                elif block.type == "tool_use":
                    assistant_content.append({
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    })
                    
                    # Check for completion signals
                    if block.name == "signal_complete":
                        return {"status": "complete", **block.input}
                    elif block.name == "signal_blocked":
                        return {"status": "blocked", **block.input}
            
            messages.append({"role": "assistant", "content": assistant_content})
            
            # Handle tool calls (would need actual tool execution here)
            # This is where you'd integrate with MCP tool handlers
            
            if response.stop_reason == "end_turn":
                break
        
        return {"status": "incomplete", "output": "Agent ended without signaling"}
