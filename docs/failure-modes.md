# Failure Modes

## Invalid command

- Symptom: the CLI returns `% Invalid command: ...`
- Cause: command is unsupported in this repo or used in the wrong mode.
- Recovery: check the current prompt and move to the correct mode first.

## Privileged command run from exec mode

- Symptom: `configure terminal`, `write memory`, or `show running-config` fails.
- Cause: you skipped `enable`.
- Recovery: enter `enable`, then retry.

## Authentication failure

- Symptom: SSH login is rejected.
- Cause: wrong fake username or secret, or the running config changed the login set.
- Recovery: reset the simulator or use a valid synthetic credential from the current running config.

## Unsaved config

- Symptom: startup config does not match running config after restart expectations.
- Cause: changes were made in running config but `write memory` was not issued.
- Recovery: reapply the changes and save, or accept the unsaved loss and reset.

## Drift present

- Symptom: `GET /state` shows `"dirty": true` after `POST /inject-drift`.
- Cause: running config no longer matches startup config.
- Recovery: correct the drift through CLI or reset to baseline.

## Docker or health startup failure

- Symptom: `.\scripts\Start-Sim.ps1` times out waiting for health.
- Cause: Docker Desktop is not running, ports are already in use, or image build failed.
- Recovery: check `docker compose ps` and `docker compose logs sim`, then retry.

## SQLite lock retry

- Symptom: logs show retry events for SQLite operations.
- Cause: overlapping access during startup, tests, or multiple local requests.
- Recovery: the app already retries with backoff; if it persists, stop extra clients and retry the workflow.

