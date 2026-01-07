"""
Signal Broker - Inter-agent coordination system.

Provides a pub/sub mechanism for agents to:
- Emit signals (READY, BLOCKED, FAILED, etc.)
- Wait for dependency signals
- Query signal state

Supports multiple backends:
- In-memory (for single-process orchestration)
- File-based (for multi-process/container scenarios)
- Redis (for distributed execution)
"""

import asyncio
import json
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Callable, Awaitable
from .models import Signal, SignalType


class SignalBroker(ABC):
    """Abstract base for signal coordination."""
    
    @abstractmethod
    async def emit(self, signal: Signal) -> None:
        """Emit a signal."""
        pass
    
    @abstractmethod
    async def wait_for(
        self, 
        signal_pattern: str, 
        timeout: Optional[float] = None
    ) -> Optional[Signal]:
        """
        Wait for a signal matching the pattern.
        
        Pattern format: "TYPE:agent" or "TYPE:*" for any agent
        """
        pass
    
    @abstractmethod
    async def query(self, agent: str) -> list[Signal]:
        """Get all signals from an agent."""
        pass
    
    @abstractmethod
    async def has_signal(self, signal_pattern: str) -> bool:
        """Check if a signal exists without waiting."""
        pass
    
    @abstractmethod
    async def clear(self) -> None:
        """Clear all signals (for testing/reset)."""
        pass


class InMemoryBroker(SignalBroker):
    """
    In-memory signal broker using asyncio.
    
    Best for single-process orchestration where all agents
    run as concurrent tasks.
    """
    
    def __init__(self):
        self._signals: list[Signal] = []
        self._subscribers: dict[str, list[asyncio.Event]] = {}
        self._lock = asyncio.Lock()
    
    async def emit(self, signal: Signal) -> None:
        """Emit a signal and notify subscribers."""
        signal.timestamp = time.time()
        
        async with self._lock:
            self._signals.append(signal)
            
            # Notify matching subscribers
            pattern = str(signal)
            for sub_pattern, events in list(self._subscribers.items()):
                if self._matches_pattern(signal, sub_pattern):
                    for event in events:
                        event.set()
    
    async def wait_for(
        self, 
        signal_pattern: str, 
        timeout: Optional[float] = None
    ) -> Optional[Signal]:
        """Wait for a signal matching the pattern."""
        # Check if signal already exists
        async with self._lock:
            for signal in reversed(self._signals):
                if self._matches_pattern(signal, signal_pattern):
                    return signal
            
            # Set up subscription
            event = asyncio.Event()
            if signal_pattern not in self._subscribers:
                self._subscribers[signal_pattern] = []
            self._subscribers[signal_pattern].append(event)
        
        try:
            # Wait for signal
            await asyncio.wait_for(event.wait(), timeout)
            
            # Find the matching signal
            async with self._lock:
                for signal in reversed(self._signals):
                    if self._matches_pattern(signal, signal_pattern):
                        return signal
        except asyncio.TimeoutError:
            return None
        finally:
            # Clean up subscription
            async with self._lock:
                if signal_pattern in self._subscribers:
                    self._subscribers[signal_pattern].remove(event)
                    if not self._subscribers[signal_pattern]:
                        del self._subscribers[signal_pattern]
        
        return None
    
    async def query(self, agent: str) -> list[Signal]:
        """Get all signals from an agent."""
        async with self._lock:
            return [s for s in self._signals if s.agent == agent]
    
    async def has_signal(self, signal_pattern: str) -> bool:
        """Check if a signal exists."""
        async with self._lock:
            for signal in self._signals:
                if self._matches_pattern(signal, signal_pattern):
                    return True
        return False
    
    async def clear(self) -> None:
        """Clear all signals."""
        async with self._lock:
            self._signals.clear()
            self._subscribers.clear()
    
    def _matches_pattern(self, signal: Signal, pattern: str) -> bool:
        """Check if a signal matches a pattern like 'READY:backend' or 'READY:*'."""
        parts = pattern.split(":", 2)
        
        if len(parts) < 2:
            return False
        
        signal_type, agent = parts[0], parts[1]
        
        # Check type
        if signal_type != "*" and signal.type.value != signal_type:
            return False
        
        # Check agent
        if agent != "*" and signal.agent != agent:
            return False
        
        return True


