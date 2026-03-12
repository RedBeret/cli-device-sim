from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, TypeVar

from cli_device_sim.config import SimulatorSettings
from cli_device_sim.logging_utils import log_event
from cli_device_sim.models import (
    AuditEntry,
    DeviceConfig,
    InterfaceConfig,
    InterfaceSummary,
    LocalUser,
    MutationResult,
    SnapshotRecord,
    StateResponse,
    utc_now,
)
from cli_device_sim.rendering import render_config

T = TypeVar("T")


def build_default_config() -> DeviceConfig:
    return DeviceConfig(
        hostname="LAB-EDGE-01",
        model="SyntheticEdge-24T",
        version="1.0.0",
        serial_number="SIM-FTX0001LAB",
        terminal_length_default=24,
        users=[
            LocalUser(username="automation", secret="lab-automation"),
            LocalUser(username="operator", secret="lab-operator"),
        ],
        interfaces=[
            InterfaceConfig(
                name="GigabitEthernet0/1",
                description="Uplink-to-198.51.100.10",
                shutdown=False,
                ipv4_address="198.51.100.10",
            ),
            InterfaceConfig(
                name="GigabitEthernet0/2",
                description="Student-port-203.0.113.20",
                shutdown=True,
                ipv4_address="203.0.113.20",
            ),
            InterfaceConfig(
                name="Loopback0",
                description="Synthetic-loopback-192.0.2.1",
                shutdown=False,
                ipv4_address="192.0.2.1",
            ),
        ],
    )


def sanitize_command(command: str) -> str:
    parts = command.split()
    for index, part in enumerate(parts[:-1]):
        if part.lower() == "secret":
            parts[index + 1] = "<redacted>"
            break
    return " ".join(parts)


