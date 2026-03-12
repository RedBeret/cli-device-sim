from __future__ import annotations

import asyncio
import logging
import socket
import threading
import time

import uvicorn

from cli_device_sim.api import create_app
from cli_device_sim.config import SimulatorSettings
from cli_device_sim.logging_utils import configure_logging, log_event
from cli_device_sim.ssh_server import SSHServer
from cli_device_sim.state import StateRepository


class _ApiServerThread(threading.Thread):
    def __init__(self, app, host: str, port: int, log_level: str) -> None:
        super().__init__(name="cli-device-sim-api", daemon=True)
        config = uvicorn.Config(app, host=host, port=port, log_level=log_level.lower(), access_log=False)
        self.server = uvicorn.Server(config)

    def run(self) -> None:
        asyncio.set_event_loop(asyncio.new_event_loop())
        self.server.run()

    def stop(self) -> None:
        self.server.should_exit = True


class SimulatorRuntime:
    def __init__(self, settings: SimulatorSettings) -> None:
        configure_logging(settings.log_level)
        self.settings = settings
        self.logger = logging.getLogger("cli_device_sim.runtime")
        self.repository = StateRepository(settings, logging.getLogger("cli_device_sim.state"))
        self.ssh_server = SSHServer(settings, self.repository, logging.getLogger("cli_device_sim.ssh"))
        self.app = create_app(self)
        self.api_thread = _ApiServerThread(self.app, settings.api_host, settings.api_port, settings.log_level)

    def start(self) -> None:
        self.repository.initialize()
        self.ssh_server.start()
        self.api_thread.start()
        self.wait_for_ready()
        log_event(
            self.logger,
            logging.INFO,
            "Simulator runtime started",
            api_port=self.settings.api_port,
            ssh_port=self.settings.ssh_port,
            db_path=str(self.settings.db_path),
        )

    def stop(self) -> None:
        self.api_thread.stop()
        self.ssh_server.stop()
        self.api_thread.join(timeout=5)
        log_event(self.logger, logging.INFO, "Simulator runtime stopped")

    def wait_for_ready(self, timeout_seconds: float = 10.0) -> None:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            api_ok = self._can_connect(self._connect_host(self.settings.api_host), self.settings.api_port)
            ssh_ok = self._can_connect(self._connect_host(self.settings.ssh_host), self.settings.ssh_port)
            if api_ok and ssh_ok:
                return
            time.sleep(0.1)
        raise RuntimeError("Simulator runtime did not become ready in time.")

    def health_payload(self) -> dict[str, object]:
        ssh_ok = self.ssh_server.is_healthy()
        api_ok = self.api_thread.is_alive()
        return {
            "status": "ok" if ssh_ok and api_ok else "degraded",
            "ssh": "up" if ssh_ok else "down",
            "api": "up" if api_ok else "down",
            "db_path": str(self.settings.db_path),
        }

    @staticmethod
    def _connect_host(host: str) -> str:
        return "127.0.0.1" if host == "0.0.0.0" else host

    @staticmethod
    def _can_connect(host: str, port: int) -> bool:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            return False

