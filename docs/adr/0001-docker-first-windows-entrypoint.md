# ADR 0001: Docker-first Windows entrypoint

- Status: Accepted

## Context

The host environment is Windows-first, and local Python may not exist on the machine. The repo still needs a one-command demo path and a predictable runtime.

## Decision

Use Docker Compose as the default runtime and PowerShell wrappers as the primary user entrypoint.

## Consequences

- Windows users get a stable `.\scripts\Start-Sim.ps1 -Demo` workflow.
- Linux-specific tooling stays inside Docker or optional WSL usage.
- The repo avoids assuming Python, virtualenv tooling, or shell parity on the host.