class StateRepository:
    def __init__(self, settings: SimulatorSettings, logger: logging.Logger) -> None:
        self.settings = settings
        self.logger = logger
        self.db_path = Path(settings.db_path)
        self._write_lock = threading.RLock()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=self.settings.sqlite_timeout_seconds, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute(f"PRAGMA busy_timeout = {int(self.settings.sqlite_timeout_seconds * 1000)}")
        return connection

    def _run_with_retry(self, operation_name: str, operation: Callable[[], T]) -> T:
        delay = self.settings.sqlite_backoff_seconds
        for attempt in range(1, self.settings.sqlite_retries + 1):
            try:
                return operation()
            except sqlite3.OperationalError as exc:
                is_locked = "locked" in str(exc).lower() or "busy" in str(exc).lower()
                if not is_locked or attempt == self.settings.sqlite_retries:
                    raise
                log_event(
                    self.logger,
                    logging.WARNING,
                    "Retrying SQLite operation after lock",
                    operation=operation_name,
                    attempt=attempt,
                    backoff_seconds=delay,
                )
                time.sleep(delay)
                delay *= 2
        raise RuntimeError(f"SQLite retry loop for {operation_name} exhausted unexpectedly.")

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        def operation() -> None:
            with self._connect() as connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS config_snapshots (
                        kind TEXT PRIMARY KEY,
                        state_json TEXT NOT NULL,
                        revision INTEGER NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS audit_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        happened_at TEXT NOT NULL,
                        actor TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        success INTEGER NOT NULL,
                        details_json TEXT NOT NULL
                    )
                    """
                )
                row = connection.execute("SELECT COUNT(*) AS count FROM config_snapshots").fetchone()
                if row["count"] == 0:
                    default_config = build_default_config()
                    timestamp = utc_now().isoformat()
                    for kind in ("running", "startup"):
                        connection.execute(
                            """
                            INSERT INTO config_snapshots (kind, state_json, revision, updated_at)
                            VALUES (?, ?, ?, ?)
                            """,
                            (kind, default_config.model_dump_json(), 1, timestamp),
                        )
                connection.commit()

        self._run_with_retry("initialize", operation)

    def authenticate(self, username: str, password: str) -> bool:
        running = self.get_snapshot("running")
        return any(user.username == username and user.secret == password for user in running.config.users)

    def get_snapshot(self, kind: str) -> SnapshotRecord:
        def operation() -> SnapshotRecord:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT state_json, revision, updated_at FROM config_snapshots WHERE kind = ?",
                    (kind,),
                ).fetchone()
            if row is None:
                raise KeyError(f"Snapshot {kind} was not found.")
            return SnapshotRecord(
                config=DeviceConfig.model_validate_json(row["state_json"]),
                revision=int(row["revision"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
            )

        return self._run_with_retry(f"get_snapshot:{kind}", operation)

    def get_state_response(self) -> StateResponse:
        running = self.get_snapshot("running")
        startup = self.get_snapshot("startup")
        dirty = running.config.model_dump() != startup.config.model_dump()
        drift_present = "DRIFT-INJECTED" in render_config(running.config)
        interfaces = [
            InterfaceSummary(
                name=interface.name,
                admin_status="down" if interface.shutdown else "up",
                oper_status="down" if interface.shutdown else "up",
                ipv4_address=interface.ipv4_address,
                description=interface.description,
            )
            for interface in running.config.interfaces
        ]
        recent_audit = self.list_recent_audit(limit=self.settings.audit_limit)
        return StateResponse(
            hostname=running.config.hostname,
            running_revision=running.revision,
            startup_revision=startup.revision,
            dirty=dirty,
            drift_present=drift_present,
            users=[user.username for user in sorted(running.config.users, key=lambda item: item.username)],
            interfaces=interfaces,
            recent_audit=recent_audit,
        )

    def render_snapshot(self, kind: str) -> str:
        return render_config(self.get_snapshot(kind).config)

    def list_recent_audit(self, *, limit: int) -> list[AuditEntry]:
        def operation() -> list[AuditEntry]:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT happened_at, actor, event_type, success, details_json
                    FROM audit_log
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            entries: list[AuditEntry] = []
            for row in rows:
                entries.append(
                    AuditEntry(
                        happened_at=datetime.fromisoformat(row["happened_at"]),
                        actor=row["actor"],
                        event_type=row["event_type"],
                        success=bool(row["success"]),
                        details=json.loads(row["details_json"]),
                    )
                )
            return entries

        return self._run_with_retry("list_recent_audit", operation)

    def append_audit(self, *, actor: str, event_type: str, success: bool, details: dict[str, object]) -> None:
        payload = json.dumps(details, sort_keys=True)

        def operation() -> None:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO audit_log (happened_at, actor, event_type, success, details_json)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (utc_now().isoformat(), actor, event_type, int(success), payload),
                )
                connection.commit()

        self._run_with_retry("append_audit", operation)

    def mutate_running(
        self,
        *,
        mutator: Callable[[DeviceConfig], None],
        updated_message: str,
        no_change_message: str,
    ) -> MutationResult:
        with self._write_lock:
            current = self.get_snapshot("running")
            mutated = current.config.model_copy(deep=True)
            mutator(mutated)
            validated = DeviceConfig.model_validate(mutated.model_dump())
            if validated.model_dump() == current.config.model_dump():
                return MutationResult(status="no_change", snapshot=current, message=no_change_message)
            updated_snapshot = self._save_snapshot("running", validated)
            return MutationResult(status="updated", snapshot=updated_snapshot, message=updated_message)

    def sync_startup_with_running(self) -> MutationResult:
        with self._write_lock:
            running = self.get_snapshot("running")
            startup = self.get_snapshot("startup")
            if running.config.model_dump() == startup.config.model_dump():
                return MutationResult(
                    status="no_change",
                    snapshot=startup,
                    message="Startup configuration already matches running configuration.",
                )
            updated_snapshot = self._save_snapshot("startup", running.config)
            return MutationResult(
                status="updated",
                snapshot=updated_snapshot,
                message="Building configuration...\n[OK]",
            )

    def reset_to_defaults(self) -> MutationResult:
        defaults = build_default_config()
        with self._write_lock:
            running = self.get_snapshot("running")
            startup = self.get_snapshot("startup")
            if (
                running.config.model_dump() == defaults.model_dump()
                and startup.config.model_dump() == defaults.model_dump()
            ):
                return MutationResult(status="no_change", snapshot=running, message="Simulator already matches the baseline.")
            self._save_snapshot("running", defaults)
            updated_startup = self._save_snapshot("startup", defaults)
            return MutationResult(status="updated", snapshot=updated_startup, message="Simulator reset to baseline.")

    def inject_drift(self) -> MutationResult:
        def mutator(config: DeviceConfig) -> None:
            interface = config.ensure_interface("GigabitEthernet0/2")
            interface.description = "DRIFT-INJECTED-to-203.0.113.77"
            interface.shutdown = False

        return self.mutate_running(
            mutator=mutator,
            updated_message="Synthetic drift injected into running configuration.",
            no_change_message="Synthetic drift is already present in running configuration.",
        )

    def _save_snapshot(self, kind: str, config: DeviceConfig) -> SnapshotRecord:
        timestamp = utc_now().isoformat()

        def operation() -> SnapshotRecord:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT revision FROM config_snapshots WHERE kind = ?",
                    (kind,),
                ).fetchone()
                next_revision = 1 if row is None else int(row["revision"]) + 1
                connection.execute(
                    """
                    INSERT INTO config_snapshots (kind, state_json, revision, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(kind) DO UPDATE SET
                        state_json = excluded.state_json,
                        revision = excluded.revision,
                        updated_at = excluded.updated_at
                    """,
                    (kind, config.model_dump_json(), next_revision, timestamp),
                )
                connection.commit()
            return SnapshotRecord(config=config, revision=next_revision, updated_at=datetime.fromisoformat(timestamp))

        return self._run_with_retry(f"save_snapshot:{kind}", operation)

