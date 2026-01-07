"""
CLI - Command-line interface for the Agent Protocol Harness.

Commands:
- run: Execute contracts from file or Claude response
- validate: Check contracts for errors
- plan: Show execution plan without running
- watch: Monitor running agents
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Optional

import click

from .parser import ContractParser, parse_contracts
from .models import ExecutionPlan, AgentStatus
from .orchestrator import Orchestrator, run_orchestration


@click.group()
@click.version_option(version="0.1.0")
def cli():
    """Agent Protocol Harness - Multi-agent orchestration with isolation."""
    pass


@cli.command()
@click.argument("contracts_file", type=click.Path(exists=True))
@click.option(
    "--repo", "-r",
    type=click.Path(exists=True),
    default=".",
    help="Repository root path"
)
@click.option(
    "--goal", "-g",
    multiple=True,
    help="Agent goal in format 'agent:goal text'"
)
@click.option(
    "--model", "-m",
    default="claude-sonnet-4-20250514",
    help="Claude model to use"
)
@click.option(
    "--protocol", "-p",
    type=click.Path(exists=True),
    help="Path to protocol markdown file"
)
@click.option(
    "--docker/--no-docker",
    default=False,
    help="Use Docker for isolation"
)
@click.option(
    "--timeout", "-t",
    default=600,
    help="Timeout per agent in seconds"
)
@click.option(
    "--output", "-o",
    type=click.Path(),
    help="Output JSON file for results"
)
@click.option(
    "--verbose", "-v",
    is_flag=True,
    help="Verbose output"
)
def run(
    contracts_file: str,
    repo: str,
    goal: tuple,
    model: str,
    protocol: Optional[str],
    docker: bool,
    timeout: int,
    output: Optional[str],
    verbose: bool,
):
    """
    Run agents from a contracts file.
    
    CONTRACTS_FILE can be markdown with ---AGENT blocks or YAML.
    
    Examples:
    
        # Run from markdown file
        agent-harness run contracts.md --repo ./myproject
        
        # Run with custom goals
        agent-harness run contracts.yaml -g "backend:add JWT auth" -g "frontend:add login page"
        
        # Run with Docker isolation
        agent-harness run contracts.md --docker --repo ./myproject
    """
    import logging
    
    if verbose:
        logging.basicConfig(level=logging.INFO)
    
    # Parse contracts
    contracts_content = Path(contracts_file).read_text()
    contracts = parse_contracts(contracts_content)
    
    if not contracts:
        click.echo("No contracts found in file", err=True)
        sys.exit(1)
    
    click.echo(f"Found {len(contracts)} agent(s): {', '.join(c.name for c in contracts)}")
    
    # Parse goals
    goals = {}
    for g in goal:
        if ":" in g:
            agent, goal_text = g.split(":", 1)
            goals[agent] = goal_text
    
    # Run orchestration
    async def execute():
        orchestrator = Orchestrator(
            repo_root=Path(repo),
            model=model,
            protocol_path=Path(protocol) if protocol else None,
            use_docker=docker,
            agent_timeout=timeout,
        )
        return await orchestrator.run(contracts, goals)
    
    result = asyncio.run(execute())
    
    # Output results
    if result.success:
        click.echo(click.style("\n✓ All agents completed successfully", fg="green"))
    else:
        click.echo(click.style("\n✗ Some agents failed", fg="red"))
    
    click.echo(f"\nExecution order: {' → '.join(result.execution_order)}")
    click.echo(f"Total duration: {result.total_duration_seconds:.1f}s")
    
    for name, agent_result in result.agents.items():
        status_color = "green" if agent_result.status == AgentStatus.COMPLETED else "red"
        click.echo(f"\n{name}:")
        click.echo(f"  Status: {click.style(agent_result.status.value, fg=status_color)}")
        click.echo(f"  Duration: {agent_result.duration_seconds:.1f}s")
        click.echo(f"  Restarts: {agent_result.restart_count}")
        click.echo(f"  Files created: {len(agent_result.files_created)}")
        click.echo(f"  Files modified: {len(agent_result.files_modified)}")
        click.echo(f"  Verification: {'✓' if agent_result.verification_passed else '✗'}")
        
        if agent_result.error:
            click.echo(f"  Error: {click.style(agent_result.error, fg='red')}")
    
    if result.errors:
        click.echo(click.style("\nErrors:", fg="red"))
        for error in result.errors:
            click.echo(f"  - {error}")
    
    # Write JSON output
    if output:
        output_data = {
            "success": result.success,
            "duration_seconds": result.total_duration_seconds,
            "execution_order": result.execution_order,
            "agents": {
                name: {
                    "status": r.status.value,
                    "duration_seconds": r.duration_seconds,
                    "files_created": list(r.files_created.keys()),
                    "files_modified": list(r.files_modified.keys()),
                    "verification_passed": r.verification_passed,
                    "error": r.error,
                    "restart_count": r.restart_count,
                }
                for name, r in result.agents.items()
            },
            "signals": [str(s) for s in result.signals],
            "errors": result.errors,
        }
        Path(output).write_text(json.dumps(output_data, indent=2))
        click.echo(f"\nResults written to {output}")
    
    sys.exit(0 if result.success else 1)


@cli.command()
@click.argument("contracts_file", type=click.Path(exists=True))
def validate(contracts_file: str):
    """
    Validate contracts for errors.
    
    Checks:
    - Syntax errors
    - Overlapping scopes
    - Missing dependencies
    - Circular dependencies
    """
    content = Path(contracts_file).read_text()
    
    try:
        contracts = parse_contracts(content)
    except Exception as e:
        click.echo(click.style(f"Parse error: {e}", fg="red"))
        sys.exit(1)
    
    if not contracts:
        click.echo("No contracts found")
        sys.exit(1)
    
    click.echo(f"Found {len(contracts)} contract(s)")
    
    errors = ContractParser.validate_contracts(contracts)
    
    if errors:
        click.echo(click.style("\nValidation errors:", fg="red"))
        for error in errors:
            click.echo(f"  ✗ {error}")
        sys.exit(1)
    else:
        click.echo(click.style("\n✓ All contracts valid", fg="green"))
        
        for contract in contracts:
            click.echo(f"\n{contract.name}:")
            click.echo(f"  Scope: {', '.join(contract.scope)}")
            click.echo(f"  Cannot: {', '.join(contract.cannot) or '(none)'}")
            click.echo(f"  Depends: {', '.join(contract.depends) or '(none)'}")
            click.echo(f"  Produces: {', '.join(contract.produces) or '(none)'}")


@cli.command()
@click.argument("contracts_file", type=click.Path(exists=True))
def plan(contracts_file: str):
    """
    Show execution plan without running.
    
    Displays:
    - Dependency graph
    - Parallel execution groups
    - Sequential ordering
    """
    content = Path(contracts_file).read_text()
    contracts = parse_contracts(content)
    
    if not contracts:
        click.echo("No contracts found")
        sys.exit(1)
    
    # Validate first
    errors = ContractParser.validate_contracts(contracts)
    if errors:
        click.echo(click.style("Validation errors - cannot plan:", fg="red"))
        for error in errors:
            click.echo(f"  ✗ {error}")
        sys.exit(1)
    
    # Build plan
    plan = ExecutionPlan.from_contracts(contracts)
    
    click.echo("Execution Plan")
    click.echo("=" * 40)
    
    click.echo("\nDependency Graph:")
    for contract in contracts:
        deps = contract.get_dependency_signals()
        if deps:
            click.echo(f"  {contract.name} ← {', '.join(deps)}")
        else:
            click.echo(f"  {contract.name} (entry point)")
    
    click.echo("\nParallel Groups:")
    for i, group in enumerate(plan.parallel_groups):
        if len(group) > 1:
            click.echo(f"  Group {i+1} (parallel): {', '.join(group)}")
        else:
            click.echo(f"  Group {i+1}: {group[0]}")
    
    click.echo(f"\nSequential Order: {' → '.join(plan.sequential_order)}")
    
    # Estimate complexity
    total_scopes = sum(len(c.scope) for c in contracts)
    click.echo(f"\nTotal scope patterns: {total_scopes}")
    click.echo(f"Max parallel agents: {max(len(g) for g in plan.parallel_groups)}")


@cli.command()
@click.argument("response_file", type=click.Path(exists=True))
@click.option(
    "--output", "-o",
    type=click.Path(),
    help="Output file for extracted contracts"
)
def extract(response_file: str, output: Optional[str]):
    """
    Extract contracts from a Claude response.
    
    Parses ---AGENT blocks from Claude's split response
    and optionally saves them to a file.
    """
    content = Path(response_file).read_text()
    contracts, metadata = ContractParser.from_claude_response(content)
    
    if not contracts:
        click.echo("No contracts found in response")
        sys.exit(1)
    
    click.echo(f"Extracted {len(contracts)} contract(s)")
    
    if metadata.get('complexity'):
        click.echo(f"Complexity: {metadata['complexity']}")
    if metadata.get('execution_mode'):
        click.echo(f"Execution: {metadata['execution_mode']}")
    
    for contract in contracts:
        click.echo(f"\n---AGENT:{contract.name}")
        click.echo(f"SCOPE: {', '.join(contract.scope)}")
        click.echo(f"CANNOT: {', '.join(contract.cannot)}")
        click.echo(f"DEPENDS: {', '.join(contract.depends) or 'none'}")
        click.echo(f"PRODUCES: {', '.join(contract.produces)}")
        click.echo(f"VERIFY: {'; '.join(contract.verify)}")
        click.echo("---")
    
    if output:
        # Write as YAML for easier editing
        import yaml
        
        data = {
            "agents": [
                {
                    "name": c.name,
                    "scope": c.scope,
                    "cannot": c.cannot,
                    "depends": c.depends,
                    "expects": c.expects,
                    "produces": c.produces,
                    "verify": c.verify,
                }
                for c in contracts
            ]
        }
        
        Path(output).write_text(yaml.dump(data, default_flow_style=False))
        click.echo(f"\nContracts written to {output}")


@cli.command()
@click.option(
    "--signal-dir", "-d",
    type=click.Path(),
    default="/tmp/agent_signals",
    help="Signal directory to watch"
)
def watch(signal_dir: str):
    """
    Watch agent signals in real-time.
    
    Monitors the signal directory and displays
    signals as they are emitted.
    """
    import time
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    
    class SignalHandler(FileSystemEventHandler):
        def on_created(self, event):
            if event.src_path.endswith('.json'):
                try:
                    data = json.loads(Path(event.src_path).read_text())
                    signal_type = data.get('type', 'UNKNOWN')
                    agent = data.get('agent', 'unknown')
                    payload = data.get('payload', '')
                    
                    color = {
                        'READY': 'green',
                        'BLOCKED': 'yellow', 
                        'FAILED': 'red',
                        'DATA': 'blue',
                        'ESCALATE': 'magenta',
                    }.get(signal_type, 'white')
                    
                    click.echo(
                        f"[{time.strftime('%H:%M:%S')}] "
                        f"{click.style(signal_type, fg=color)}:{agent}"
                        f"{':' + payload if payload else ''}"
                    )
                except Exception:
                    pass
    
    signal_path = Path(signal_dir)
    signal_path.mkdir(parents=True, exist_ok=True)
    
    click.echo(f"Watching {signal_dir} for signals...")
    click.echo("Press Ctrl+C to stop\n")
    
    observer = Observer()
    observer.schedule(SignalHandler(), str(signal_path), recursive=True)
    observer.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    
    observer.join()


def main():
    """Entry point."""
    cli()


if __name__ == "__main__":
    main()
