"""
Contract Parser - Extract agent specifications from protocol output.

Parses the SCOPE FORMAT blocks:
---AGENT:name
SCOPE: path1, path2
CANNOT: path3, path4
DEPENDS: READY:other
EXPECTS: some input
PRODUCES: some output
VERIFY: npm test
---
"""

import re
from typing import Iterator
from .models import Contract


class ContractParser:
    """Parse agent contracts from various formats."""
    
    # Pattern for agent block delimiters
    AGENT_BLOCK_PATTERN = re.compile(
        r'---AGENT:(\w[\w-]*)\s*\n(.*?)---',
        re.DOTALL | re.MULTILINE
    )
    
    # Patterns for individual fields
    FIELD_PATTERNS = {
        'scope': re.compile(r'^SCOPE:\s*(.+)$', re.MULTILINE | re.IGNORECASE),
        'cannot': re.compile(r'^CANNOT:\s*(.+)$', re.MULTILINE | re.IGNORECASE),
        'depends': re.compile(r'^DEPENDS:\s*(.+)$', re.MULTILINE | re.IGNORECASE),
        'expects': re.compile(r'^EXPECTS:\s*(.+)$', re.MULTILINE | re.IGNORECASE),
        'produces': re.compile(r'^PRODUCES:\s*(.+)$', re.MULTILINE | re.IGNORECASE),
        'verify': re.compile(r'^VERIFY:\s*(.+)$', re.MULTILINE | re.IGNORECASE),
    }
    
    @classmethod
    def parse_markdown(cls, content: str) -> list[Contract]:
        """
        Parse all agent contracts from markdown content.
        
        Args:
            content: Markdown string containing agent blocks
            
        Returns:
            List of Contract objects
        """
        contracts = []
        
        for match in cls.AGENT_BLOCK_PATTERN.finditer(content):
            name = match.group(1)
            body = match.group(2)
            
            contract = cls._parse_block(name, body)
            contracts.append(contract)
        
        return contracts
    
    @classmethod
    def _parse_block(cls, name: str, body: str) -> Contract:
        """Parse a single agent block body into a Contract."""
        fields = {}
        
        for field_name, pattern in cls.FIELD_PATTERNS.items():
            match = pattern.search(body)
            if match:
                value = match.group(1).strip()
                fields[field_name] = cls._parse_value(value, field_name)
            else:
                fields[field_name] = []
        
        return Contract(
            name=name,
            scope=fields['scope'],
            cannot=fields['cannot'],
            depends=fields['depends'],
            expects=fields['expects'],
            produces=fields['produces'],
            verify=fields['verify'],
        )
    
    @classmethod
    def _parse_value(cls, value: str, field_name: str) -> list[str]:
        """Parse a field value into a list of items."""
        if value.lower() == 'none':
            return []
        
        # Handle semicolon-separated commands (for verify)
        if field_name == 'verify' and ';' in value:
            return [cmd.strip() for cmd in value.split(';') if cmd.strip()]
        
        # Handle comma-separated values
        if ',' in value:
            return [item.strip() for item in value.split(',') if item.strip()]
        
        # Single value
        return [value] if value else []
    
    @classmethod
    def parse_yaml(cls, content: str) -> list[Contract]:
        """
        Parse agent contracts from YAML format.
        
        Expected format:
        agents:
          - name: backend
            scope: [backend/, api/]
            cannot: [frontend/]
            depends: [READY:database]
            ...
        """
        import yaml
        
        data = yaml.safe_load(content)
        contracts = []
        
        for agent_data in data.get('agents', []):
            contract = Contract(
                name=agent_data['name'],
                scope=agent_data.get('scope', []),
                cannot=agent_data.get('cannot', []),
                depends=agent_data.get('depends', []),
                expects=agent_data.get('expects', []),
                produces=agent_data.get('produces', []),
                verify=agent_data.get('verify', []),
                goal=agent_data.get('goal', ''),
            )
            contracts.append(contract)
        
        return contracts
    
    @classmethod
    def validate_contracts(cls, contracts: list[Contract]) -> list[str]:
        """
        Validate a set of contracts for consistency.
        
        Checks:
        - No overlapping scopes
        - All dependencies reference existing agents
        - At least one agent has no dependencies (entry point)
        
        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []
        agent_names = {c.name for c in contracts}
        
        # Check for overlapping scopes
        for i, c1 in enumerate(contracts):
            for c2 in contracts[i+1:]:
                overlap = cls._find_scope_overlap(c1.scope, c2.scope)
                if overlap:
                    errors.append(
                        f"Scope overlap between {c1.name} and {c2.name}: {overlap}"
                    )
        
        # Check dependency references
        has_entry_point = False
        for contract in contracts:
            deps = contract.get_dependency_signals()
            if not deps:
                has_entry_point = True
            
            for dep in deps:
                # Extract agent name from signal
                if ':' in dep:
                    dep_agent = dep.split(':')[1]
                else:
                    dep_agent = dep
                
                if dep_agent not in agent_names:
                    errors.append(
                        f"Agent {contract.name} depends on unknown agent: {dep_agent}"
                    )
        
        if not has_entry_point and contracts:
            errors.append("No entry point: all agents have dependencies (circular?)")
        
        return errors
    
    @classmethod
    def _find_scope_overlap(cls, scope1: list[str], scope2: list[str]) -> list[str]:
        """Find overlapping paths between two scopes."""
        overlaps = []
        
        for s1 in scope1:
            for s2 in scope2:
                # Simple prefix check (more sophisticated glob matching could be added)
                s1_base = s1.rstrip('/*')
                s2_base = s2.rstrip('/*')
                
                if s1_base.startswith(s2_base) or s2_base.startswith(s1_base):
                    overlaps.append(f"{s1} <-> {s2}")
        
        return overlaps
    
    @classmethod
    def from_claude_response(cls, response: str) -> tuple[list[Contract], dict]:
        """
        Parse contracts and metadata from a Claude response.
        
        Extracts:
        - Agent contracts from ---AGENT blocks
        - Complexity calculation if present
        - Execution order if specified
        
        Returns:
            Tuple of (contracts, metadata_dict)
        """
        contracts = cls.parse_markdown(response)
        
        metadata = {
            'complexity': None,
            'execution_mode': None,
            'split_reason': None,
        }
        
        # Extract complexity
        complexity_match = re.search(r'C\s*=\s*(\d+)', response)
        if complexity_match:
            metadata['complexity'] = int(complexity_match.group(1))
        
        # Extract execution mode
        if 'SEQUENTIAL' in response.upper():
            metadata['execution_mode'] = 'sequential'
        elif 'PARALLEL' in response.upper():
            metadata['execution_mode'] = 'parallel'
        
        # Extract split reason
        split_match = re.search(r'SPLIT REQUIRED.*?(?=\n\n|\Z)', response, re.DOTALL)
        if split_match:
            metadata['split_reason'] = split_match.group(0).strip()
        
        return contracts, metadata


def parse_contracts(source: str) -> list[Contract]:
    """
    Convenience function to parse contracts from any format.
    
    Auto-detects format based on content.
    """
    # Try YAML first
    if source.strip().startswith('agents:') or source.strip().startswith('---\nagents:'):
        return ContractParser.parse_yaml(source)
    
    # Otherwise treat as markdown
    return ContractParser.parse_markdown(source)
