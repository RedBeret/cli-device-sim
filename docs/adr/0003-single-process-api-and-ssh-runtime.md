# ADR 0003: Single-process API and SSH runtime

- Status: Accepted

## Context

This repo is a local synthetic lab, not a production control plane. Adding multiple services or a process supervisor would increase operational complexity without improving the teaching outcome.

## Decision

Run the FastAPI inspection API and Paramiko SSH server inside one Python runtime, coordinated by a small `SimulatorRuntime`.

## Consequences

- The Docker image and demo path stay lightweight.
- Health checks can reason about both listeners from one place.
- Tests can start and stop the simulator in process.
- The design remains simple enough for learners to read end to end.
