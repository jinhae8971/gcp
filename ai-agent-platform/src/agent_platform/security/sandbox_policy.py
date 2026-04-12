"""Sandbox execution policies.

Declarative profiles that describe how the shell/tool runtime should be
isolated when executing agent-initiated commands. Consumers (tools/shell,
k8s runner, local subprocess wrapper) read the selected profile and apply
the appropriate kernel isolation.

We model three tiers:

  - LOCAL     : no isolation. Only for trusted dev environments.
  - CONTAINER : Docker/Podman with seccomp + user namespace.
  - GVISOR    : Docker + runsc runtime OR Firecracker microVM.

Each profile carries resource limits, network policy, syscall allowlist,
filesystem mounts, and environment filters. These are serialized into
runtime-specific flags by the concrete runner (not included here).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SandboxTier(str, Enum):
    LOCAL = "local"
    CONTAINER = "container"
    GVISOR = "gvisor"
    FIRECRACKER = "firecracker"


class NetworkPolicy(str, Enum):
    NONE = "none"          # no network at all
    OUTBOUND_ONLY = "outbound_only"
    ALLOWLIST = "allowlist"
    FULL = "full"


@dataclass
class ResourceLimits:
    cpu_cores: float = 1.0
    memory_mb: int = 1024
    pids_max: int = 256
    disk_mb: int = 512
    wall_timeout_seconds: int = 300


@dataclass
class SandboxPolicy:
    """A fully-resolved sandbox profile."""

    name: str
    tier: SandboxTier
    limits: ResourceLimits = field(default_factory=ResourceLimits)
    network: NetworkPolicy = NetworkPolicy.NONE
    network_allowlist: list[str] = field(default_factory=list)
    read_only_paths: list[str] = field(default_factory=list)
    writable_paths: list[str] = field(default_factory=list)
    blocked_syscalls: list[str] = field(default_factory=list)
    allowed_env_vars: list[str] = field(
        default_factory=lambda: ["PATH", "HOME", "LANG", "LC_ALL"]
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "tier": self.tier.value,
            "limits": {
                "cpu_cores": self.limits.cpu_cores,
                "memory_mb": self.limits.memory_mb,
                "pids_max": self.limits.pids_max,
                "disk_mb": self.limits.disk_mb,
                "wall_timeout_seconds": self.limits.wall_timeout_seconds,
            },
            "network": self.network.value,
            "network_allowlist": list(self.network_allowlist),
            "read_only_paths": list(self.read_only_paths),
            "writable_paths": list(self.writable_paths),
            "blocked_syscalls": list(self.blocked_syscalls),
            "allowed_env_vars": list(self.allowed_env_vars),
        }


# ── Built-in profiles ────────────────────────────────────────


BUILTIN_PROFILES: dict[str, SandboxPolicy] = {
    "dev": SandboxPolicy(
        name="dev",
        tier=SandboxTier.LOCAL,
        network=NetworkPolicy.FULL,
        limits=ResourceLimits(cpu_cores=4.0, memory_mb=4096, wall_timeout_seconds=600),
        writable_paths=["/workspace"],
        blocked_syscalls=[],
    ),
    "standard": SandboxPolicy(
        name="standard",
        tier=SandboxTier.CONTAINER,
        network=NetworkPolicy.OUTBOUND_ONLY,
        limits=ResourceLimits(cpu_cores=2.0, memory_mb=2048, wall_timeout_seconds=300),
        writable_paths=["/workspace"],
        read_only_paths=["/usr", "/bin", "/lib"],
        blocked_syscalls=["keyctl", "add_key", "request_key", "bpf", "ptrace"],
    ),
    "hardened": SandboxPolicy(
        name="hardened",
        tier=SandboxTier.GVISOR,
        network=NetworkPolicy.NONE,
        limits=ResourceLimits(cpu_cores=1.0, memory_mb=1024, wall_timeout_seconds=180),
        writable_paths=["/workspace"],
        read_only_paths=["/usr", "/bin", "/lib"],
        blocked_syscalls=[
            "keyctl", "add_key", "request_key", "bpf", "ptrace",
            "kexec_load", "kexec_file_load", "finit_module", "init_module",
            "delete_module", "mount", "umount2", "pivot_root", "chroot",
        ],
        allowed_env_vars=["PATH", "LANG"],
    ),
    "isolated_vm": SandboxPolicy(
        name="isolated_vm",
        tier=SandboxTier.FIRECRACKER,
        network=NetworkPolicy.NONE,
        limits=ResourceLimits(cpu_cores=1.0, memory_mb=512, wall_timeout_seconds=120),
        writable_paths=["/workspace"],
        blocked_syscalls=[],  # full VM boundary — syscall filtering less critical
        allowed_env_vars=["PATH"],
    ),
}


def get_profile(name: str) -> SandboxPolicy:
    """Look up a built-in sandbox profile by name."""
    if name not in BUILTIN_PROFILES:
        raise KeyError(
            f"Unknown sandbox profile: {name!r}. "
            f"Available: {sorted(BUILTIN_PROFILES)}"
        )
    return BUILTIN_PROFILES[name]


def select_profile(tier: str) -> SandboxPolicy:
    """Pick a sensible default profile for a given tier string.

    Maps the SandboxSettings.sandbox_mode strings to built-ins so settings
    consumers don't need to know profile names.
    """
    mapping = {
        "local": "dev",
        "container": "standard",
        "gvisor": "hardened",
        "firecracker": "isolated_vm",
    }
    profile_name = mapping.get(tier.lower(), "standard")
    return get_profile(profile_name)
