"""
Tests for the Agent Protocol Harness.
"""

import pytest
import asyncio
from pathlib import Path
import tempfile
import shutil

from agent_harness import (
    Contract,
    Signal,
    SignalType,
    Trajectory,
    ExecutionPlan,
    ContractParser,
    parse_contracts,
    create_broker,
    ScopeEnforcer,
)


class TestContract:
    """Tests for Contract model."""
    
    def test_path_allowed_in_scope(self):
        contract = Contract(
            name="test",
            scope=["src/", "lib/"],
            cannot=["tests/"],
        )
        
        assert contract.path_allowed("src/main.py")
        assert contract.path_allowed("src/utils/helper.py")
        assert contract.path_allowed("lib/module.js")
    
    def test_path_denied_in_cannot(self):
        contract = Contract(
            name="test",
            scope=["src/", "tests/"],
            cannot=["tests/fixtures/"],
        )
        
        # tests/ is in scope but tests/fixtures/ is in cannot
        assert contract.path_allowed("tests/test_main.py")
        assert not contract.path_allowed("tests/fixtures/data.json")
    
    def test_path_denied_outside_scope(self):
        contract = Contract(
            name="test",
            scope=["backend/"],
            cannot=[],
        )
        
        assert not contract.path_allowed("frontend/app.js")
        assert not contract.path_allowed("README.md")
    
    def test_glob_patterns(self):
        contract = Contract(
            name="test",
            scope=["*.py", "src/**/*.js"],
            cannot=["*.test.py"],
        )
        
        assert contract.path_allowed("main.py")
        assert not contract.path_allowed("main.test.py")
    
    def test_dependency_signals(self):
        contract = Contract(
            name="frontend",
            scope=["frontend/"],
            depends=["READY:backend", "READY:database"],
        )
        
        signals = contract.get_dependency_signals()
        assert "READY:backend" in signals
        assert "READY:database" in signals
    
    def test_dependency_none(self):
        contract = Contract(
            name="entry",
            scope=["src/"],
            depends=["none"],
        )
        
        assert contract.get_dependency_signals() == []


class TestSignal:
    """Tests for Signal model."""
    
    def test_signal_to_string(self):
        signal = Signal(SignalType.READY, "backend")
        assert str(signal) == "READY:backend"
        
        signal = Signal(SignalType.BLOCKED, "auth", "missing credentials")
        assert str(signal) == "BLOCKED:auth:missing credentials"
    
    def test_signal_parse(self):
        signal = Signal.parse("READY:backend")
        assert signal.type == SignalType.READY
        assert signal.agent == "backend"
        assert signal.payload is None
        
        signal = Signal.parse("FAILED:worker:timeout exceeded")
        assert signal.type == SignalType.FAILED
        assert signal.agent == "worker"
        assert signal.payload == "timeout exceeded"


