# Runbook

## Start

From Windows PowerShell:

```powershell
.\scripts\Start-Sim.ps1
```

Health check:

```powershell
Invoke-RestMethod http://127.0.0.1:8080/healthz
```

SSH target:

```powershell
ssh operator@127.0.0.1 -p 2222
```

## Stop

```powershell
.\scripts\Stop-Sim.ps1
```

## Mutating workflow: CLI running-config changes

Example:

```text
enable
configure terminal
hostname LAB-EDGE-STUDENT
interface GigabitEthernet0/2
description Study-port-203.0.113.44
no shutdown
end
```

Validation:

- `show running-config`
- `show interfaces summary`
- `GET /state`

Rollback notes:

- Re-enter configuration mode and restore the prior hostname or description.
- Use `shutdown` to reverse a prior `no shutdown`.
- If you want to discard all ad hoc changes quickly, call `POST /reset`.

## Mutating workflow: save running to startup

Example:

```text
enable
write memory
```

Validation:

- `show startup-config`
- compare running and startup config
- `GET /state` should report `"dirty": false`

Rollback notes:

- There is no single-command undo for `write memory`.
- If you saved an unwanted configuration, reset the simulator and replay the desired baseline.
- Before saving in training scenarios, inspect `show running-config` so you know what you are committing.

## Mutating workflow: POST /inject-drift

Example:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8080/inject-drift
```

Validation:

- `GET /state`
- `GET /running-config`
- `show interfaces summary`

Rollback notes:

- Correct the drifted interface through the CLI and optionally save it.
- If you want to return immediately to baseline, call `POST /reset`.

## Mutating workflow: POST /reset

Example:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8080/reset
```

Validation:

- `GET /state`
- `show running-config`
- `show startup-config`

Rollback notes:

- `POST /reset` intentionally overwrites both running and startup snapshots.
- There is no automatic restore path after reset.
- If you need to preserve a scenario before resetting, export `GET /running-config` or `show running-config` first.

## Demo workflow

Fastest path from Windows:

```powershell
.\scripts\Start-Sim.ps1 -Demo
```

That path is idempotent because it resets the simulator first.

## Health triage

- If `/healthz` is down, inspect `docker compose logs sim`.
- If SSH is down but API is up, restart the stack and inspect recent audit entries.
- If state looks wrong, inspect `/state` before resetting so you keep the evidence for the exercise.
