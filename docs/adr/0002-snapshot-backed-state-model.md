# ADR 0002: Snapshot-backed state model

- Status: Accepted

## Context

The training objective depends on clearly separating running and startup config. A line-oriented text store would work, but it would make validation, idempotency, and tests harder.

## Decision

Store validated `DeviceConfig` snapshots in SQLite for `running` and `startup`, then render them into CLI text on demand.

## Consequences

- Mutations can be validated through Pydantic before they are persisted.
- `write memory` becomes an explicit copy from running to startup.
- Tests can assert object-level outcomes without relying only on terminal scraping.
- The CLI output stays deterministic and easy to compare in docs and training notes.