class TestContractParser:
    """Tests for contract parsing."""
    
    def test_parse_markdown_single_agent(self):
        markdown = """
---AGENT:backend
SCOPE: backend/, api/
CANNOT: frontend/, *.md
DEPENDS: none
EXPECTS: database connection
PRODUCES: REST API endpoints
VERIFY: npm test; curl localhost:3000/health
---
"""
        contracts = ContractParser.parse_markdown(markdown)
        
        assert len(contracts) == 1
        assert contracts[0].name == "backend"
        assert contracts[0].scope == ["backend/", "api/"]
        assert contracts[0].cannot == ["frontend/", "*.md"]
        assert contracts[0].depends == []
        assert contracts[0].verify == ["npm test", "curl localhost:3000/health"]
    
    def test_parse_markdown_multiple_agents(self):
        markdown = """
Some preamble text...

---AGENT:database
SCOPE: database/
DEPENDS: none
PRODUCES: migrations
VERIFY: npm run migrate
---

Some text between...

---AGENT:backend
SCOPE: backend/
DEPENDS: READY:database
PRODUCES: API
VERIFY: npm test
---
"""
        contracts = ContractParser.parse_markdown(markdown)
        
        assert len(contracts) == 2
        assert contracts[0].name == "database"
        assert contracts[1].name == "backend"
        assert contracts[1].depends == ["READY:database"]
    
    def test_parse_yaml(self):
        yaml_content = """
agents:
  - name: backend
    scope:
      - backend/
      - api/
    cannot:
      - frontend/
    depends:
      - READY:database
    produces:
      - REST endpoints
    verify:
      - npm test
    goal: Build the backend
"""
        contracts = ContractParser.parse_yaml(yaml_content)
        
        assert len(contracts) == 1
        assert contracts[0].name == "backend"
        assert contracts[0].scope == ["backend/", "api/"]
        assert contracts[0].goal == "Build the backend"
    
    def test_validate_no_overlap(self):
        contracts = [
            Contract(name="a", scope=["src/a/"]),
            Contract(name="b", scope=["src/b/"]),
        ]
        
        errors = ContractParser.validate_contracts(contracts)
        assert errors == []
    
    def test_validate_overlap_detected(self):
        contracts = [
            Contract(name="a", scope=["src/"]),
            Contract(name="b", scope=["src/utils/"]),  # Overlaps with src/
        ]
        
        errors = ContractParser.validate_contracts(contracts)
        assert len(errors) == 1
        assert "overlap" in errors[0].lower()
    
    def test_validate_missing_dependency(self):
        contracts = [
            Contract(name="frontend", scope=["frontend/"], depends=["READY:backend"]),
        ]
        
        errors = ContractParser.validate_contracts(contracts)
        assert len(errors) == 1
        assert "unknown agent" in errors[0].lower()
    
    def test_validate_no_entry_point(self):
        contracts = [
            Contract(name="a", scope=["a/"], depends=["READY:b"]),
            Contract(name="b", scope=["b/"], depends=["READY:a"]),
        ]
        
        errors = ContractParser.validate_contracts(contracts)
        assert any("entry point" in e.lower() or "circular" in e.lower() for e in errors)


class TestExecutionPlan:
    """Tests for execution planning."""
    
    def test_sequential_dependencies(self):
        contracts = [
            Contract(name="a", scope=["a/"], depends=[]),
            Contract(name="b", scope=["b/"], depends=["READY:a"]),
            Contract(name="c", scope=["c/"], depends=["READY:b"]),
        ]
        
        plan = ExecutionPlan.from_contracts(contracts)
        
        assert plan.sequential_order == ["a", "b", "c"]
    
    def test_parallel_groups(self):
        contracts = [
            Contract(name="database", scope=["db/"], depends=[]),
            Contract(name="cache", scope=["cache/"], depends=[]),
            Contract(name="backend", scope=["backend/"], depends=["READY:database", "READY:cache"]),
        ]
        
        plan = ExecutionPlan.from_contracts(contracts)
        
        # database and cache can run in parallel
        first_group = plan.parallel_groups[0]
        assert set(first_group) == {"database", "cache"}
        
        # backend runs after
        assert "backend" in plan.parallel_groups[1]
    
    def test_circular_dependency_detected(self):
        contracts = [
            Contract(name="a", scope=["a/"], depends=["READY:b"]),
            Contract(name="b", scope=["b/"], depends=["READY:a"]),
        ]
        
        with pytest.raises(ValueError, match="[Cc]ircular"):
            ExecutionPlan.from_contracts(contracts)


