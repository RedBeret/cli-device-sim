from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


HOSTNAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9-]{0,31}$")
USERNAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
GIGABIT_INTERFACE_PATTERN = re.compile(r"^gigabitethernet\d+/\d+$", re.IGNORECASE)
LOOPBACK_INTERFACE_PATTERN = re.compile(r"^loopback\d+$", re.IGNORECASE)


def utc_now() -> datetime:
    return datetime.now(UTC)


def canonicalize_interface_name(value: str) -> str:
    stripped = value.strip()
    if GIGABIT_INTERFACE_PATTERN.fullmatch(stripped):
        suffix = stripped[len("gigabitethernet") :]
        return f"GigabitEthernet{suffix}"
    if LOOPBACK_INTERFACE_PATTERN.fullmatch(stripped):
        suffix = stripped[len("loopback") :]
        return f"Loopback{suffix}"
    raise ValueError("Interface name must look like GigabitEthernet0/1 or Loopback0.")


class LocalUser(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str
    secret: str

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        if not USERNAME_PATTERN.fullmatch(value):
            raise ValueError("Username must be lowercase letters, numbers, or hyphens.")
        return value

    @field_validator("secret")
    @classmethod
    def validate_secret(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 6:
            raise ValueError("Secret must be at least 6 characters long.")
        return cleaned


class InterfaceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    shutdown: bool = True
    ipv4_address: str = "unassigned"

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return canonicalize_interface_name(value)

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) > 120:
            raise ValueError("Description must be 120 characters or fewer.")
        return cleaned


class DeviceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hostname: str = "LAB-EDGE-01"
    model: str = "SyntheticEdge-24T"
    version: str = "1.0.0"
    serial_number: str = "SIM-FTX0001LAB"
    terminal_length_default: int = 24
    users: list[LocalUser] = Field(default_factory=list)
    interfaces: list[InterfaceConfig] = Field(default_factory=list)

    @field_validator("hostname")
    @classmethod
    def validate_hostname(cls, value: str) -> str:
        if not HOSTNAME_PATTERN.fullmatch(value):
            raise ValueError("Hostname must start with a letter and use only letters, numbers, or hyphens.")
        return value

    def get_interface(self, name: str) -> InterfaceConfig | None:
        canonical_name = canonicalize_interface_name(name)
        for interface in self.interfaces:
            if interface.name == canonical_name:
                return interface
        return None

    def ensure_interface(self, name: str) -> InterfaceConfig:
        existing = self.get_interface(name)
        if existing is not None:
            return existing
        interface = InterfaceConfig(name=name)
        self.interfaces.append(interface)
        return interface


class InterfaceSummary(BaseModel):
    name: str
    admin_status: Literal["up", "down"]
    oper_status: Literal["up", "down"]
    ipv4_address: str
    description: str


class AuditEntry(BaseModel):
    happened_at: datetime
    actor: str
    event_type: str
    success: bool
    details: dict[str, object] = Field(default_factory=dict)


class StateResponse(BaseModel):
    hostname: str
    running_revision: int
    startup_revision: int
    dirty: bool
    drift_present: bool
    users: list[str]
    interfaces: list[InterfaceSummary]
    recent_audit: list[AuditEntry]


class MutateResponse(BaseModel):
    status: Literal["updated", "no_change"]
    message: str
    state: StateResponse


@dataclass(slots=True)
class SnapshotRecord:
    config: DeviceConfig
    revision: int
    updated_at: datetime


@dataclass(slots=True)
class MutationResult:
    status: Literal["updated", "no_change"]
    snapshot: SnapshotRecord
    message: str
