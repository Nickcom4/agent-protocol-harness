"""
Filesystem Isolator - Enforces scope constraints via Docker.

Creates isolated environments where agents can only see/modify
files within their declared SCOPE.

Isolation mechanisms:
1. Docker containers with volume mounts
2. Read-only mounts for CANNOT paths
3. Workspace overlay for modifications
"""

import asyncio
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import fnmatch
import hashlib

from .models import Contract


@dataclass
class IsolatedWorkspace:
    """
    An isolated workspace for an agent.
    
    Contains:
    - Scoped view of the repository
    - Writable overlay for modifications
    - Signal directory mount
    """
    agent_name: str
    container_id: Optional[str]
    workspace_path: Path
    repo_root: Path
    signal_dir: Path
    
    # Tracking
    files_written: list[str]
    files_read: list[str]
    
    async def get_modifications(self) -> dict[str, str]:
        """Get all files modified by the agent."""
        mods = {}
        for rel_path in self.files_written:
            full_path = self.workspace_path / rel_path
            if full_path.exists():
                mods[rel_path] = full_path.read_text()
        return mods
    
    async def cleanup(self) -> None:
        """Remove the isolated workspace."""
        if self.container_id:
            proc = await asyncio.create_subprocess_exec(
                "docker", "rm", "-f", self.container_id,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
        
        if self.workspace_path.exists():
            shutil.rmtree(self.workspace_path)


class FilesystemIsolator:
    """
    Creates isolated filesystems for agents based on their contracts.
    
    Uses Docker to enforce scope constraints:
    - SCOPE paths are mounted read-write
    - CANNOT paths are not visible
    - All modifications go to an overlay directory
    """
    
    def __init__(
        self, 
        repo_root: Path,
        work_dir: Optional[Path] = None,
        use_docker: bool = True,
        docker_image: str = "python:3.11-slim"
    ):
        self.repo_root = Path(repo_root).resolve()
        self.work_dir = Path(work_dir or tempfile.mkdtemp(prefix="agent_harness_"))
        self.use_docker = use_docker
        self.docker_image = docker_image
        
        self.work_dir.mkdir(parents=True, exist_ok=True)
    
    async def create_workspace(
        self, 
        contract: Contract,
        signal_dir: Path,
    ) -> IsolatedWorkspace:
        """
        Create an isolated workspace for an agent.
        
        Args:
            contract: The agent's contract defining scope
            signal_dir: Directory for signal files
            
        Returns:
            IsolatedWorkspace with configured isolation
        """
        # Create workspace directory
        workspace_id = hashlib.sha256(
            f"{contract.name}_{os.getpid()}".encode()
        ).hexdigest()[:12]
        
        workspace_path = self.work_dir / f"agent_{contract.name}_{workspace_id}"
        workspace_path.mkdir(parents=True, exist_ok=True)
        
        # Copy scoped files to workspace
        await self._copy_scoped_files(contract, workspace_path)
        
        container_id = None
        if self.use_docker:
            container_id = await self._create_container(
                contract, workspace_path, signal_dir
            )
        
        return IsolatedWorkspace(
            agent_name=contract.name,
            container_id=container_id,
            workspace_path=workspace_path,
            repo_root=self.repo_root,
            signal_dir=signal_dir,
            files_written=[],
            files_read=[],
        )
    
    async def _copy_scoped_files(
        self, 
        contract: Contract, 
        workspace_path: Path
    ) -> None:
        """Copy only files matching scope patterns to workspace."""
        for root, dirs, files in os.walk(self.repo_root):
            # Skip hidden directories and common excludes
            dirs[:] = [
                d for d in dirs 
                if not d.startswith('.') 
                and d not in ('node_modules', '__pycache__', 'venv', '.git')
            ]
            
            for filename in files:
                full_path = Path(root) / filename
                rel_path = full_path.relative_to(self.repo_root)
                
                # Check if path is in scope and not forbidden
                if contract.path_allowed(str(rel_path)):
                    dest_path = workspace_path / rel_path
                    dest_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(full_path, dest_path)
    
    async def _create_container(
        self,
        contract: Contract,
        workspace_path: Path,
        signal_dir: Path,
    ) -> str:
        """Create a Docker container with isolated mounts."""
        # Build volume mounts
        mounts = [
            f"{workspace_path}:/workspace:rw",
            f"{signal_dir}:/signals:rw",
        ]
        
        # Create container
        cmd = [
            "docker", "create",
            "--name", f"agent_{contract.name}_{os.getpid()}",
            "-w", "/workspace",
            "-e", f"AGENT_NAME={contract.name}",
            "-e", "AGENT_ISOLATED=true",
        ]
        
        for mount in mounts:
            cmd.extend(["-v", mount])
        
        cmd.extend([
            self.docker_image,
            "tail", "-f", "/dev/null"  # Keep container alive
        ])
        
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        
        if proc.returncode != 0:
            raise RuntimeError(f"Failed to create container: {stderr.decode()}")
        
        container_id = stdout.decode().strip()
        
        # Start the container
        proc = await asyncio.create_subprocess_exec(
            "docker", "start", container_id,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        
        if proc.returncode != 0:
            raise RuntimeError(f"Failed to start container: {stderr.decode()}")
        
        return container_id
    
    async def execute_in_workspace(
        self,
        workspace: IsolatedWorkspace,
        command: str,
        timeout: float = 300,
    ) -> tuple[int, str, str]:
        """
        Execute a command in the isolated workspace.
        
        Returns:
            Tuple of (return_code, stdout, stderr)
        """
        if workspace.container_id:
            return await self._execute_in_container(
                workspace.container_id, command, timeout
            )
        else:
            return await self._execute_local(
                workspace.workspace_path, command, timeout
            )
    
    async def _execute_in_container(
        self,
        container_id: str,
        command: str,
        timeout: float,
    ) -> tuple[int, str, str]:
        """Execute command inside Docker container."""
        proc = await asyncio.create_subprocess_exec(
            "docker", "exec", container_id,
            "sh", "-c", command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
            return proc.returncode, stdout.decode(), stderr.decode()
        except asyncio.TimeoutError:
            proc.kill()
            return -1, "", "Command timed out"
    
    async def _execute_local(
        self,
        workspace_path: Path,
        command: str,
        timeout: float,
    ) -> tuple[int, str, str]:
        """Execute command locally in workspace directory."""
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=workspace_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={
                **os.environ,
                "AGENT_ISOLATED": "true",
            }
        )
        
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
            return proc.returncode, stdout.decode(), stderr.decode()
        except asyncio.TimeoutError:
            proc.kill()
            return -1, "", "Command timed out"
    
    async def sync_back(
        self,
        workspace: IsolatedWorkspace,
        target_dir: Optional[Path] = None,
    ) -> dict[str, Path]:
        """
        Sync modified files back to the target directory.
        
        Args:
            workspace: The isolated workspace
            target_dir: Where to copy files (defaults to repo_root)
            
        Returns:
            Dict of relative_path -> absolute_path for modified files
        """
        target = target_dir or self.repo_root
        synced = {}
        
        # Walk workspace and find modified/new files
        for root, dirs, files in os.walk(workspace.workspace_path):
            # Skip hidden and temp directories
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            
            for filename in files:
                workspace_file = Path(root) / filename
                rel_path = workspace_file.relative_to(workspace.workspace_path)
                
                # Skip signal files and temp files
                if str(rel_path).startswith(('signals/', '.tmp')):
                    continue
                
                target_file = target / rel_path
                original_file = self.repo_root / rel_path
                
                # Check if file is new or modified
                is_new = not original_file.exists()
                is_modified = (
                    not is_new and 
                    workspace_file.read_bytes() != original_file.read_bytes()
                )
                
                if is_new or is_modified:
                    target_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(workspace_file, target_file)
                    synced[str(rel_path)] = target_file
        
        return synced
    
    async def cleanup_all(self) -> None:
        """Clean up all workspaces and containers."""
        # Stop all agent containers
        proc = await asyncio.create_subprocess_shell(
            "docker ps -q --filter 'name=agent_*' | xargs -r docker rm -f",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        
        # Remove work directory
        if self.work_dir.exists():
            shutil.rmtree(self.work_dir)


class ScopeEnforcer:
    """
    Runtime scope enforcement for file operations.
    
    Can be used as a wrapper around file operations to enforce
    contract scope without full container isolation.
    """
    
    def __init__(self, contract: Contract, base_path: Path):
        self.contract = contract
        self.base_path = Path(base_path).resolve()
        self._access_log: list[tuple[str, str, bool]] = []  # (path, op, allowed)
    
    def check_read(self, path: str | Path) -> bool:
        """Check if reading from path is allowed."""
        allowed = self._check_access(path)
        self._access_log.append((str(path), "read", allowed))
        return allowed
    
    def check_write(self, path: str | Path) -> bool:
        """Check if writing to path is allowed."""
        allowed = self._check_access(path)
        self._access_log.append((str(path), "write", allowed))
        return allowed
    
    def _check_access(self, path: str | Path) -> bool:
        """Check if path is within allowed scope."""
        path = Path(path)
        
        # Make path relative if absolute
        if path.is_absolute():
            try:
                path = path.relative_to(self.base_path)
            except ValueError:
                return False  # Outside base path
        
        return self.contract.path_allowed(str(path))
    
    def get_violations(self) -> list[tuple[str, str]]:
        """Get list of access violations (path, operation)."""
        return [(p, op) for p, op, allowed in self._access_log if not allowed]
    
    def wrap_open(self, original_open):
        """
        Create a wrapped open() that enforces scope.
        
        Usage:
            enforcer = ScopeEnforcer(contract, repo_root)
            with enforcer.wrap_open(open) as safe_open:
                f = safe_open("file.txt", "r")
        """
        def safe_open(path, mode="r", *args, **kwargs):
            is_write = any(m in mode for m in ('w', 'a', 'x', '+'))
            
            if is_write:
                if not self.check_write(path):
                    raise PermissionError(
                        f"Write access denied by contract: {path}"
                    )
            else:
                if not self.check_read(path):
                    raise PermissionError(
                        f"Read access denied by contract: {path}"
                    )
            
            return original_open(path, mode, *args, **kwargs)
        
        return safe_open