class TestSignalBroker:
    """Tests for signal coordination."""
    
    @pytest.mark.asyncio
    async def test_emit_and_query(self):
        broker = create_broker("memory")
        
        signal = Signal(SignalType.READY, "backend")
        await broker.emit(signal)
        
        signals = await broker.query("backend")
        assert len(signals) == 1
        assert signals[0].type == SignalType.READY
    
    @pytest.mark.asyncio
    async def test_wait_for_existing(self):
        broker = create_broker("memory")
        
        await broker.emit(Signal(SignalType.READY, "backend"))
        
        result = await broker.wait_for("READY:backend", timeout=1.0)
        assert result is not None
        assert result.agent == "backend"
    
    @pytest.mark.asyncio
    async def test_wait_for_timeout(self):
        broker = create_broker("memory")
        
        result = await broker.wait_for("READY:nonexistent", timeout=0.1)
        assert result is None
    
    @pytest.mark.asyncio
    async def test_wait_for_future_signal(self):
        broker = create_broker("memory")
        
        async def emit_later():
            await asyncio.sleep(0.1)
            await broker.emit(Signal(SignalType.READY, "delayed"))
        
        # Start emitter
        asyncio.create_task(emit_later())
        
        # Wait should receive the signal
        result = await broker.wait_for("READY:delayed", timeout=1.0)
        assert result is not None
        assert result.agent == "delayed"
    
    @pytest.mark.asyncio
    async def test_has_signal(self):
        broker = create_broker("memory")
        
        assert not await broker.has_signal("READY:backend")
        
        await broker.emit(Signal(SignalType.READY, "backend"))
        
        assert await broker.has_signal("READY:backend")
        assert not await broker.has_signal("READY:frontend")
    
    @pytest.mark.asyncio
    async def test_clear(self):
        broker = create_broker("memory")
        
        await broker.emit(Signal(SignalType.READY, "a"))
        await broker.emit(Signal(SignalType.READY, "b"))
        
        await broker.clear()
        
        assert not await broker.has_signal("READY:a")
        assert not await broker.has_signal("READY:b")


class TestScopeEnforcer:
    """Tests for runtime scope enforcement."""
    
    def test_read_allowed_in_scope(self):
        contract = Contract(name="test", scope=["src/"])
        enforcer = ScopeEnforcer(contract, Path("/repo"))
        
        assert enforcer.check_read("src/main.py")
        assert enforcer.check_read("src/utils/helper.py")
    
    def test_read_denied_outside_scope(self):
        contract = Contract(name="test", scope=["src/"])
        enforcer = ScopeEnforcer(contract, Path("/repo"))
        
        assert not enforcer.check_read("tests/test_main.py")
        assert not enforcer.check_read("README.md")
    
    def test_write_denied_in_cannot(self):
        contract = Contract(
            name="test",
            scope=["src/", "tests/"],
            cannot=["tests/fixtures/"],
        )
        enforcer = ScopeEnforcer(contract, Path("/repo"))
        
        assert enforcer.check_write("tests/test_main.py")
        assert not enforcer.check_write("tests/fixtures/data.json")
    
    def test_violations_tracked(self):
        contract = Contract(name="test", scope=["src/"])
        enforcer = ScopeEnforcer(contract, Path("/repo"))
        
        enforcer.check_read("src/ok.py")  # Allowed
        enforcer.check_read("tests/bad.py")  # Denied
        enforcer.check_write("config/bad.yaml")  # Denied
        
        violations = enforcer.get_violations()
        assert len(violations) == 2
        assert ("tests/bad.py", "read") in violations
        assert ("config/bad.yaml", "write") in violations


class TestFileBroker:
    """Tests for file-based signal broker."""
    
    @pytest.mark.asyncio
    async def test_file_broker_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            broker = create_broker("file", signal_dir=Path(tmpdir))
            
            await broker.emit(Signal(SignalType.READY, "test", "payload"))
            
            assert await broker.has_signal("READY:test")
            
            result = await broker.wait_for("READY:test", timeout=1.0)
            assert result is not None
            assert result.payload == "payload"


# Integration test (requires API key)
class TestIntegration:
    """Integration tests - skipped without API key."""
    
    @pytest.mark.skip(reason="Requires ANTHROPIC_API_KEY")
    @pytest.mark.asyncio
    async def test_simple_orchestration(self):
        from agent_harness import Orchestrator
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a minimal repo
            repo = Path(tmpdir) / "repo"
            repo.mkdir()
            (repo / "src").mkdir()
            (repo / "src" / "main.py").write_text("# placeholder")
            
            contracts = [
                Contract(
                    name="simple",
                    scope=["src/"],
                    depends=[],
                    verify=[],
                    goal="Add a hello function to main.py",
                ),
            ]
            
            orchestrator = Orchestrator(
                repo_root=repo,
                use_docker=False,
            )
            
            result = await orchestrator.run(contracts)
            
            assert result.success
            assert "simple" in result.agents
