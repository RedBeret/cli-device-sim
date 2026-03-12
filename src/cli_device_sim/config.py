from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class SimulatorSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SIM_", extra="ignore")

    api_host: str = "0.0.0.0"
    api_port: int = 8080
    ssh_host: str = "0.0.0.0"
    ssh_port: int = 2222
    db_path: Path = Field(default=Path("data/sim.db"))
    ssh_host_key_path: Path = Field(default=Path("data/host_key.pem"))
    log_level: str = "INFO"
    sqlite_timeout_seconds: float = 2.0
    sqlite_retries: int = 5
    sqlite_backoff_seconds: float = 0.05
    socket_timeout_seconds: float = 5.0
    channel_timeout_seconds: float = 1.0
    audit_limit: int = 15

