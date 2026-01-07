"""
Claude API Client - Wrapper for Claude API with contract injection.

Handles:
- System prompt construction with contract and protocol
- Tool definitions for file operations
- Message streaming and parsing
- Signal extraction from responses
"""

import json
import os
import re
from dataclasses import dataclass
from typing import Optional, AsyncIterator, Callable
from pathlib import Path

from .models import Contract, Signal, SignalType, Trajectory


@dataclass
class AgentResponse:
    """Parsed response from an agent."""
    content: str
    signals: list[Signal]
    trajectory: Trajectory
    files_modified: list[str]
    files_created: list[str]
    verification_results: dict[str, bool]
    is_complete: bool
    is_blocked: bool
    block_reason: Optional[str] = None
    checkpoint: Optional[dict] = None


class ClaudeClient:
    """
    Claude API client with contract-aware system prompts.
    
    Constructs system prompts that include:
    - The agent protocol
    - The specific contract for the agent
    - Available tools based on scope
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "claude-sonnet-4-20250514",
        protocol_path: Optional[Path] = None,
    ):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.model = model
        self.protocol_path = protocol_path
        self._protocol_content: Optional[str] = None
        
        if not self.api_key:
            raise ValueError(
                "API key required. Set ANTHROPIC_API_KEY or pass api_key."
            )
    
    def _get_protocol(self) -> str:
        """Load the agent protocol."""
        if self._protocol_content:
            return self._protocol_content
        
        if self.protocol_path and self.protocol_path.exists():
            self._protocol_content = self.protocol_path.read_text()
        else:
            # Use embedded minimal protocol
            self._protocol_content = self._get_minimal_protocol()
        
        return self._protocol_content
    
    def _get_minimal_protocol(self) -> str:
        """Minimal embedded protocol for when no file is provided."""
        return """
# AGENT PROTOCOL (Minimal)

## HEADER (MANDATORY)
Every response starts with:
```
GOAL:[task]|STATUS:[phase]|[done]/[total]|[next]|CTX:[%]|SPLIT:n
STATE:[key=value,...]|TRAJ:[BOUNDED|ESCAPING|CONVERGED|OSCILLATING]|BLOCK:[none|reason]
```

## SIGNALS
When complete: `SIGNAL:READY:{agent_name}`
When blocked: `SIGNAL:BLOCKED:{agent_name}:{reason}`
When failed: `SIGNAL:FAILED:{agent_name}:{reason}`

## VERIFY (Before Claiming Done)
- Tests pass
- PRODUCES outputs exist
- VERIFY commands succeed

## COMPLETE
```
COMPLETE
GOAL:[verbatim]
CHANGED:[file]:[what]
ADDED:[file]:[purpose]
VERIFIED:[evidence]
SIGNAL:READY:{agent_name}
```
"""
    
    def build_system_prompt(self, contract: Contract) -> str:
        """
        Build the system prompt for an agent.
        
        Includes:
        - Base protocol
        - Contract section
        - Tool instructions
        """
        protocol = self._get_protocol()
        contract_section = contract.to_system_prompt_section()
        
        tool_instructions = self._get_tool_instructions(contract)
        
        return f"""
{protocol}

---

{contract_section}

---

{tool_instructions}

---

## CRITICAL INSTRUCTIONS

1. You are agent `{contract.name}` - always identify yourself in signals
2. File operations outside SCOPE will fail - don't attempt them
3. Before signaling READY, verify all PRODUCES exist and VERIFY commands pass
4. If blocked, signal BLOCKED immediately with reason
5. Always emit exactly one terminal signal: READY, BLOCKED, or FAILED
"""
    
    def _get_tool_instructions(self, contract: Contract) -> str:
        """Generate tool usage instructions based on scope."""
        return f"""
## AVAILABLE TOOLS

### read_file
Read a file from your scope.
Arguments: {{"path": "relative/path/to/file"}}
Allowed paths: {', '.join(contract.scope)}

### write_file
Write content to a file in your scope.
Arguments: {{"path": "relative/path/to/file", "content": "file content"}}
Allowed paths: {', '.join(contract.scope)}

### execute
Run a shell command in your workspace.
Arguments: {{"command": "shell command"}}
Use for: running tests, builds, verification commands

### list_files
List files in a directory within your scope.
Arguments: {{"path": "relative/path/to/dir"}}