class FileBroker(SignalBroker):
    """
    File-based signal broker.
    
    Uses a directory of JSON files for coordination.
    Suitable for multi-process scenarios where agents run
    in separate containers but share a mounted volume.
    """
    
    def __init__(self, signal_dir: Path):
        self.signal_dir = Path(signal_dir)
        self.signal_dir.mkdir(parents=True, exist_ok=True)
    
    async def emit(self, signal: Signal) -> None:
        """Write signal to file."""
        signal.timestamp = time.time()
        
        filename = f"{signal.agent}_{signal.type.value}_{int(signal.timestamp * 1000)}.json"
        filepath = self.signal_dir / filename
        
        data = {
            "type": signal.type.value,
            "agent": signal.agent,
            "payload": signal.payload,
            "timestamp": signal.timestamp,
        }
        
        filepath.write_text(json.dumps(data))
    
    async def wait_for(
        self, 
        signal_pattern: str, 
        timeout: Optional[float] = None
    ) -> Optional[Signal]:
        """Poll for signal file."""
        start = time.time()
        poll_interval = 0.1
        
        while True:
            if await self.has_signal(signal_pattern):
                signals = await self._load_signals()
                for signal in reversed(signals):
                    if self._matches_pattern(signal, signal_pattern):
                        return signal
            
            if timeout and (time.time() - start) >= timeout:
                return None
            
            await asyncio.sleep(poll_interval)
    
    async def query(self, agent: str) -> list[Signal]:
        """Load all signals from agent."""
        signals = await self._load_signals()
        return [s for s in signals if s.agent == agent]
    
    async def has_signal(self, signal_pattern: str) -> bool:
        """Check for signal file."""
        signals = await self._load_signals()
        for signal in signals:
            if self._matches_pattern(signal, signal_pattern):
                return True
        return False
    
    async def clear(self) -> None:
        """Remove all signal files."""
        for filepath in self.signal_dir.glob("*.json"):
            filepath.unlink()
    
    async def _load_signals(self) -> list[Signal]:
        """Load all signals from directory."""
        signals = []
        
        for filepath in sorted(self.signal_dir.glob("*.json")):
            try:
                data = json.loads(filepath.read_text())
                signal = Signal(
                    type=SignalType(data["type"]),
                    agent=data["agent"],
                    payload=data.get("payload"),
                    timestamp=data.get("timestamp", 0),
                )
                signals.append(signal)
            except (json.JSONDecodeError, KeyError, ValueError):
                continue
        
        return signals
    
    def _matches_pattern(self, signal: Signal, pattern: str) -> bool:
        """Same matching logic as InMemoryBroker."""
        parts = pattern.split(":", 2)
        
        if len(parts) < 2:
            return False
        
        signal_type, agent = parts[0], parts[1]
        
        if signal_type != "*" and signal.type.value != signal_type:
            return False
        
        if agent != "*" and signal.agent != agent:
            return False
        
        return True


class RedisBroker(SignalBroker):
    """
    Redis-based signal broker for distributed execution.
    
    Uses Redis pub/sub for real-time notifications
    and sorted sets for signal persistence.
    """
    
    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self.redis_url = redis_url
        self._redis = None
        self._pubsub = None
    
    async def _get_redis(self):
        """Lazy initialization of Redis connection."""
        if self._redis is None:
            import redis.asyncio as redis
            self._redis = redis.from_url(self.redis_url)
        return self._redis
    
    async def emit(self, signal: Signal) -> None:
        """Publish signal to Redis."""
        signal.timestamp = time.time()
        r = await self._get_redis()
        
        data = json.dumps({
            "type": signal.type.value,
            "agent": signal.agent,
            "payload": signal.payload,
            "timestamp": signal.timestamp,
        })
        
        # Store in sorted set (by timestamp)
        await r.zadd("agent_signals", {data: signal.timestamp})
        
        # Publish for real-time subscribers
        await r.publish("agent_signals_channel", data)
    
    async def wait_for(
        self, 
        signal_pattern: str, 
        timeout: Optional[float] = None
    ) -> Optional[Signal]:
        """Subscribe and wait for signal."""
        # Check existing signals first
        if await self.has_signal(signal_pattern):
            signals = await self._load_signals()
            for signal in reversed(signals):
                if self._matches_pattern(signal, signal_pattern):
                    return signal
        
        # Subscribe for new signals
        r = await self._get_redis()
        pubsub = r.pubsub()
        await pubsub.subscribe("agent_signals_channel")
        
        try:
            start = time.time()
            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                
                data = json.loads(message["data"])
                signal = Signal(
                    type=SignalType(data["type"]),
                    agent=data["agent"],
                    payload=data.get("payload"),
                    timestamp=data.get("timestamp", 0),
                )
                
                if self._matches_pattern(signal, signal_pattern):
                    return signal
                
                if timeout and (time.time() - start) >= timeout:
                    return None
        finally:
            await pubsub.unsubscribe("agent_signals_channel")
        
        return None
    
    async def query(self, agent: str) -> list[Signal]:
        """Get all signals from agent."""
        signals = await self._load_signals()
        return [s for s in signals if s.agent == agent]
    
    async def has_signal(self, signal_pattern: str) -> bool:
        """Check Redis for signal."""
        signals = await self._load_signals()
        for signal in signals:
            if self._matches_pattern(signal, signal_pattern):
                return True
        return False
    
    async def clear(self) -> None:
        """Clear all signals from Redis."""
        r = await self._get_redis()
        await r.delete("agent_signals")
    
    async def _load_signals(self) -> list[Signal]:
        """Load all signals from Redis sorted set."""
        r = await self._get_redis()
        raw_signals = await r.zrange("agent_signals", 0, -1)
        
        signals = []
        for raw in raw_signals:
            data = json.loads(raw)
            signal = Signal(
                type=SignalType(data["type"]),
                agent=data["agent"],
                payload=data.get("payload"),
                timestamp=data.get("timestamp", 0),
            )
            signals.append(signal)
        
        return signals
    
    def _matches_pattern(self, signal: Signal, pattern: str) -> bool:
        """Same matching logic as other brokers."""
        parts = pattern.split(":", 2)
        
        if len(parts) < 2:
            return False
        
        signal_type, agent = parts[0], parts[1]
        
        if signal_type != "*" and signal.type.value != signal_type:
            return False
        
        if agent != "*" and signal.agent != agent:
            return False
        
        return True


def create_broker(backend: str = "memory", **kwargs) -> SignalBroker:
    """
    Factory function to create a signal broker.
    
    Args:
        backend: One of "memory", "file", "redis"
        **kwargs: Backend-specific configuration
        
    Returns:
        Configured SignalBroker instance
    """
    if backend == "memory":
        return InMemoryBroker()
    elif backend == "file":
        signal_dir = kwargs.get("signal_dir", Path("/tmp/agent_signals"))
        return FileBroker(signal_dir)
    elif backend == "redis":
        redis_url = kwargs.get("redis_url", "redis://localhost:6379")
        return RedisBroker(redis_url)
    else:
        raise ValueError(f"Unknown broker backend: {backend}")