### signal
Emit a coordination signal.
Arguments: {{"type": "READY|BLOCKED|FAILED", "payload": "optional reason"}}
"""
    
    def get_tools(self, contract: Contract) -> list[dict]:
        """
        Get tool definitions for the Claude API.
        
        Tools are scoped based on the contract.
        """
        return [
            {
                "name": "read_file",
                "description": f"Read a file. Allowed: {', '.join(contract.scope)}",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Relative path to file"
                        }
                    },
                    "required": ["path"]
                }
            },
            {
                "name": "write_file", 
                "description": f"Write a file. Allowed: {', '.join(contract.scope)}",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Relative path to file"
                        },
                        "content": {
                            "type": "string",
                            "description": "Content to write"
                        }
                    },
                    "required": ["path", "content"]
                }
            },
            {
                "name": "execute",
                "description": "Run a shell command in workspace",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "Shell command to execute"
                        }
                    },
                    "required": ["command"]
                }
            },
            {
                "name": "list_files",
                "description": f"List directory contents. Allowed: {', '.join(contract.scope)}",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Relative path to directory"
                        }
                    },
                    "required": ["path"]
                }
            },
            {
                "name": "signal",
                "description": "Emit a coordination signal (READY, BLOCKED, or FAILED)",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": ["READY", "BLOCKED", "FAILED"],
                            "description": "Signal type"
                        },
                        "payload": {
                            "type": "string",
                            "description": "Optional reason/details"
                        }
                    },
                    "required": ["type"]
                }
            }
        ]
    
    async def create_conversation(
        self,
        contract: Contract,
        goal: str,
    ) -> "AgentConversation":
        """
        Create a new conversation for an agent.
        
        Returns an AgentConversation that can be used to
        interact with the agent.
        """
        return AgentConversation(
            client=self,
            contract=contract,
            goal=goal,
        )
    
    def parse_response(
        self,
        content: str,
        agent_name: str,
    ) -> AgentResponse:
        """
        Parse a Claude response to extract structured data.
        
        Extracts:
        - Signals from SIGNAL: lines
        - Trajectory from TRAJ: field
        - File operations from CHANGED/ADDED lines
        - Verification results from VERIFIED: section
        - Checkpoint data if present
        """
        signals = self._extract_signals(content, agent_name)
        trajectory = self._extract_trajectory(content)
        files_modified, files_created = self._extract_file_ops(content)
        verification = self._extract_verification(content)
        checkpoint = self._extract_checkpoint(content)
        
        is_complete = "COMPLETE" in content or any(
            s.type == SignalType.READY for s in signals
        )
        is_blocked = any(
            s.type in (SignalType.BLOCKED, SignalType.FAILED) for s in signals
        )
        block_reason = None
        if is_blocked:
            for s in signals:
                if s.type in (SignalType.BLOCKED, SignalType.FAILED):
                    block_reason = s.payload
                    break
        
        return AgentResponse(
            content=content,
            signals=signals,
            trajectory=trajectory,
            files_modified=files_modified,
            files_created=files_created,
            verification_results=verification,
            is_complete=is_complete,
            is_blocked=is_blocked,
            block_reason=block_reason,
            checkpoint=checkpoint,
        )
    
    def _extract_signals(self, content: str, agent_name: str) -> list[Signal]:
        """Extract signal declarations from response."""
        signals = []
        
        # Pattern: SIGNAL:TYPE:agent:payload or SIGNAL:TYPE:agent
        pattern = r'SIGNAL:(READY|BLOCKED|FAILED|DATA|ESCALATE):(\w+)(?::([^\n]+))?'
        
        for match in re.finditer(pattern, content):
            signal_type = SignalType(match.group(1))
            agent = match.group(2)
            payload = match.group(3)
            
            signals.append(Signal(
                type=signal_type,
                agent=agent,
                payload=payload,
            ))
        
        # Also check for READY:agent format without SIGNAL: prefix
        simple_pattern = r'^(READY|BLOCKED|FAILED):(\w+)(?::([^\n]+))?$'
        for match in re.finditer(simple_pattern, content, re.MULTILINE):
            signal_type = SignalType(match.group(1))
            agent = match.group(2)
            payload = match.group(3) if match.group(3) else None
            
            # Avoid duplicates
            existing = any(
                s.type == signal_type and s.agent == agent 
                for s in signals
            )
            if not existing:
                signals.append(Signal(
                    type=signal_type,
                    agent=agent,
                    payload=payload,
                ))
        
        return signals
    
    def _extract_trajectory(self, content: str) -> Trajectory:
        """Extract trajectory state from header."""
        match = re.search(r'TRAJ:(BOUNDED|ESCAPING|CONVERGED|OSCILLATING)', content)
        if match:
            return Trajectory(match.group(1))
        return Trajectory.BOUNDED
    
    def _extract_file_ops(self, content: str) -> tuple[list[str], list[str]]:
        """Extract file operations from CHANGED/ADDED lines."""
        modified = []
        created = []
        
        for match in re.finditer(r'^CHANGED:([^:]+):', content, re.MULTILINE):
            modified.append(match.group(1))
        
        for match in re.finditer(r'^ADDED:([^:]+):', content, re.MULTILINE):
            created.append(match.group(1))
        
        return modified, created
    
    def _extract_verification(self, content: str) -> dict[str, bool]:
        """Extract verification results."""
        results = {}
        
        # Look for VERIFIED: section
        verified_match = re.search(
            r'VERIFIED:\s*\n((?:- .+\n)+)',
            content
        )
        if verified_match:
            for line in verified_match.group(1).split('\n'):
                line = line.strip()
                if line.startswith('- '):
                    # Check for success indicators
                    passed = any(
                        ind in line.lower() 
                        for ind in ('✓', 'pass', 'exit 0', 'success', 'ok')
                    )
                    results[line[2:]] = passed
        
        return results
    
    def _extract_checkpoint(self, content: str) -> Optional[dict]:
        """Extract checkpoint data if present."""
        if 'CHECKPOINT' not in content:
            return None
        
        checkpoint = {}
        
        patterns = {
            'goal': r'GOAL:([^\n]+)',
            'phase': r'PHASE:([^\n]+)',
            'done': r'DONE:([^\n]+)',
            'wip': r'WIP:([^\n]+)',
            'todo': r'TODO:([^\n]+)',
            'state': r'STATE:([^\n]+)',
            'commit': r'COMMIT:([^\n]+)',
            'resume': r'RESUME:([^\n]+)',
        }
        
        for key, pattern in patterns.items():
            match = re.search(pattern, content)
            if match:
                checkpoint[key] = match.group(1).strip()
        
        return checkpoint if checkpoint else None


class AgentConversation:
    """
    Manages a conversation with a Claude agent.
    
    Handles:
    - Message history
    - Tool call execution
    - Response streaming
    """
    
    def __init__(
        self,
        client: ClaudeClient,
        contract: Contract,
        goal: str,
    ):
        self.client = client
        self.contract = contract
        self.goal = goal
        self.messages: list[dict] = []
        self.system_prompt = client.build_system_prompt(contract)
        self.tools = client.get_tools(contract)
        
        # Tool handlers (set by orchestrator)
        self.tool_handlers: dict[str, Callable] = {}
    
    def set_tool_handler(self, name: str, handler: Callable) -> None:
        """Register a handler for a tool."""
        self.tool_handlers[name] = handler
    
    async def send(self, message: str) -> AgentResponse:
        """
        Send a message and get a response.
        
        Handles tool calls automatically using registered handlers.
        """
        import anthropic
        
        self.messages.append({
            "role": "user",
            "content": message,
        })
        
        client = anthropic.Anthropic(api_key=self.client.api_key)
        
        while True:
            response = client.messages.create(
                model=self.client.model,
                max_tokens=8192,
                system=self.system_prompt,
                tools=self.tools,
                messages=self.messages,
            )
            
            # Collect response content
            assistant_content = []
            tool_uses = []
            text_content = ""
            
            for block in response.content:
                if block.type == "text":
                    text_content += block.text
                    assistant_content.append({
                        "type": "text",
                        "text": block.text,
                    })
                elif block.type == "tool_use":
                    tool_uses.append(block)
                    assistant_content.append({
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    })
            
            self.messages.append({
                "role": "assistant",
                "content": assistant_content,
            })
            
            # Handle tool calls
            if tool_uses:
                tool_results = []
                for tool_use in tool_uses:
                    result = await self._handle_tool(tool_use)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use.id,
                        "content": result,
                    })
                
                self.messages.append({
                    "role": "user",
                    "content": tool_results,
                })
                
                # Continue conversation if not end_turn
                if response.stop_reason != "end_turn":
                    continue
            
            # Parse and return response
            return self.client.parse_response(text_content, self.contract.name)
    
    async def _handle_tool(self, tool_use) -> str:
        """Execute a tool and return the result."""
        handler = self.tool_handlers.get(tool_use.name)
        
        if handler:
            try:
                result = await handler(tool_use.input)
                return json.dumps({"success": True, "result": result})
            except PermissionError as e:
                return json.dumps({
                    "success": False,
                    "error": f"Access denied: {e}"
                })
            except Exception as e:
                return json.dumps({
                    "success": False,
                    "error": str(e)
                })
        else:
            return json.dumps({
                "success": False,
                "error": f"Unknown tool: {tool_use.name}"
            })
